from concurrent.futures import ThreadPoolExecutor

from core.memory.persistent_store import PersistentStore


def test_persistent_store_serializes_concurrent_writes(tmp_path):
    path = tmp_path / "state.json"
    store = PersistentStore(path)

    def write(value):
        store.save({"value": value})

    with ThreadPoolExecutor(max_workers=8) as executor:
        list(
            executor.map(
                write,
                range(50),
            )
        )

    result = store.load()

    assert isinstance(result, dict)
    assert "value" in result
    assert 0 <= result["value"] < 50


def test_persistent_store_last_state_is_valid_after_concurrent_writes(
    tmp_path,
):
    path = tmp_path / "state.json"
    store = PersistentStore(path)

    def write(value):
        store.save(
            {
                "value": value,
                "nested": {
                    "number": value,
                },
            }
        )

    with ThreadPoolExecutor(max_workers=4) as executor:
        list(
            executor.map(
                write,
                range(100),
            )
        )

    result = store.load()

    assert result["value"] == result["nested"]["number"]
