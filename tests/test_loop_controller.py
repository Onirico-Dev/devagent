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
