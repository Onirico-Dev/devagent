import pytest
from core.loop_controller import LoopController


class _TestLoop(LoopController):
    def run_once(self):
        self._iterations += 1
        return self._iterations


def test_stop_marks_controller_as_stopped():
    loop = _TestLoop()

    assert loop.stopped is False

    loop.stop()

    assert loop.stopped is True

def test_run_executes_requested_iterations_and_returns_results():
    loop = _TestLoop()

    assert loop.run(3) == [1, 2, 3]
    assert loop.iterations == 3


def test_run_stops_before_next_iteration():
    loop = _TestLoop()
    loop.stop()

    assert loop.run(3) == []
    assert loop.iterations == 0


def test_run_rejects_zero():
    loop = _TestLoop()

    with pytest.raises(ValueError, match="max_iterations"):
        loop.run(0)


def test_run_rejects_negative_iterations():
    loop = _TestLoop()

    with pytest.raises(ValueError, match="max_iterations"):
        loop.run(-1)


def test_run_rejects_boolean_iterations():
    loop = _TestLoop()

    with pytest.raises(ValueError, match="max_iterations"):
        loop.run(True)


def test_run_rejects_non_integer_iterations():
    loop = _TestLoop()

    with pytest.raises(ValueError, match="max_iterations"):
        loop.run("3")


def test_start_resumes_controller():
    loop = _TestLoop()

    loop.stop()
    assert loop.stopped is True

    loop.start()

    assert loop.stopped is False
    assert loop.run(1) == [1]
