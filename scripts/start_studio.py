"""Start the local DevAgent Studio with the Codex adapter."""

import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys
import threading
from http.server import HTTPServer


def main():
    parser = argparse.ArgumentParser(description="DevAgent Studio com Codex")
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[1]
    os.chdir(root)
    sys.path.insert(0, str(root))
    os.environ["DEVAGENT_AI"] = "codex"

    import api
    from core.adapters.codex_adapter import CodexAdapter

    if not isinstance(api.agent.ai, CodexAdapter):
        raise SystemExit("Adaptador Codex não selecionado.")

    server = HTTPServer(("127.0.0.1", 0), api.APIHandler)
    url = f"http://127.0.0.1:{server.server_port}"
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        print("Adaptador: Codex", flush=True)
        print("Projeto:", root, flush=True)
        print("Studio:", url, flush=True)
        print("Mantenha esta sessão aberta. Ctrl+C encerra.", flush=True)
        opener = shutil.which("termux-open-url")
        if opener and not args.no_browser:
            try:
                subprocess.Popen([opener, url], stdout=subprocess.DEVNULL,
                                 stderr=subprocess.DEVNULL)
            except OSError:
                print("Abra o endereço acima manualmente.", flush=True)
        worker.join()
    except KeyboardInterrupt:
        print("\nEncerrando Studio...", flush=True)
    finally:
        server.shutdown()
        server.server_close()


if __name__ == "__main__":
    main()
