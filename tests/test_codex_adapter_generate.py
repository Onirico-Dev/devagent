import pytest

from core.adapters.base import AIAdapter
from core.adapters.codex_adapter import CodexAdapter


class FakeTransport:
    instances = []

    def __init__(self, timeout=120, command=None):
        self.timeout = timeout
        self.command = command
        self.entered = False
        self.closed = False
        self.prompt = None
        self.response = "  resposta válida  "
        self.fail_on_turn = False
        self.__class__.instances.append(self)

    def __enter__(self):
        self.entered = True
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.closed = True

    def create_session(self):
        return "thread-test"

    def start_turn(self, thread_id, prompt):
        assert thread_id == "thread-test"
        self.prompt = prompt
        if self.fail_on_turn:
            raise RuntimeError("Falha simulada")
        return "turn-test"

    def wait_turn(self, thread_id, turn_id):
        assert thread_id == "thread-test"
        assert turn_id == "turn-test"
        return self.response


@pytest.fixture(autouse=True)
def clear_instances():
    FakeTransport.instances.clear()


def test_codex_adapter_implements_aiadapter():
    adapter = CodexAdapter(transport_factory=FakeTransport)
    assert isinstance(adapter, AIAdapter)


def test_generate_returns_text_and_closes_transport():
    adapter = CodexAdapter(
        timeout=17,
        transport_factory=FakeTransport,
    )

    result = adapter.generate("Crie um plano JSON.")

    transport = FakeTransport.instances[-1]

    assert result == "resposta válida"
    assert transport.prompt == "Crie um plano JSON."
    assert transport.timeout == 17
    assert transport.entered
    assert transport.closed


@pytest.mark.parametrize("prompt", [None, 1, [], {}])
def test_generate_rejects_non_string_prompt(prompt):
    adapter = CodexAdapter(transport_factory=FakeTransport)

    with pytest.raises(TypeError):
        adapter.generate(prompt)

    assert FakeTransport.instances == []


@pytest.mark.parametrize("prompt", ["", " ", "\n\t"])
def test_generate_rejects_empty_prompt(prompt):
    adapter = CodexAdapter(transport_factory=FakeTransport)

    with pytest.raises(ValueError):
        adapter.generate(prompt)

    assert FakeTransport.instances == []


@pytest.mark.parametrize("timeout", [0, -1, True, None, "10"])
def test_invalid_timeout(timeout):
    with pytest.raises(ValueError):
        CodexAdapter(
            timeout=timeout,
            transport_factory=FakeTransport,
        )


def test_generate_closes_transport_after_failure():
    class FailingTransport(FakeTransport):
        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            self.fail_on_turn = True

    adapter = CodexAdapter(
        transport_factory=FailingTransport,
    )

    with pytest.raises(RuntimeError, match="Falha simulada"):
        adapter.generate("Plano de teste")

    assert FakeTransport.instances[-1].closed


@pytest.mark.parametrize("response", ["", "   ", None, 123])
def test_generate_rejects_invalid_response(response):
    class InvalidResponseTransport(FakeTransport):
        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            self.response = response

    adapter = CodexAdapter(
        transport_factory=InvalidResponseTransport,
    )

    with pytest.raises(RuntimeError, match="resposta textual"):
        adapter.generate("Plano de teste")

    assert FakeTransport.instances[-1].closed


def test_custom_command_is_forwarded():
    adapter = CodexAdapter(
        command=["fake-codex", "app-server"],
        transport_factory=FakeTransport,
    )

    adapter.generate("Plano de teste")

    assert FakeTransport.instances[-1].command == (
        "fake-codex",
        "app-server",
    )
