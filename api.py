from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlsplit
import json
from pathlib import Path

from agent import DevAgent
from core.api.service import APIService
from core.gateway import (
    CommitTransactionError,
    DevAgentGateway,
)


WEB_ROOT = Path(__file__).resolve().parent / "devagent_studio"

MAX_REQUEST_BODY_BYTES = 1024 * 1024

# Allowlist: somente estes três recursos podem ser servidos.
STATIC_FILES = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/app.js": ("app.js", "application/javascript; charset=utf-8"),
    "/styles.css": ("styles.css", "text/css; charset=utf-8"),
}


agent = DevAgent(".")
gateway = DevAgentGateway(agent, ".")


class APIHandler(BaseHTTPRequestHandler):

    def _service(self):
        return APIService(agent, gateway)

    def send_json(self, status, data):
        body = json.dumps(
            data,
            ensure_ascii=False,
        ).encode("utf-8")

        self.send_response(status)

        self.send_header(
            "Content-Type",
            "application/json; charset=utf-8",
        )

        self.send_header(
            "Content-Length",
            str(len(body)),
        )

        self.send_header(
            "X-Content-Type-Options",
            "nosniff",
        )

        self.send_header(
            "Cache-Control",
            "no-cache",
        )

        self.end_headers()
        self.wfile.write(body)

    def handle_error(self, error):
        if isinstance(error, CommitTransactionError):
            self.send_json(
                200,
                {
                    "status": "failed",
                    "error": str(error),
                    **(
                        error.result
                        if isinstance(error.result, dict)
                        else {}
                    ),
                },
            )
            return

        if isinstance(error, KeyError):
            self.send_json(
                404,
                {
                    "error": str(error).strip("'"),
                },
            )
            return

        if isinstance(error, ValueError):
            self.send_json(
                409,
                {
                    "error": str(error),
                },
            )
            return

        self.send_json(
            500,
            {
                "error": str(error),
            },
        )

    def _serve_static(self, route):
        filename, content_type = STATIC_FILES[route]

        try:
            body = (WEB_ROOT / filename).read_bytes()

        except FileNotFoundError:
            self.send_json(
                404,
                {
                    "error": "Recurso estático não encontrado",
                },
            )
            return

        self.send_response(200)

        self.send_header(
            "Content-Type",
            content_type,
        )

        self.send_header(
            "Content-Length",
            str(len(body)),
        )

        self.send_header(
            "X-Content-Type-Options",
            "nosniff",
        )

        self.send_header(
            "Cache-Control",
            "no-cache",
        )

        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        try:
            path = urlsplit(self.path).path

            if path in STATIC_FILES:
                self._serve_static(path)
                return

            service = self._service()

            if path == "/health":
                self.send_json(
                    200,
                    service.health(),
                )
                return

            if path == "/tasks":
                self.send_json(
                    200,
                    {
                        "tasks": service.list_tasks(),
                    },
                )
                return

            if path == "/tasks/latest":
                task = service.latest_task()

                if task is None:
                    self.send_json(
                        404,
                        {
                            "error": "Nenhuma tarefa encontrada",
                        },
                    )
                    return

                self.send_json(200, task)
                return

            task_route = path.split("/")

            if (
                len(task_route) == 5 and task_route[1] == "tasks"
                and task_route[2] and task_route[3] == "investigation" and task_route[4]
            ):
                job = service.get_task_investigation(task_route[2], task_route[4])
                if job is None:
                    self.send_json(404, {"error": "Investigação não encontrada"})
                    return
                self.send_json(200, job)
                return

            if (
                len(task_route) == 4
                and task_route[1] == "tasks"
                and task_route[2]
                and task_route[3] == "diagnostic"
            ):
                report = service.task_diagnostic(task_route[2])
                if report is None:
                    self.send_json(404, {"error": "Tarefa não encontrada"})
                    return
                self.send_json(200, report)
                return

            if (
                len(task_route) == 3
                and task_route[1] == "tasks"
                and task_route[2]
            ):
                task_id = task_route[2]
                task = service.get_task(task_id)

                if task is None:
                    self.send_json(
                        404,
                        {
                            "error": "Tarefa não encontrada",
                        },
                    )
                    return

                self.send_json(200, task)
                return

            self.send_json(
                404,
                {
                    "error": "Endpoint não encontrado",
                },
            )

        except Exception as error:
            self.handle_error(error)

    def do_POST(self):
        path = urlsplit(self.path).path

        route = path.split("/")
        if len(route) == 4 and route[1] == "tasks" and route[2] and route[3] == "investigation":
            try:
                if self.headers.get("Content-Type", "").split(";")[0].strip().lower() != "application/json":
                    self.send_json(415, {"error": "Use Content-Type application/json"})
                    return
                length = self.headers.get("Content-Length", "")
                if not length.isdecimal() or not 0 < int(length) <= 64:
                    self.send_json(400, {"error": "Corpo da investigação inválido"})
                    return
                try:
                    body = json.loads(self.rfile.read(int(length)))
                except (ValueError, UnicodeDecodeError):
                    body = None
                if not isinstance(body, dict) or body:
                    self.send_json(400, {"error": "A investigação aceita somente um objeto JSON vazio"})
                    return
                job = self._service().start_task_investigation(route[2])
                if job is None:
                    self.send_json(404, {"error": "Tarefa não encontrada"})
                else:
                    self.send_json(202 if job["status"] == "running" else 200, job)
            except Exception as error:
                self.handle_error(error)
            return

        if path == "/plan":
            try:
                content_length = self.headers.get(
                    "Content-Length"
                )

                if content_length is None:
                    length = 0

                else:
                    if not content_length.isdecimal():
                        self.send_json(
                            400,
                            {
                                "error": "Content-Length inválido",
                            },
                        )
                        return

                    length = int(content_length)

                    if length > MAX_REQUEST_BODY_BYTES:
                        self.send_json(
                            413,
                            {
                                "error": (
                                    "Corpo da requisição excede "
                                    "o limite de 1 MiB"
                                ),
                            },
                        )
                        return

                raw = self.rfile.read(length)

                if len(raw) != length:
                    self.send_json(
                        400,
                        {
                            "error": "JSON inválido",
                        },
                    )
                    return

                try:
                    data = json.loads(raw)

                except (
                    json.JSONDecodeError,
                    UnicodeDecodeError,
                ):
                    self.send_json(
                        400,
                        {
                            "error": "JSON inválido",
                        },
                    )
                    return

                if not isinstance(data, dict):
                    self.send_json(
                        400,
                        {
                            "error": (
                                "O corpo da requisição deve ser "
                                "um objeto JSON"
                            ),
                        },
                    )
                    return

                instruction = data.get("instruction")

                if (
                    not isinstance(instruction, str)
                    or not instruction.strip()
                ):
                    self.send_json(
                        400,
                        {
                            "error": (
                                "Campo 'instruction' é obrigatório"
                            ),
                        },
                    )
                    return

                service = self._service()
                result = service.create_task(instruction)

                self.send_json(
                    200,
                    result,
                )

            except Exception as error:
                self.handle_error(error)

            return

        approval_route = path.split("/")

        if (
            len(approval_route) == 3
            and approval_route[1] == "approve"
            and approval_route[2]
        ):
            approval_id = approval_route[2]

            try:
                service = self._service()
                result = service.approve(approval_id)

                self.send_json(
                    200,
                    result,
                )

            except Exception as error:
                self.handle_error(error)

            return

        reject_route = path.split("/")

        if (
            len(reject_route) == 3
            and reject_route[1] == "reject"
            and reject_route[2]
        ):
            approval_id = reject_route[2]

            try:
                service = self._service()
                result = service.reject(approval_id)

                self.send_json(
                    200,
                    result,
                )

            except Exception as error:
                self.handle_error(error)

            return

        self.send_json(
            404,
            {
                "error": "Endpoint não encontrado",
            },
        )

    def do_PUT(self):
        self.send_json(
            405,
            {
                "error": "Método não permitido",
            },
        )

    def do_PATCH(self):
        self.send_json(
            405,
            {
                "error": "Método não permitido",
            },
        )

    def do_DELETE(self):
        self.send_json(
            405,
            {
                "error": "Método não permitido",
            },
        )

    def log_message(self, format, *args):
        super().log_message(format, *args)


def run():
    server = HTTPServer(
        ("127.0.0.1", 8765),
        APIHandler,
    )

    print(
        "DevAgent API em "
        "http://127.0.0.1:8765"
    )

    try:
        server.serve_forever()

    except KeyboardInterrupt:
        print("\nServidor encerrado.")

    finally:
        server.server_close()


if __name__ == "__main__":
    run()
