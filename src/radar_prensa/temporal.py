from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

_DATE_FIELDS = ("occurrence_date", "fecha_hecho", "fecha_evento", "event_date")
_PUBLICATION_FIELDS = ("fecha_iso", "published_at", "fecha_publicacion", "fecha", "date", "published")


def _parse_date(value: Any) -> str | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    for candidate in (raw, raw.replace("Z", "+00:00")):
        try:
            dt = datetime.fromisoformat(candidate)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.isoformat().replace("+00:00", "Z")
        except Exception:
            pass
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y"):
        try:
            dt = datetime.strptime(raw[:10], fmt).replace(tzinfo=timezone.utc)
            return dt.isoformat().replace("+00:00", "Z")
        except Exception:
            pass
    return None


def publication_time(record: dict[str, Any]) -> str | None:
    for key in _PUBLICATION_FIELDS:
        parsed = _parse_date(record.get(key))
        if parsed:
            return parsed
    return None


def event_temporal(record: dict[str, Any]) -> dict[str, Any]:
    for key in _DATE_FIELDS:
        parsed = _parse_date(record.get(key))
        if parsed:
            day = parsed[:10]
            return {
                "occurrence_date_from": day,
                "occurrence_date_to": day,
                "occurrence_date_anchor": day,
                "occurrence_date_precision": "EXACT",
                "occurrence_date_basis": f"SOURCE_FIELD:{key}",
                "occurrence_date_confidence": 0.90,
                "publication_date": (publication_time(record) or "")[:10] or None,
            }
    pub = publication_time(record)
    return {
        "occurrence_date_from": None,
        "occurrence_date_to": None,
        "occurrence_date_anchor": None,
        "occurrence_date_precision": "UNKNOWN",
        "occurrence_date_basis": "NO_EXPLICIT_OCCURRENCE_DATE",
        "occurrence_date_confidence": 0.0,
        "publication_date": pub[:10] if pub else None,
    }
