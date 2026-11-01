import json
import sys
from http.server import HTTPServer
from pathlib import Path

ROOT = Path(sys.argv[1]).resolve()
if not ROOT.is_dir():
    raise SystemExit(f"Diretório de projeto inexistente: {ROOT}")

# O processo é iniciado com cwd no projeto temporário.
# Assim, a inicialização global de api.py também fica isolada.
from core.adapters.mock import MockAdapter
from agent import DevAgent
from core.gateway import DevAgentGateway
import api

agent = DevAgent(str(ROOT), ai_adapter=MockAdapter())
gateway = DevAgentGateway(agent, str(ROOT))

api.agent = agent
api.gateway = gateway

server = HTTPServer(("127.0.0.1", 0), api.APIHandler)

try:
    print(json.dumps({"port": server.server_port}), flush=True)
    server.serve_forever()
finally:
    server.server_close()
