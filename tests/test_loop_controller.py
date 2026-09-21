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


def test_run_continuous_executes_until_max_iterations():
    class Loop(LoopController):
        def run_once(self):
            self._iterations += 1
            return self._iterations

    loop = Loop()
    sleeps = []

    results = loop.run_continuous(
        interval_seconds=0,
        max_iterations=3,
        sleep_fn=sleeps.append,
    )

    assert results == [1, 2, 3]
    assert loop.iterations == 3
    assert loop.stopped is False
    assert sleeps == []


def test_run_continuous_sleeps_between_iterations():
    class Loop(LoopController):
        def run_once(self):
            self._iterations += 1
            return self._iterations

    loop = Loop()
    sleeps = []

    results = loop.run_continuous(
        interval_seconds=2.5,
        max_iterations=3,
        sleep_fn=sleeps.append,
    )

    assert results == [1, 2, 3]
    assert sleeps == [2.5, 2.5]


def test_run_continuous_propagates_run_once_failure():
    class Loop(LoopController):
        def __init__(self):
            super().__init__()
            self.calls = 0

        def run_once(self):
            self.calls += 1
            raise RuntimeError("LOOP_FAILURE")

    loop = Loop()
    sleeps = []

    with pytest.raises(RuntimeError, match="LOOP_FAILURE"):
        loop.run_continuous(
            interval_seconds=1,
            sleep_fn=sleeps.append,
        )

    assert loop.calls == 1
    assert sleeps == []


def test_run_continuous_stops_when_run_once_requests_stop():
    class Loop(LoopController):
        def run_once(self):
            self._iterations += 1
            self.stop()
            return self._iterations

    loop = Loop()

    results = loop.run_continuous(
        interval_seconds=1,
        sleep_fn=lambda _: (_ for _ in ()).throw(
            AssertionError("não deveria dormir após stop")
        ),
    )

    assert results == [1]
    assert loop.iterations == 1
    assert loop.stopped is True


def test_run_continuous_rejects_invalid_interval():
    class Loop(LoopController):
        def run_once(self):
            return None

    loop = Loop()

    for value in (-1, float("nan"), float("inf"), True, "1"):
        with pytest.raises(ValueError, match="interval_seconds"):
            loop.run_continuous(value)


def test_run_continuous_rejects_invalid_max_iterations():
    class Loop(LoopController):
        def run_once(self):
            return None

    loop = Loop()

    for value in (0, -1, True, 1.5, "3"):
        with pytest.raises(ValueError, match="max_iterations"):
            loop.run_continuous(max_iterations=value)


def test_run_continuous_rejects_invalid_sleep_function():
    class Loop(LoopController):
        def run_once(self):
            return None

    loop = Loop()

    with pytest.raises(ValueError, match="sleep_fn"):
        loop.run_continuous(
            max_iterations=1,
            sleep_fn=None,
        )