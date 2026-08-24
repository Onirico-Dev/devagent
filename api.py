from http.server import BaseHTTPRequestHandler, HTTPServer
import json

from agent import DevAgent
from core.gateway import DevAgentGateway


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

        if self.path.startswith("/tasks/"):
            task_id = self.path.split("/")[-1]
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

                result = gateway.create_task(instruction)

                self.send_json(
                    200,
                    result
                )

            except Exception as error:
                self.handle_error(error)

            return

        if self.path.startswith("/approve/"):
            approval_id = self.path.split("/")[-1]

            try:
                result = gateway.approve(approval_id)

                self.send_json(
                    200,
                    result
                )

            except Exception as error:
                self.handle_error(error)

            return

        if self.path.startswith("/reject/"):
            approval_id = self.path.split("/")[-1]

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
