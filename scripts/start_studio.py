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

    server = None
    worker = None
    failures = []
    reason = "startup_failure"
    try:
        server = HTTPServer(("127.0.0.1", 0), api.APIHandler)
        url = f"http://127.0.0.1:{server.server_port}"

        def serve():
            try:
                server.serve_forever()
            except BaseException as error:
                failures.append(error)

        worker = threading.Thread(target=serve, daemon=False)
        worker.start()
        reason = "loop_failure"
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
        if failures:
            raise failures[0]
        reason = "loop_returned"
    except KeyboardInterrupt:
        reason = "keyboard_interrupt"
        print("\nEncerrando Studio...", flush=True)
    except BaseException as error:
        print(
            f"DevAgent Studio: {reason}; type={type(error).__name__}",
            file=sys.stderr,
            flush=True,
        )
        raise
    finally:
        try:
            if worker is not None and worker.ident is not None:
                # Wait for an active request before closing the listening socket.
                if worker.is_alive():
                    server.shutdown()
                worker.join()
            if server is not None:
                server.server_close()
        finally:
            print(
                f"DevAgent Studio: stopped; reason={reason}",
                file=sys.stderr,
                flush=True,
            )


if __name__ == "__main__":
    main()
