from __future__ import annotations

import calendar
import re
from datetime import date, datetime, timedelta, timezone
from typing import Any

from .utils import norm_text

_DATE_FIELDS = ("occurrence_date", "fecha_hecho", "fecha_evento", "event_date")
_PUBLICATION_FIELDS = ("fecha_iso", "published_at", "fecha_publicacion", "fecha", "date", "published")

_MONTHS = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6,
    "julio": 7, "agosto": 8, "septiembre": 9, "setiembre": 9, "octubre": 10,
    "noviembre": 11, "diciembre": 12,
}
_WEEKDAYS = {"lunes": 0, "martes": 1, "miercoles": 2, "jueves": 3, "viernes": 4, "sabado": 5, "domingo": 6}
_MONTH_PATTERN = "|".join(sorted(_MONTHS, key=len, reverse=True))
_WEEKDAY_PATTERN = "|".join(_WEEKDAYS)

_EVENT_CUE = re.compile(
    r"\b(?:investigacion|investigo|investiga|investigaba|comenzo|inicio|iniciaron|"
    r"hechos?|ocurrio|ocurrieron|operativo|allanamiento|incautacion|incauto|decomiso|"
    r"detencion|detenido|detuvieron|audiencia|formalizacion|formalizo|causa|delito|fraude|"
    r"contrabando|narcotrafico|lavado|corrupcion|sancion|sanciono|fiscalizacion|fiscalizo|"
    r"transferencia|pago|contrato|adjudicacion|querella|denuncia|condena|condenado|"
    r"se realizo|se efectuo|se registro|fue detenido|fueron detenidos)\b"
)
_PAST_CUE = re.compile(
    r"\b(?:ocurrio|ocurrieron|comenzo|inicio|iniciaron|se realizo|se efectuo|se registro|"
    r"fue|fueron|detenido|detuvieron|incauto|incautaron|decomiso|sanciono|formalizo)\b"
)

_EXACT_TEXT = re.compile(
    rf"\b(?P<day>[0-3]?\d)\s+de\s+(?P<month>{_MONTH_PATTERN})\s+(?:de|del)\s+(?P<year>20\d{{2}})\b",
    re.IGNORECASE,
)
_DMY_TEXT = re.compile(r"\b(?P<day>[0-3]?\d)[/-](?P<month>\d{1,2})[/-](?P<year>20\d{2})\b")
_YMD_TEXT = re.compile(r"\b(?P<year>20\d{2})-(?P<month>\d{2})-(?P<day>\d{2})\b")
_MONTH_YEAR = re.compile(
    rf"\b(?:en|durante|desde|a\s+partir\s+de)\s+(?P<month>{_MONTH_PATTERN})\s+(?:de\s+)?(?P<year>20\d{{2}})\b",
    re.IGNORECASE,
)
_SEMESTER = re.compile(r"\b(?P<which>primer|segundo)\s+semestre\s+(?:de\s+)?(?P<year>20\d{2})\b", re.IGNORECASE)
_YEAR_RANGE = re.compile(r"\b(?:entre|desde)\s+(?P<y1>20\d{2})\s+(?:y|hasta|a)\s+(?P<y2>20\d{2})\b", re.IGNORECASE)
_SINGLE_YEAR = re.compile(r"\b(?:durante|en|desde|a\s+partir\s+de)\s+(?P<year>20\d{2})\b", re.IGNORECASE)
_RELATIVE_DAY = re.compile(r"\b(?P<rel>anteayer|ayer)\b", re.IGNORECASE)
_WEEKDAY = re.compile(rf"\b(?P<prefix>el|este|pasado)\s+(?P<weekday>{_WEEKDAY_PATTERN})\b", re.IGNORECASE)


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


def _article_text(record: dict[str, Any]) -> str:
    parts: list[str] = []
    for key in (
        "titulo", "title", "resumen", "summary", "tema", "bajada", "descripcion",
        "texto_enriquecido", "texto", "contenido", "content", "evidencia_uaf",
    ):
        value = record.get(key)
        if value:
            parts.append(str(value))
    return "\n".join(dict.fromkeys(parts))


def _near_event_cue(text: str, start: int, end: int, radius: int = 150, require_past: bool = False) -> bool:
    window = norm_text(text[max(0, start - radius): min(len(text), end + 80)])
    return bool((_PAST_CUE if require_past else _EVENT_CUE).search(window))


def _excerpt(text: str, start: int, end: int, radius: int = 110) -> str:
    return " ".join(text[max(0, start - radius): min(len(text), end + radius)].split())[:500]


def _safe_date(year: int, month: int, day: int) -> date | None:
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _candidate(rule: str, precision: str, start_date: date, end_date: date, confidence: float, text: str, start: int, end: int, anchor: date | None = None) -> dict[str, Any]:
    return {
        "occurrence_date_from": start_date.isoformat(),
        "occurrence_date_to": end_date.isoformat(),
        "occurrence_date_anchor": (anchor or (start_date if start_date == end_date else None)).isoformat() if (anchor or start_date == end_date) else None,
        "occurrence_date_precision": precision,
        "occurrence_date_basis": "ARTICLE_TEXT",
        "occurrence_date_rule": rule,
        "occurrence_date_confidence": confidence,
        "occurrence_date_evidence": _excerpt(text, start, end),
    }


