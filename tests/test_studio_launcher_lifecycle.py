"""Exercise the real launcher with fake adapter/server boundaries."""
import importlib.util
import signal
import subprocess
import sys
import threading
import types
from pathlib import Path

import pytest


LAUNCHER = Path(__file__).resolve().parents[1] / "scripts" / "start_studio.py"


def load_launcher():
    spec = importlib.util.spec_from_file_location("studio_launcher_under_test", LAUNCHER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def fake_adapter_modules(monkeypatch):
    class CodexAdapter:
        pass

    fake_api = types.ModuleType("api")
    fake_api.agent = types.SimpleNamespace(ai=CodexAdapter())
    fake_api.APIHandler = object
    fake_codex = types.ModuleType("core.adapters.codex_adapter")
    fake_codex.CodexAdapter = CodexAdapter
    monkeypatch.setitem(sys.modules, "api", fake_api)
    monkeypatch.setitem(sys.modules, "core.adapters.codex_adapter", fake_codex)
    monkeypatch.setenv("DEVAGENT_AI", "mock")
    monkeypatch.setattr(sys, "argv", [str(LAUNCHER), "--no-browser"])


@pytest.mark.parametrize("failure, reason", [
    (None, "loop_returned"),
    (KeyboardInterrupt(), "keyboard_interrupt"),
    (RuntimeError("PRIVATE"), "loop_failure"),
    (SystemExit(7), "loop_failure"),
])
def test_launcher_manages_worker_and_preserves_failure(monkeypatch, capsys, failure, reason):
    fake_adapter_modules(monkeypatch)
    launcher = load_launcher()
    events = []

    class Server:
        server_port = 8765

        def __init__(self, *args):
            pass

        def serve_forever(self):
            events.append(("serve", threading.get_ident()))
            if failure is not None:
                raise failure

        def shutdown(self):
            raise AssertionError("shutdown must not wait on an already failed worker")

        def server_close(self):
            events.append(("close", threading.get_ident()))

    monkeypatch.setattr(launcher, "HTTPServer", Server)
    monkeypatch.setattr(launcher.shutil, "which", lambda name: None)
    if isinstance(failure, (RuntimeError, SystemExit)):
        with pytest.raises(type(failure)) as caught:
            launcher.main()
        assert caught.value is failure
    else:
        launcher.main()
    assert [event for event, ident in events] == ["serve", "close"]
    assert events[0][1] != threading.get_ident()
    assert events[1][1] == threading.get_ident()
    err = capsys.readouterr().err
    assert reason in err
    assert "PRIVATE" not in err


def test_launcher_identifies_bind_failure(monkeypatch, capsys):
    fake_adapter_modules(monkeypatch)
    launcher = load_launcher()

    def fail(*args):
        raise OSError(98, "PRIVATE")

    monkeypatch.setattr(launcher, "HTTPServer", fail)
    with pytest.raises(OSError):
        launcher.main()
    err = capsys.readouterr().err
    assert "startup_failure" in err and "OSError" in err
    assert "PRIVATE" not in err


@pytest.mark.parametrize("failure, expected", [("RuntimeError('PRIVATE')", 1), ("SystemExit(7)", 7)])
def test_launcher_process_does_not_report_success_when_serving_fails(failure, expected):
    code = """
import http.server, runpy, sys, types
class Adapter: pass
api = types.ModuleType('api')
api.agent = types.SimpleNamespace(ai=Adapter())
api.APIHandler = object
codex = types.ModuleType('core.adapters.codex_adapter')
codex.CodexAdapter = Adapter
sys.modules['api'] = api
sys.modules['core.adapters.codex_adapter'] = codex
class Server:
    server_port = 8765
    def __init__(self, *args): pass
    def serve_forever(self): raise FAILURE
    def shutdown(self): pass
    def server_close(self): print('CLOSED', flush=True)
http.server.HTTPServer = Server
sys.argv = [LAUNCHER, '--no-browser']
runpy.run_path(LAUNCHER, run_name='__main__')
""".replace("FAILURE", failure).replace("LAUNCHER", repr(str(LAUNCHER)))
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=10)
    assert result.returncode == expected
    assert "CLOSED" in result.stdout
    assert "loop_failure" in result.stderr


