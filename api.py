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

        self.send_json(
            404,
            {
                "error": "Endpoint não encontrado"
            }
        )

    def do_POST(self):

        if self.path == "/plan":

            length = int(
                self.headers.get(
                    "Content-Length",
                    0
                )
            )

            raw = self.rfile.read(length)

            try:

                data = json.loads(raw)

                instruction = data["instruction"]

                result = gateway.create_task(
                    instruction
                )

                self.send_json(
                    200,
                    result
                )

            except Exception as error:

                self.send_json(
                    500,
                    {
                        "error": str(error)
                    }
                )

            return

        if self.path.startswith("/approve/"):

            approval_id = self.path.split(
                "/"
            )[-1]

            try:

                result = gateway.approve(
                    approval_id
                )

                self.send_json(
                    200,
                    result
                )

            except Exception as error:

                self.send_json(
                    500,
                    {
                        "error": str(error)
                    }
                )

            return

        if self.path.startswith("/reject/"):

            approval_id = self.path.split(
                "/"
            )[-1]

            try:

                result = gateway.reject(
                    approval_id
                )

                self.send_json(
                    200,
                    result
                )

            except Exception as error:

                self.send_json(
                    500,
                    {
                        "error": str(error)
                    }
                )

            return

        self.send_json(
            404,
            {
                "error": "Endpoint não encontrado"
            }
        )


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
