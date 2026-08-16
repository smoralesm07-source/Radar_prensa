from __future__ import annotations

import argparse
import json
from .importer import DEFAULT_MONITOR_URL
from .pipeline import run


def main() -> None:
    parser = argparse.ArgumentParser(description="Radar Prensa v0.1")
    parser.add_argument("--source", default=DEFAULT_MONITOR_URL, help="datos.json local o URL del Monitor")
    parser.add_argument("--output", default="data/exports")
    args = parser.parse_args()
    manifest = run(args.source, args.output)
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