def test_keyboard_interrupt_waits_for_active_worker_before_close(monkeypatch):
    fake_adapter_modules(monkeypatch)
    launcher = load_launcher()
    started = threading.Event()
    stop = threading.Event()
    events = []
    original_thread = threading.Thread

    class Server:
        server_port = 8765

        def __init__(self, *args):
            pass

        def serve_forever(self):
            events.append("serving")
            started.set()
            assert stop.wait(5), "worker cleanup did not release active request"
            events.append("request_finished")

        def shutdown(self):
            events.append("shutdown")
            stop.set()

        def server_close(self):
            assert "request_finished" in events
            events.append("close")

    class InterruptingJoin(original_thread):
        joins = 0

        def join(self, *args, **kwargs):
            self.joins += 1
            if self.joins == 1:
                assert started.wait(5)
                raise KeyboardInterrupt
            return super().join(*args, **kwargs)

    monkeypatch.setattr(launcher, "HTTPServer", Server)
    monkeypatch.setattr(launcher.threading, "Thread", InterruptingJoin)
    monkeypatch.setattr(launcher.shutil, "which", lambda name: None)
    launcher.main()
    assert events == ["serving", "shutdown", "request_finished", "close"]


def test_thread_start_failure_still_closes_server(monkeypatch, capsys):
    fake_adapter_modules(monkeypatch)
    launcher = load_launcher()
    closed = []

    class Server:
        server_port = 8765

        def __init__(self, *args):
            pass

        def serve_forever(self):
            pass

        def server_close(self):
            closed.append(True)

    class FailedThread:
        ident = None

        def __init__(self, **kwargs):
            assert kwargs["daemon"] is False

        def start(self):
            raise RuntimeError("PRIVATE")

    monkeypatch.setattr(launcher, "HTTPServer", Server)
    monkeypatch.setattr(launcher.threading, "Thread", FailedThread)
    with pytest.raises(RuntimeError):
        launcher.main()
    assert closed == [True]
    assert "startup_failure" in capsys.readouterr().err


def test_real_sigint_waits_for_worker_before_closing_socket():
    code = """
import http.server, runpy, sys, threading, types
class Adapter: pass
api = types.ModuleType('api')
api.agent = types.SimpleNamespace(ai=Adapter())
api.APIHandler = object
codex = types.ModuleType('core.adapters.codex_adapter')
codex.CodexAdapter = Adapter
sys.modules['api'] = api
sys.modules['core.adapters.codex_adapter'] = codex
stop = threading.Event()
class Server:
    server_port = 8765
    finished = False
    def __init__(self, *args): pass
    def serve_forever(self):
        if not stop.wait(5): raise RuntimeError('shutdown was not requested')
        self.finished = True
        print('REQUEST_FINISHED', flush=True)
    def shutdown(self):
        print('SHUTDOWN', flush=True)
        stop.set()
    def server_close(self):
        assert self.finished, 'socket closed before worker finished'
        print('CLOSED', flush=True)
http.server.HTTPServer = Server
sys.argv = [LAUNCHER, '--no-browser']
runpy.run_path(LAUNCHER, run_name='__main__')
""".replace("LAUNCHER", repr(str(LAUNCHER)))
    process = subprocess.Popen([sys.executable, "-c", code], stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, text=True)
    try:
        while True:
            line = process.stdout.readline()
            assert line, "launcher exited before becoming ready"
            if "Mantenha esta sessão" in line:
                break
        process.send_signal(signal.SIGINT)
        stdout, stderr = process.communicate(timeout=10)
        assert process.returncode == 0, stderr
        assert stdout.index("SHUTDOWN") < stdout.index("REQUEST_FINISHED") < stdout.index("CLOSED")
        assert "keyboard_interrupt" in stderr
    finally:
        if process.poll() is None:
            process.kill()
            process.communicate(timeout=5)
