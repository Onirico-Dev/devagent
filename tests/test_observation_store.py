import os
from pathlib import Path

import pytest

from core.observation_store import ObservationStore
from core.observer import Observation


def test_store_load_empty(tmp_path: Path):
    store = ObservationStore(tmp_path / "observations.json")

    assert store.load() == []


def test_store_append_and_load(tmp_path: Path):
    store = ObservationStore(tmp_path / "observations.json")
    observation = Observation(
        instruction="criar arquivo app.py",
        metadata={"source": "test"},
    )

    store.append(observation)

    assert store.load() == [observation]


def test_store_save_and_load_multiple(tmp_path: Path):
    store = ObservationStore(tmp_path / "observations.json")
    observations = [
        Observation("primeira", {"source": "a"}),
        Observation("segunda", {"source": "b"}),
    ]

    store.save(observations)

    assert store.load() == observations


def test_store_rejects_invalid_record(tmp_path: Path):
    path = tmp_path / "observations.json"
    path.write_text('{"invalid": true}', encoding="utf-8")

    store = ObservationStore(path)

    with pytest.raises(ValueError, match="Armazenamento"):
        store.load()


def test_store_rejects_invalid_observation_on_append(tmp_path: Path):
    store = ObservationStore(tmp_path / "observations.json")

    with pytest.raises(ValueError, match="Observação"):
        store.append("invalid")


def test_store_rejects_invalid_observation_on_save(tmp_path: Path):
    store = ObservationStore(tmp_path / "observations.json")

    with pytest.raises(ValueError, match="Observação"):
        store.save(["invalid"])


def test_save_fsyncs_file_and_parent_directory(tmp_path, monkeypatch):
    store = ObservationStore(tmp_path / "observations.json")
    observation = Observation("teste", {"source": "test"})
    fsync_calls = []

    original_fsync = os.fsync

    def tracked_fsync(fd):
        fsync_calls.append(fd)
        return original_fsync(fd)

    monkeypatch.setattr(os, "fsync", tracked_fsync)

    store.save([observation])

    assert len(fsync_calls) == 2


def test_serialize_rejects_non_list():
    from core.observation_store import ObservationStore
    import pytest

    with pytest.raises(ValueError, match="Observações inválidas"):
        ObservationStore._serialize("invalid")


def test_serialize_rejects_invalid_observation():
    from core.observation_store import ObservationStore
    import pytest

    with pytest.raises(ValueError, match="Observação inválida"):
        ObservationStore._serialize([object()])


def test_deserialize_rejects_non_dict_record():
    from core.observation_store import ObservationStore
    import pytest

    with pytest.raises(ValueError, match="Registro de observação inválido"):
        ObservationStore._deserialize([object()])


def test_deserialize_rejects_invalid_instruction():
    from core.observation_store import ObservationStore
    import pytest

    with pytest.raises(ValueError, match="Instrução de observação inválida"):
        ObservationStore._deserialize([{"instruction": "   ", "metadata": {}}])


def test_deserialize_rejects_invalid_metadata():
    from core.observation_store import ObservationStore
    import pytest

    with pytest.raises(ValueError, match="Metadados de observação inválidos"):
        ObservationStore._deserialize([{"instruction": "teste", "metadata": []}])


def test_save_removes_temporary_file_on_failure(monkeypatch, tmp_path):
    from core.observation_store import ObservationStore, Observation

    store = ObservationStore(tmp_path / "observations.json")

    def fail_replace(*args, **kwargs):
        raise OSError("replace failed")

    monkeypatch.setattr("os.replace", fail_replace)

    try:
        store.save([Observation("teste", {})])
    except OSError:
        pass

    assert not list(tmp_path.glob("*.tmp"))

def _observation_store_append_process(path, start_event, ready_queue, index):
    from core.observation import Observation
    from core.observation_store import ObservationStore

    store = ObservationStore(path)

    ready_queue.put("ready")
    start_event.wait(timeout=10)

    store.append(
        Observation(
            instruction=f"observacao-{index}",
            metadata={"process": index},
        )
    )


def test_observation_store_serializes_concurrent_appends_across_processes(
    tmp_path,
):
    import multiprocessing as mp

    path = tmp_path / "observations.json"
    ObservationStore(path).save([])

    context = mp.get_context("spawn")
    start_event = context.Event()
    ready_queue = context.Queue()

    processes = [
        context.Process(
            target=_observation_store_append_process,
            args=(str(path), start_event, ready_queue, index),
        )
        for index in range(2)
    ]

    for process in processes:
        process.start()

    ready_queue.get(timeout=10)
    ready_queue.get(timeout=10)

    start_event.set()

    for process in processes:
        process.join(timeout=15)

    assert all(not process.is_alive() for process in processes)
    assert all(process.exitcode == 0 for process in processes)

    observations = ObservationStore(path).load()

    assert len(observations) == 2
    assert {
        observation.instruction
        for observation in observations
    } == {
        "observacao-0",
        "observacao-1",
    }
