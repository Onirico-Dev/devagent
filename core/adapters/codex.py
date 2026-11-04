"""Transporte experimental para o Codex App Server.

Não concede aprovações nem executa alterações no projeto.
"""

import json
import os
import selectors
import subprocess
import tempfile
import time
from collections import deque
from threading import RLock


class CodexProtocolError(RuntimeError):
    """Erro de comunicação ou protocolo JSON-RPC."""


class CodexTransport:
    DEFAULT_COMMAND = (
        "proot-distro",
        "login",
        "debian",
        "--",
        "/usr/local/bin/codex",
        "app-server",
        "--listen",
        "stdio://",
    )

    def __init__(self, command=None, timeout=120):
        if timeout <= 0:
            raise ValueError("Timeout deve ser positivo.")

        self.command = tuple(command or self.DEFAULT_COMMAND)
        self.timeout = timeout
        self._lock = RLock()
        self._process = None
        self._selector = None
        self._workspace = None
        self._buffer = bytearray()
        self._events = deque(maxlen=1000)
        self._terminal_events = {}
        self._responses = {}
        self._pending_requests = set()
        self._next_id = 0

    def _send(self, message):
        if self._process is None or self._process.poll() is not None:
            raise CodexProtocolError("Codex não está ativo.")

        payload = (
            json.dumps(message, ensure_ascii=False) + "\n"
        ).encode("utf-8")

        try:
            self._process.stdin.write(payload)
            self._process.stdin.flush()
        except (BrokenPipeError, OSError) as error:
            raise CodexProtocolError(
                "Falha ao enviar mensagem ao Codex."
            ) from error

    def _read_message(self, deadline):
        while True:
            newline = self._buffer.find(b"\n")

            if newline >= 0:
                raw = bytes(self._buffer[:newline])
                del self._buffer[:newline + 1]

                if not raw.strip():
                    continue

                try:
                    message = json.loads(raw)
                except (ValueError, UnicodeDecodeError) as error:
                    raise CodexProtocolError(
                        "Mensagem JSON-RPC inválida."
                    ) from error

                if not isinstance(message, dict):
                    raise CodexProtocolError(
                        "Mensagem JSON-RPC não é um objeto."
                    )

                return message

            remaining = deadline - time.monotonic()

            if remaining <= 0:
                raise TimeoutError("Codex excedeu o tempo limite.")

            ready = self._selector.select(min(remaining, 0.5))

            if not ready:
                if self._process.poll() is not None:
                    raise CodexProtocolError(
                        "Processo Codex encerrou inesperadamente."
                    )
                continue

            chunk = os.read(self._process.stdout.fileno(), 65536)

            if not chunk:
                raise CodexProtocolError(
                    "Conexão com Codex encerrada."
                )

            self._buffer.extend(chunk)

            if len(self._buffer) > 4 * 1024 * 1024:
                raise CodexProtocolError(
                    "Mensagem excedeu o limite de 4 MiB."
                )

    def _dispatch(self, message):
        method = message.get("method")

        if method is not None and "id" in message:
            self._send({
                "jsonrpc": "2.0",
                "id": message["id"],
                "error": {
                    "code": -32601,
                    "message": "Solicitação não autorizada pelo DevAgent.",
                },
            })
            return

        if method is not None:
            if method in ("turn/completed", "turn/failed"):
                params = message.get("params", {})
                turn = params.get("turn", {}) if isinstance(params, dict) else None

                if not isinstance(params, dict) or not isinstance(turn, dict):
                    raise CodexProtocolError(
                        "Evento terminal JSON-RPC inválido."
                    )

                thread_id = params.get("threadId")
                turn_id = turn.get("id")

                if (
                    not isinstance(thread_id, str)
                    or not thread_id
                    or not isinstance(turn_id, str)
                    or not turn_id
                ):
                    raise CodexProtocolError(
                        "Identificadores de turno inválidos."
                    )

                key = (thread_id, turn_id)

                if key in self._terminal_events:
                    raise CodexProtocolError(
                        "Evento terminal duplicado."
                    )

                if len(self._terminal_events) >= 1000:
                    raise CodexProtocolError(
                        "Limite de eventos terminais excedido."
                    )

                self._terminal_events[key] = message
                return

            self._events.append(message)
            return

        if "id" in message:
            response_id = message["id"]

            if (
                not isinstance(response_id, int)
                or isinstance(response_id, bool)
                or response_id not in self._pending_requests
            ):
                raise CodexProtocolError(
                    "Resposta JSON-RPC com identificador desconhecido."
                )

            if response_id in self._responses:
                raise CodexProtocolError(
                    "Resposta JSON-RPC duplicada."
                )

            self._responses[response_id] = message
            return

        raise CodexProtocolError(
            "Mensagem JSON-RPC sem método ou identificador."
        )

    def _request(self, method, params, timeout=None):
        self._next_id += 1
        request_id = self._next_id

        self._pending_requests.add(request_id)

        try:
            self._send({
                "jsonrpc": "2.0",
                "id": request_id,
                "method": method,
                "params": params,
            })

            deadline = time.monotonic() + (
                self.timeout if timeout is None else timeout
            )

            while request_id not in self._responses:
                self._dispatch(self._read_message(deadline))

            response = self._responses.pop(request_id)
        except BaseException:
            self.close()
            raise
        finally:
            self._pending_requests.discard(request_id)

        if "error" in response:
            raise CodexProtocolError(
                f"Erro JSON-RPC em {method}: {response['error']}"
            )

        if "result" not in response:
            raise CodexProtocolError(
                f"Resposta sem resultado: {method}"
            )

        return response["result"]

    def start(self):
        with self._lock:
            if self._process is not None:
                if self._process.poll() is None:
                    return
                self.close()

            self._workspace = tempfile.TemporaryDirectory(
                prefix="devagent-codex-"
            )

            try:
                self._process = subprocess.Popen(
                    self.command,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                    bufsize=0,
                )

                self._selector = selectors.DefaultSelector()
                self._selector.register(
                    self._process.stdout,
                    selectors.EVENT_READ,
                )

                self._request("initialize", {
                    "clientInfo": {
                        "name": "devagent",
                        "title": "DevAgent",
                        "version": "0.1.0",
                    },
                    "capabilities": None,
                })

                self._send({
                    "jsonrpc": "2.0",
                    "method": "initialized",
                })

            except BaseException:
                self.close()
                raise

    def create_session(self):
        with self._lock:
            self.start()

            result = self._request("thread/start", {
                "cwd": self._workspace.name,
                "sandbox": "read-only",
                "approvalPolicy": "never",
                "ephemeral": True,
            })

            if result.get("sandbox", {}).get("type") != "readOnly":
                raise CodexProtocolError(
                    "Codex não confirmou a política readOnly."
                )

            if result.get("approvalPolicy") != "never":
                raise CodexProtocolError(
                    "Política de aprovação inesperada."
                )

            return result["thread"]["id"]

    def start_turn(self, thread_id, prompt):
        if not isinstance(thread_id, str) or not thread_id:
            raise ValueError("Thread inválida.")

        if not isinstance(prompt, str) or not prompt.strip():
            raise ValueError("Prompt inválido.")

        with self._lock:
            result = self._request("turn/start", {
                "threadId": thread_id,
                "input": [{
                    "type": "text",
                    "text": prompt,
                }],
                "sandboxPolicy": {
                    "type": "readOnly",
                    "networkAccess": False,
                },
                "approvalPolicy": "never",
            })

            return result["turn"]["id"]

    def wait_turn(self, thread_id, turn_id):
        with self._lock:
            deadline = time.monotonic() + self.timeout

            while True:
                event = self._terminal_events.pop(
                    (thread_id, turn_id),
                    None,
                )

                if event is not None:
                    method = event["method"]
                    params = event["params"]
                    turn = params["turn"]

                    if method == "turn/failed":
                        raise CodexProtocolError(
                            "Turno Codex falhou: "
                            + str(params.get("error", "erro desconhecido"))
                        )

                    if turn.get("status") != "completed":
                        raise CodexProtocolError(
                            "Turno não concluído com sucesso."
                        )

                    messages = [
                        item["text"]
                        for item in turn.get("items", [])
                        if item.get("type") == "agentMessage"
                        and item.get("phase") == "final_answer"
                        and isinstance(item.get("text"), str)
                    ]

                    if len(messages) != 1:
                        raise CodexProtocolError(
                            "Resposta final ausente ou ambígua."
                        )

                    return messages[0]

                self._dispatch(self._read_message(deadline))

    def get_events(self):
        with self._lock:
            events = list(self._events)
            self._events.clear()
            return events

    def close(self):
        with self._lock:
            process = self._process
            self._process = None

            if self._selector is not None:
                self._selector.close()
                self._selector = None

            if process is not None:
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait()

                for stream in (process.stdin, process.stdout):
                    if stream is not None:
                        stream.close()

            if self._workspace is not None:
                self._workspace.cleanup()
                self._workspace = None

            self._buffer.clear()
            self._events.clear()
            self._terminal_events.clear()
            self._responses.clear()
            self._pending_requests.clear()

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()
