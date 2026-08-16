from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen

DEFAULT_MONITOR_URL = "https://raw.githubusercontent.com/smoralesm07-source/Monitor/monitor-state/datos.json"


def load_monitor(source: str | Path) -> dict[str, Any]:
    source = str(source)
    if source.startswith(("http://", "https://")):
        req = Request(source, headers={"User-Agent": "RadarPrensa/0.1 (+OSINT research)"})
        with urlopen(req, timeout=45) as response:
            return json.loads(response.read().decode("utf-8"))
    return json.loads(Path(source).read_text(encoding="utf-8"))


def _looks_like_record(item: Any) -> bool:
    if not isinstance(item, dict):
        return False
    has_url = bool(item.get("link") or item.get("url") or item.get("source_url"))
    has_title = bool(item.get("titulo") or item.get("title") or item.get("tema"))
    return has_url and has_title


def extract_records(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Extrae publicaciones tolerando cambios menores del esquema del Monitor."""
    candidates: list[dict[str, Any]] = []
    seen_ids: set[int] = set()
    for key in ("prensa", "contexto", "noticias", "publicaciones", "items"):
        value = payload.get(key)
        if isinstance(value, list):
            for item in value:
                if _looks_like_record(item):
                    candidates.append(item)
                    seen_ids.add(id(item))

    def walk(value: Any, depth: int = 0) -> None:
        if depth > 5:
            return
        if isinstance(value, dict):
            if _looks_like_record(value) and id(value) not in seen_ids:
                candidates.append(value)
                seen_ids.add(id(value))
                return
            for child in value.values():
                walk(child, depth + 1)
        elif isinstance(value, list):
            for child in value:
                walk(child, depth + 1)

    if not candidates:
        walk(payload)
    return candidates
