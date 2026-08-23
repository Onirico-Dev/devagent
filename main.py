#!/usr/bin/env python3

from pathlib import Path
import json


ROOT = Path(__file__).resolve().parent


def load_config():
    config_path = ROOT / "config" / "config.json"

    with config_path.open("r", encoding="utf-8") as file:
        return json.load(file)


def main():
    config = load_config()

    print("=" * 50)
    print(f"{config['name']} v{config['version']}")
    print("=" * 50)
    print("Sistema inicializado.")
    print(f"Diretório: {ROOT}")
    print(f"Modo: {config['mode']}")


if __name__ == "__main__":
    main()
