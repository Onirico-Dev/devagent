from http.server import BaseHTTPRequestHandler, HTTPServer
import json

from agent import DevAgent
from core.gateway import (
    CommitTransactionError,
    DevAgentGateway,
)


agent = DevAgent(".")
gateway = DevAgentGateway(agent, ".")


class APIHandler(BaseHTTPRequestHandler):

    def send_json(self, status, data):
        body = json.dumps(
            data,
            ensure_ascii=False
        ).encode("utf-8")

        self.send_response(status)

        self.send_header(
            "Content-Type",
            "application/json; charset=utf-8"
        )

        self.send_header(
            "Content-Length",
            str(len(body))
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
                    "error": str(error).strip("'")
                }
            )
            return

        if isinstance(error, ValueError):
            self.send_json(
                409,
                {
                    "error": str(error)
                }
            )
            return

        self.send_json(
            500,
            {
                "error": str(error)
            }
        )

    def do_GET(self):
        if self.path == "/health":
            self.send_json(
                200,
                {
                    "status": "ok",
                    "service": "devagent"
                }
            )
            return

        if self.path == "/tasks":
            self.send_json(
                200,
                {
                    "tasks": gateway.list_tasks()
                }
            )
            return

        if self.path == "/tasks/latest":
            task = gateway.latest_task()

            if task is None:
                self.send_json(
                    404,
                    {
                        "error": "Nenhuma tarefa encontrada"
                    }
                )
                return

            self.send_json(200, task)
            return

        task_route = self.path.split("/")

        if (
            len(task_route) == 3
            and task_route[1] == "tasks"
            and task_route[2]
        ):
            task_id = task_route[2]
            task = gateway.get_task(task_id)

            if task is None:
                self.send_json(
                    404,
                    {
                        "error": "Tarefa não encontrada"
                    }
                )
                return

            self.send_json(200, task)
            return

        self.send_json(
            404,
            {
                "error": "Endpoint não encontrado"
            }
        )

    def do_POST(self):
        if self.path == "/plan":
            try:
                length = int(
                    self.headers.get(
                        "Content-Length",
                        0
                    )
                )

                raw = self.rfile.read(length)

                try:
                    data = json.loads(raw)
                except (json.JSONDecodeError, UnicodeDecodeError):
                    self.send_json(
                        400,
                        {
                            "error": "JSON inválido"
                        }
                    )
                    return

                if not isinstance(data, dict):
                    self.send_json(
                        400,
                        {
                            "error": (
                                "O corpo da requisição deve ser "
                                "um objeto JSON"
                            )
                        }
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
                            )
                        }
                    )
                    return

                gateway.agent = agent
                result = gateway.create_task(instruction)

                self.send_json(
                    200,
                    result
                )

            except Exception as error:
                self.handle_error(error)

            return

        approval_route = self.path.split("/")

        if (
            len(approval_route) == 3
            and approval_route[1] == "approve"
            and approval_route[2]
        ):
            approval_id = approval_route[2]

            try:
                result = gateway.approve(approval_id)

                self.send_json(
                    200,
                    result
                )

            except Exception as error:
                self.handle_error(error)

            return

        reject_route = self.path.split("/")

        if (
            len(reject_route) == 3
            and reject_route[1] == "reject"
            and reject_route[2]
        ):
            approval_id = reject_route[2]

            try:
                result = gateway.reject(approval_id)

                self.send_json(
                    200,
                    result
                )

            except Exception as error:
                self.handle_error(error)

            return

        self.send_json(
            404,
            {
                "error": "Endpoint não encontrado"
            }
        )

    def do_PUT(self):
        self.send_json(
            405,
            {
                "error": "Método não permitido"
            }
        )

    def do_PATCH(self):
        self.send_json(
            405,
            {
                "error": "Método não permitido"
            }
        )

    def do_DELETE(self):
        self.send_json(
            405,
            {
                "error": "Método não permitido"
            }
        )

    def log_message(self, format, *args):
        super().log_message(format, *args)


def run():
    server = HTTPServer(
        ("127.0.0.1", 8765),
        APIHandler
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