def _article_candidates(text: str, publication_day: date | None) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []

    for regex, rule in ((_EXACT_TEXT, "EXACT_SPANISH_DATE"), (_DMY_TEXT, "EXACT_NUMERIC_DMY"), (_YMD_TEXT, "EXACT_NUMERIC_YMD")):
        for match in regex.finditer(text):
            if not _near_event_cue(text, *match.span()):
                continue
            month = _MONTHS[norm_text(match.group("month"))] if rule == "EXACT_SPANISH_DATE" else int(match.group("month"))
            d = _safe_date(int(match.group("year")), month, int(match.group("day")))
            if d:
                candidates.append(_candidate(rule, "EXACT", d, d, 0.92, text, *match.span(), anchor=d))

    for match in _MONTH_YEAR.finditer(text):
        if not _near_event_cue(text, *match.span()):
            continue
        year = int(match.group("year"))
        month = _MONTHS[norm_text(match.group("month"))]
        start = date(year, month, 1)
        end = date(year, month, calendar.monthrange(year, month)[1])
        candidates.append(_candidate("MONTH_YEAR_WITH_EVENT_CUE", "MONTH", start, end, 0.84, text, *match.span()))

    for match in _SEMESTER.finditer(text):
        if not _near_event_cue(text, *match.span()):
            continue
        year = int(match.group("year"))
        if norm_text(match.group("which")) == "primer":
            start, end = date(year, 1, 1), date(year, 6, 30)
        else:
            start, end = date(year, 7, 1), date(year, 12, 31)
        candidates.append(_candidate("SEMESTER_WITH_EVENT_CUE", "HALF_YEAR", start, end, 0.79, text, *match.span()))

    for match in _YEAR_RANGE.finditer(text):
        if not _near_event_cue(text, *match.span()):
            continue
        y1, y2 = int(match.group("y1")), int(match.group("y2"))
        if y1 <= y2 and y2 - y1 <= 10:
            candidates.append(_candidate("YEAR_RANGE_WITH_EVENT_CUE", "YEAR_RANGE", date(y1, 1, 1), date(y2, 12, 31), 0.76, text, *match.span()))

    for match in _SINGLE_YEAR.finditer(text):
        if not _near_event_cue(text, *match.span()):
            continue
        year = int(match.group("year"))
        candidates.append(_candidate("YEAR_WITH_EVENT_CUE", "YEAR", date(year, 1, 1), date(year, 12, 31), 0.70, text, *match.span()))

    if publication_day:
        for match in _RELATIVE_DAY.finditer(text):
            if not _near_event_cue(text, *match.span(), radius=90, require_past=True):
                continue
            delta = 2 if norm_text(match.group("rel")) == "anteayer" else 1
            d = publication_day - timedelta(days=delta)
            candidates.append(_candidate("RELATIVE_DAY_FROM_PUBLICATION", "INFERRED_DAY", d, d, 0.72, text, *match.span(), anchor=d))

        for match in _WEEKDAY.finditer(text):
            if not _near_event_cue(text, *match.span(), radius=100, require_past=True):
                continue
            weekday = _WEEKDAYS[norm_text(match.group("weekday"))]
            delta = (publication_day.weekday() - weekday) % 7
            if norm_text(match.group("prefix")) == "pasado" and delta == 0:
                delta = 7
            d = publication_day - timedelta(days=delta)
            candidates.append(_candidate("WEEKDAY_FROM_PUBLICATION", "INFERRED_DAY", d, d, 0.64, text, *match.span(), anchor=d))

    if publication_day:
        candidates = [c for c in candidates if date.fromisoformat(c["occurrence_date_from"]) <= publication_day]

    precision_rank = {"EXACT": 6, "INFERRED_DAY": 5, "MONTH": 4, "HALF_YEAR": 3, "YEAR_RANGE": 2, "YEAR": 1}
    candidates.sort(key=lambda c: (c["occurrence_date_confidence"], precision_rank.get(c["occurrence_date_precision"], 0)), reverse=True)
    return candidates


def event_temporal(record: dict[str, Any], article_text: str | None = None) -> dict[str, Any]:
    pub = publication_time(record)
    publication_day = date.fromisoformat(pub[:10]) if pub else None

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
                "occurrence_date_rule": "UPSTREAM_EXPLICIT_FIELD",
                "occurrence_date_confidence": 0.95,
                "occurrence_date_evidence": str(record.get(key)),
                "publication_date": pub[:10] if pub else None,
            }

    text = article_text if article_text is not None else _article_text(record)
    candidates = _article_candidates(text, publication_day)
    if candidates:
        best = dict(candidates[0])
        best["publication_date"] = publication_day.isoformat() if publication_day else None
        best["temporal_candidates_count"] = len(candidates)
        return best

    return {
        "occurrence_date_from": None,
        "occurrence_date_to": None,
        "occurrence_date_anchor": None,
        "occurrence_date_precision": "UNKNOWN",
        "occurrence_date_basis": "NO_EXPLICIT_OCCURRENCE_DATE",
        "occurrence_date_rule": None,
        "occurrence_date_confidence": 0.0,
        "occurrence_date_evidence": None,
        "publication_date": publication_day.isoformat() if publication_day else None,
        "temporal_candidates_count": 0,
    }
