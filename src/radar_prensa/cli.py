from __future__ import annotations

import argparse
import json
import os

from .importer import DEFAULT_MONITOR_URL
from .pipeline_v040 import run


def main() -> None:
    parser = argparse.ArgumentParser(description="Radar Prensa v0.4 · contexto longitudinal + identidad gobernada")
    parser.add_argument("--source", default=DEFAULT_MONITOR_URL, help="datos.json local o URL del Monitor")
    parser.add_argument("--output", default="data/exports")
    parser.add_argument(
        "--sii-entity-search",
        default=os.getenv("RADAR_PRENSA_SII_ENTITY_SEARCH"),
        help="Ruta opcional a entity_search.parquet de Radar SII Fusion.",
    )
    parser.add_argument(
        "--sii-reference-meta",
        default=os.getenv("RADAR_PRENSA_SII_REFERENCE_META"),
        help="JSON opcional con tag/digest del asset SII utilizado para resolver identidad.",
    )
    args = parser.parse_args()
    manifest = run(
        args.source,
        args.output,
        sii_entity_search=args.sii_entity_search,
        sii_reference_meta=args.sii_reference_meta,
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
