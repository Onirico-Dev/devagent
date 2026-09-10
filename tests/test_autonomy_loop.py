import pytest

from core.autonomy_loop import AutonomyLoop
from core.observer import Observation, Observer
from core.worker import Worker


class FakeGateway:
    def __init__(self):
        self.calls = []

    def create_task(self, instruction):
        self.calls.append(instruction)
        return {
            "approval_id": str(len(self.calls)),
            "status": "pending",
            "plan": {
                "instruction": instruction,
                "changes": [],
            },
        }


def test_loop_requires_worker():
    with pytest.raises(ValueError, match="Worker inválido"):
        AutonomyLoop(None)


def test_loop_runs_one_observation_round():
    gateway = FakeGateway()
    worker = Worker(
        gateway,
        Observer([Observation("verificar projeto", {})]),
    )
    loop = AutonomyLoop(worker)

    result = loop.run_once()

    assert result.stopped is False
    assert len(result.proposals) == 1
    assert result.proposals[0].status == "pending"
    assert result.metadata["iterations"] == 1
    assert result.metadata["proposal_count"] == 1


def test_loop_is_idempotent_for_same_observation():
    gateway = FakeGateway()
    worker = Worker(
        gateway,
        Observer([Observation("verificar projeto", {})]),
    )
    loop = AutonomyLoop(worker)

    first = loop.run_once()
    second = loop.run_once()

    assert len(first.proposals) == 1
    assert second.proposals == []
    assert loop.iterations == 2
    assert gateway.calls == ["verificar projeto"]


def test_loop_can_be_stopped():
    gateway = FakeGateway()
    worker = Worker(
        gateway,
        Observer([Observation("verificar projeto", {})]),
    )
    loop = AutonomyLoop(worker)

    loop.stop()
    result = loop.run_once()

    assert loop.stopped is True
    assert result.stopped is True
    assert result.proposals == []
    assert result.metadata["iterations"] == 0
    assert gateway.calls == []


def test_loop_does_not_execute_approval():
    gateway = FakeGateway()
    worker = Worker(
        gateway,
        Observer([Observation("verificar projeto", {})]),
    )
    loop = AutonomyLoop(worker)

    result = loop.run_once()

    assert result.proposals[0].status == "pending"
    assert not hasattr(gateway, "approve")
    assert not hasattr(gateway, "execute_approved")
