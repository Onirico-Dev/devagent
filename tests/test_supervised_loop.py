import json

import pytest

from core.supervised_loop import SupervisedLoop


class FakeWorker:
    def __init__(self, proposals=None):
        self.proposals = list(proposals or [])
        self.calls = 0

    def run_once(self):
        self.calls += 1
        proposals = self.proposals
        self.proposals = []
        return proposals


class FakeGateway:
    def __init__(self, tasks=None):
        self.tasks = list(tasks or [])
        self.created = []

    def list_tasks(self):
        return list(self.tasks)

    def create_task(self, instruction):
        self.created.append(instruction)
        task = {
            "approval_id": str(len(self.created)),
            "instruction": instruction,
            "status": "pending",
        }
        self.tasks.append(task)
        return task


def test_new_observation_creates_pending_proposal():
    worker = FakeWorker(
        [
            {
                "instruction": "crie arquivo_a.txt",
                "approval_id": "1",
                "status": "pending",
                "plan": {},
            }
        ]
    )
    gateway = FakeGateway()

    loop = SupervisedLoop(worker=worker, gateway=gateway)

    result = loop.run_once()

    assert len(result.proposals) == 1
    assert result.proposals[0]["instruction"] == "crie arquivo_a.txt"
    assert result.proposals[0]["approval_id"] == "1"
    assert result.metadata["proposal_count"] == 1


def test_second_round_does_not_duplicate_existing_pending_proposal():
    worker = FakeWorker(
        [
            {
                "instruction": "crie arquivo_a.txt",
                "approval_id": "1",
                "status": "pending",
                "plan": {},
            }
        ]
    )
    gateway = FakeGateway()

    loop = SupervisedLoop(worker=worker, gateway=gateway)

    first = loop.run_once()
    second = loop.run_once()

    assert len(first.proposals) == 1
    assert second.proposals == []


def test_pending_state_is_reported_without_crossing_approval_barrier():
    worker = FakeWorker()
    gateway = FakeGateway(
        [
            {
                "approval_id": "10",
                "instruction": "crie arquivo.txt",
                "status": "pending",
            }
        ]
    )

    loop = SupervisedLoop(worker=worker, gateway=gateway)

    result = loop.run_once()

    assert result.proposals == []
    assert result.metadata["pending_count"] == 1


@pytest.mark.parametrize(
    "status",
    ["committed", "rejected", "rolled_back", "failed"],
)
def test_terminal_task_does_not_become_new_execution(status):
    worker = FakeWorker()
    gateway = FakeGateway(
        [
            {
                "approval_id": "10",
                "instruction": "crie arquivo.txt",
                "status": status,
            }
        ]
    )

    loop = SupervisedLoop(worker=worker, gateway=gateway)

    result = loop.run_once()

    assert result.proposals == []
    assert result.metadata["pending_count"] == 0


def test_stop_prevents_future_rounds():
    worker = FakeWorker(
        [
            {
                "instruction": "crie arquivo.txt",
                "approval_id": "1",
                "status": "pending",
                "plan": {},
            }
        ]
    )
    gateway = FakeGateway()

    loop = SupervisedLoop(worker=worker, gateway=gateway)

    loop.stop()
    result = loop.run_once()

    assert result.stopped is True
    assert result.proposals == []
    assert worker.calls == 0


def test_invalid_worker_is_rejected():
    with pytest.raises(ValueError, match="Worker inválido"):
        SupervisedLoop(worker=object(), gateway=FakeGateway())


def test_invalid_gateway_is_rejected():
    with pytest.raises(ValueError, match="Gateway inválido"):
        SupervisedLoop(worker=FakeWorker(), gateway=object())


def test_export_state_contains_loop_state():
    loop = SupervisedLoop(
        worker=FakeWorker(),
        gateway=FakeGateway(),
    )

    state = loop.export_state()

    assert isinstance(state, dict)
    assert state["stopped"] is False
    assert state["iterations"] == 0


def test_restore_state_validates_mapping():
    loop = SupervisedLoop(
        worker=FakeWorker(),
        gateway=FakeGateway(),
    )

    with pytest.raises(ValueError, match="Estado inválido"):
        loop.restore_state([])


def test_restore_state_restores_iterations_and_stop():
    loop = SupervisedLoop(
        worker=FakeWorker(),
        gateway=FakeGateway(),
    )

    loop.restore_state(
        {
            "stopped": True,
            "iterations": 4,
        }
    )

    assert loop.stopped is True
    assert loop.iterations == 4


def test_supervised_loop_preserves_external_approval_barrier():
    class WorkerWithProposal:
        def __init__(self):
            self.calls = 0

        def run_once(self):
            self.calls += 1
            return [
                {
                    "instruction": "crie arquivo.txt",
                    "approval_id": "42",
                    "status": "pending",
                    "plan": {},
                }
            ]

    class GatewayWithApprovalGuard:
        def __init__(self):
            self.approve_called = False

        def list_tasks(self):
            return [
                {
                    "approval_id": "42",
                    "instruction": "crie arquivo.txt",
                    "status": "pending",
                }
            ]

        def approve(self, approval_id):
            self.approve_called = True
            raise AssertionError(
                "SupervisedLoop não deve aprovar automaticamente."
            )

    worker = WorkerWithProposal()
    gateway = GatewayWithApprovalGuard()

    loop = SupervisedLoop(worker=worker, gateway=gateway)

    result = loop.run_once()

    assert len(result.proposals) == 1
    assert result.proposals[0]["approval_id"] == "42"
    assert gateway.approve_called is False


def test_supervised_loop_does_not_execute_pending_task():
    class WorkerWithProposal:
        def run_once(self):
            return [
                {
                    "instruction": "crie arquivo.txt",
                    "approval_id": "43",
                    "status": "pending",
                    "plan": {},
                }
            ]

    class Gateway:
        def list_tasks(self):
            return [
                {
                    "approval_id": "43",
                    "instruction": "crie arquivo.txt",
                    "status": "pending",
                }
            ]

        def approve(self, approval_id):
            raise AssertionError("aprovação automática proibida")

        def execute_approved(self, approval_id):
            raise AssertionError("execução automática proibida")

    loop = SupervisedLoop(
        worker=WorkerWithProposal(),
        gateway=Gateway(),
    )

    result = loop.run_once()

    assert result.metadata["pending_count"] == 1


def test_supervised_loop_can_observe_after_external_decision():
    class Worker:
        def __init__(self):
            self.round = 0

        def run_once(self):
            self.round += 1
            if self.round == 1:
                return [
                    {
                        "instruction": "crie arquivo.txt",
                        "approval_id": "44",
                        "status": "pending",
                        "plan": {},
                    }
                ]
            return []

    class Gateway:
        def __init__(self):
            self.status = "pending"

        def list_tasks(self):
            return [
                {
                    "approval_id": "44",
                    "instruction": "crie arquivo.txt",
                    "status": self.status,
                }
            ]

    worker = Worker()
    gateway = Gateway()
    loop = SupervisedLoop(worker=worker, gateway=gateway)

    first = loop.run_once()

    assert len(first.proposals) == 1
    assert first.metadata["pending_count"] == 1

    gateway.status = "committed"

    second = loop.run_once()

    assert second.proposals == []
    assert second.metadata["pending_count"] == 0
    assert loop.iterations == 2
