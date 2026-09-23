from core.execution_feedback import ExecutionFeedback
from core.observation import Observation


def test_build_committed_result():
    result = {
        "approval_id": "12",
        "status": "committed",
        "transaction_id": "tx-123",
        "tests": {"success": True},
        "git": {"status": "committed"},
        "repair_attempts": 0,
    }

    observation = ExecutionFeedback().build(result)

    assert isinstance(observation, Observation)
    assert observation.instruction == "Avaliar resultado da transação."
    assert observation.metadata["source"] == "transaction_result"
    assert observation.metadata["transaction_id"] == "tx-123"
    assert observation.metadata["status"] == "committed"
    assert observation.metadata["tests"] == {"success": True}
    assert observation.metadata["git"] == {"status": "committed"}


def test_build_rolled_back_result():
    result = {
        "approval_id": "12",
        "status": "rolled_back",
        "transaction_id": "tx-456",
        "tests": {"success": False},
        "repair_attempts": 2,
        "error": "test failure",
    }

    observation = ExecutionFeedback().build(result)

    assert observation.metadata["status"] == "rolled_back"
    assert observation.metadata["transaction_id"] == "tx-456"
    assert observation.metadata["repair_attempts"] == 2
    assert observation.metadata["error"] == "test failure"


def test_build_failed_result():
    result = {
        "approval_id": "12",
        "status": "failed",
        "transaction_id": "tx-789",
        "rollback_error": "rollback failed",
    }

    observation = ExecutionFeedback().build(result)

    assert observation.metadata["status"] == "failed"
    assert observation.metadata["rollback_error"] == "rollback failed"


def test_non_final_result_returns_none():
    result = {
        "status": "executing",
        "transaction_id": "tx-123",
    }

    assert ExecutionFeedback().build(result) is None


def test_invalid_result_is_rejected():
    try:
        ExecutionFeedback().build(None)
    except ValueError as exc:
        assert str(exc) == "Resultado de execução inválido."
    else:
        raise AssertionError("Era esperado ValueError.")


def test_missing_transaction_id_is_rejected():
    result = {
        "status": "committed",
    }

    try:
        ExecutionFeedback().build(result)
    except ValueError as exc:
        assert str(exc) == "Resultado sem transaction_id."
    else:
        raise AssertionError("Era esperado ValueError.")

def test_pipeline_feedback_generates_corrected_content(tmp_path):
    from core.adapters.mock import MockAdapter
    from core.pipeline import DevAgentPipeline

    broken = tmp_path / "broken.py"
    broken.write_text("def broken(:\\n", encoding="utf-8")

    pipeline = DevAgentPipeline(
        root=tmp_path,
        ai_adapter=MockAdapter(),
    )

    feedback_context = {
        "transaction_id": "tx-syntax-error",
        "status": "failed",
        "evidence": {
            "error": "SyntaxError: invalid syntax",
        },
        "transaction_metadata": {
            "changes": [
                {
                    "change_type": "create",
                    "path": "broken.py",
                    "content": "def broken(:\\n",
                    "reason": "Criar arquivo.",
                }
            ]
        },
    }

    result = pipeline.process(
        "corrigir falha da transação tx-syntax-error",
        feedback_context=feedback_context,
    )

    plan = result

    assert plan.changes[0].path == "broken.py"
    assert plan.changes[0].change_type.value == "modify"
    assert plan.changes[0].content != "def broken(:\\n"
    assert "SyntaxError" in plan.changes[0].reason
