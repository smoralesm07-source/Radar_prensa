from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .utils import canonical_url, norm_text

DEFAULT_MONITOR_URL = "https://raw.githubusercontent.com/smoralesm07-source/Monitor/monitor-state/datos.json"


def load_monitor(source: str | Path) -> dict[str, Any]:
    source = str(source)
    if source.startswith(("http://", "https://")):
        req = Request(source, headers={"User-Agent": "RadarPrensa/0.4.1 (+OSINT research)"})
        last_error: Exception | None = None
        for attempt in range(1, 4):
            try:
                with urlopen(req, timeout=60) as response:
                    return json.loads(response.read().decode("utf-8"))
            except HTTPError as exc:
                # Errores permanentes del origen no se ocultan con reintentos.
                if 400 <= exc.code < 500 and exc.code != 429:
                    raise
                last_error = exc
            except (TimeoutError, URLError, OSError) as exc:
                last_error = exc
            if attempt < 3:
                time.sleep(2 ** (attempt - 1))
        raise RuntimeError(f"MONITOR_DOWNLOAD_FAILED_AFTER_RETRIES:{source}") from last_error
    return json.loads(Path(source).read_text(encoding="utf-8"))


def _looks_like_record(item: Any) -> bool:
    if not isinstance(item, dict):
        return False
    has_url = bool(item.get("link") or item.get("url") or item.get("source_url"))
    has_title = bool(item.get("titulo") or item.get("title") or item.get("tema"))
    return has_url and has_title


def _first(item: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = item.get(key)
        if value not in (None, "", []):
            return str(value).strip()
    return ""


def _soft_record_key(item: dict[str, Any]) -> tuple[str, str, str, str]:
    """Clave secundaria para aliases del mismo artículo.

    No se usa para construir IDs canónicos. Sólo colapsa registros cuando URL
    normalizada, medio, título y fecha coinciden. Esto cubre aliases como paths
    con mayúsculas/minúsculas sin asumir globalmente que toda URL web es
    case-insensitive.
    """
    url = canonical_url(_first(item, "link", "url", "source_url"))
    source = _first(item, "medio", "source", "fuente")
    title = _first(item, "titulo", "title", "tema")
    published = _first(item, "fecha_iso", "fecha", "published_at", "publication_date")[:10]
    return norm_text(url), norm_text(source), norm_text(title), published


def _dedupe_aliases(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str, str]] = set()
    for item in candidates:
        key = _soft_record_key(item)
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


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
    return _dedupe_aliases(candidates)
