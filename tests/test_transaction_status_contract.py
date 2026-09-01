from core.schemas.models import Transaction, TransactionStatus


def test_transaction_status_enum_contains_only_transaction_lifecycle_states():
    assert {status.value for status in TransactionStatus} == {
        "pending",
        "approved",
        "executing",
        "testing",
        "committed",
        "rolled_back",
        "failed",
    }


def test_transaction_starts_pending():
    transaction = Transaction(transaction_id="tx-1")

    assert transaction.status is TransactionStatus.PENDING


def test_transaction_execution_statuses_are_distinct_from_repair_cycle_states():
    transaction_statuses = {status.value for status in TransactionStatus}

    repair_only_states = {
        "analyzing",
        "repairing",
        "verified",
        "repair_failed",
    }

    assert transaction_statuses.isdisjoint(repair_only_states)


def test_transaction_status_values_are_strings():
    for status in TransactionStatus:
        assert isinstance(status.value, str)


def test_transaction_status_enum_is_string_compatible():
    assert TransactionStatus.PENDING == "pending"
    assert TransactionStatus.EXECUTING == "executing"
    assert TransactionStatus.TESTING == "testing"
    assert TransactionStatus.COMMITTED == "committed"
    assert TransactionStatus.ROLLED_BACK == "rolled_back"
    assert TransactionStatus.FAILED == "failed"
