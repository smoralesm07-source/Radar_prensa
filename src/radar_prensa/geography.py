from __future__ import annotations

import re
from typing import Any

from .geo_catalog import (
    AMBIGUOUS_COMMUNES,
    COMUNAS_POR_REGION,
    PROVINCIAS_POR_REGION,
    REGION_ALIASES,
    REGIONES,
    catalog_counts,
)
from .utils import norm_text, slug

_COMMUNE_INDEX: dict[str, tuple[str, str]] = {}
for _region, _communes in COMUNAS_POR_REGION.items():
    for _name in _communes:
        _COMMUNE_INDEX[norm_text(_name)] = (_name, _region)

_PROVINCE_INDEX: dict[str, tuple[str, str]] = {}
for _region, _provinces in PROVINCIAS_POR_REGION.items():
    for _name in _provinces:
        _PROVINCE_INDEX[norm_text(_name)] = (_name, _region)

_REGION_INDEX: dict[str, str] = {norm_text(r): r for r in REGIONES}
_REGION_INDEX.update(REGION_ALIASES)

_AMBIGUOUS = {norm_text(x) for x in AMBIGUOUS_COMMUNES}
_LEVEL_CUE = {
    "COMUNA": re.compile(r"(?:comuna|municipalidad|municipio|ciudad)\s+(?:de\s+|del\s+|la\s+|el\s+)?$"),
    "PROVINCIA": re.compile(r"(?:provincia)\s+(?:de\s+|del\s+|la\s+|el\s+)?$"),
    "REGION": re.compile(r"(?:region|gobierno\s+regional)\s+(?:de\s+|del\s+|la\s+|el\s+)?$"),
}
_PLACE_CUE = re.compile(
    r"(?:\ben|\bdesde|\bhacia|\bhasta|\bcerca\s+de|\ben\s+la\s+comuna\s+de|"
    r"\ben\s+la\s+provincia\s+de|\ben\s+la\s+region\s+de|\bmunicipalidad\s+de|"
    r"\bfiscalia\s+de|\btribunal\s+de|\bpuerto\s+de|\bpaso\s+fronterizo\s+de)\s*$"
)
_PERSONAL_CUE = re.compile(r"(?:don|dona|sr|sra|senor|senora|dr|dra)\s+$")
_VALID_LEVELS = {"COMUNA", "PROVINCIA", "REGION", "LOCALIDAD", "CIUDAD", "EXTRANJERO"}


def _flatten_locations(record: dict[str, Any]) -> list[Any]:
    found: list[Any] = []
    for key in ("lugares", "locations", "territorios", "location", "lugar", "comuna", "provincia", "region"):
        value = record.get(key)
        if isinstance(value, list):
            found.extend(value)
        elif value:
            found.append(value)
    return found


def _row(
    name: str,
    level: str,
    region: str | None = None,
    lat: Any = None,
    lon: Any = None,
    confidence: Any = None,
    origin: str = "rule",
    matched_text: str | None = None,
    match_rule: str | None = None,
) -> dict[str, Any]:
    level = str(level or "UNKNOWN").upper()
    row = {
        "territory_id": f"territory:cl:{level.casefold()}:{slug(name)}",
        "name": name,
        "country": "CL",
        "administrative_level": level,
        "region": region,
        "lat": lat,
        "lon": lon,
        "identity_method": "UPSTREAM_OR_CATALOG_MATCH",
        "confidence": confidence,
        "origin": origin,
        "matched_text": matched_text,
        "match_rule": match_rule,
    }
    if region and level != "REGION":
        row["parent_region_id"] = f"territory:cl:region:{slug(region)}"
    return row


def _resolve_catalog(name: str, preferred_level: str | None = None) -> tuple[str, str, str | None] | None:
    key = norm_text(name)
    preferred_level = (preferred_level or "").upper()
    if preferred_level == "REGION" and key in _REGION_INDEX:
        return _REGION_INDEX[key], "REGION", _REGION_INDEX[key]
    if preferred_level == "PROVINCIA" and key in _PROVINCE_INDEX:
        canonical, region = _PROVINCE_INDEX[key]
        return canonical, "PROVINCIA", region
    if preferred_level == "COMUNA" and key in _COMMUNE_INDEX:
        canonical, region = _COMMUNE_INDEX[key]
        return canonical, "COMUNA", region
    if key in _COMMUNE_INDEX:
        canonical, region = _COMMUNE_INDEX[key]
        return canonical, "COMUNA", region
    if key in _PROVINCE_INDEX:
        canonical, region = _PROVINCE_INDEX[key]
        return canonical, "PROVINCIA", region
    if key in _REGION_INDEX:
        canonical = _REGION_INDEX[key]
        return canonical, "REGION", canonical
    return None


def _text_for_matching(record: dict[str, Any]) -> str:
    parts = []
    for key in (
        "titulo", "title", "resumen", "summary", "tema", "bajada", "descripcion",
        "texto_enriquecido", "texto", "contenido", "content", "evidencia_uaf",
    ):
        value = record.get(key)
        if value:
            parts.append(str(value))
    return " ".join(dict.fromkeys(parts))


def _find_catalog_mentions(record: dict[str, Any]) -> list[dict[str, Any]]:
    normalized = norm_text(_text_for_matching(record))
    if not normalized:
        return []
    padded = f" {normalized} "
    found: list[dict[str, Any]] = []
    consumed: list[tuple[int, int]] = []

    candidates: list[tuple[str, str, str, str | None]] = []
    for key, (canonical, region) in _COMMUNE_INDEX.items():
        candidates.append((key, canonical, "COMUNA", region))
    for key, (canonical, region) in _PROVINCE_INDEX.items():
        candidates.append((key, canonical, "PROVINCIA", region))
    for key, canonical in _REGION_INDEX.items():
        candidates.append((key, canonical, "REGION", canonical))
    candidates.sort(key=lambda x: (-len(x[0]), {"COMUNA": 0, "PROVINCIA": 1, "REGION": 2}[x[2]]))

    seen_semantic: set[tuple[str, str]] = set()
    for needle, canonical, level, region in candidates:
        pattern = re.compile(rf"(?<![a-z0-9]){re.escape(needle)}(?![a-z0-9])")
        for match in pattern.finditer(padded):
            start, end = match.span()
            if any(start >= a and end <= b for a, b in consumed):
                continue
            left = padded[max(0, start - 90):start]
            explicit_level = bool(_LEVEL_CUE[level].search(left))
            place_cue = explicit_level or bool(_PLACE_CUE.search(left))
            if level == "COMUNA" and needle in _AMBIGUOUS and not place_cue:
                continue
            if level == "COMUNA" and _PERSONAL_CUE.search(left) and not place_cue:
                continue

            competing = []
            for lvl, index in (("COMUNA", _COMMUNE_INDEX), ("PROVINCIA", _PROVINCE_INDEX), ("REGION", _REGION_INDEX)):
                if needle in index and lvl != level:
                    competing.append(lvl)
            if competing and not explicit_level:
                if level != "COMUNA":
                    continue
                if needle in _AMBIGUOUS and not place_cue:
                    continue

            confidence = 0.96 if explicit_level else (0.90 if place_cue else 0.76)
            key = (level, canonical)
            if key in seen_semantic:
                continue
            found.append(
                _row(
                    canonical,
                    level,
                    region if level != "REGION" else canonical,
                    confidence=confidence,
                    origin="text_catalog_v0.2",
                    matched_text=canonical,
                    match_rule="EXPLICIT_GEO_CUE" if explicit_level else ("PLACE_PREPOSITION" if place_cue else "CATALOG_EXACT"),
                )
            )
            seen_semantic.add(key)
            consumed.append((start, end))
            break
    return found


def extract_territories(record: dict[str, Any]) -> list[dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}

    def add(row: dict[str, Any]) -> None:
        current = rows.get(row["territory_id"])
        if current is None:
            rows[row["territory_id"]] = row
            return
        rank = {"monitor_upstream": 3, "monitor_upstream_catalog": 3, "text_catalog_v0.2": 2, "derived_hierarchy": 1}
        if rank.get(row.get("origin"), 0) > rank.get(current.get("origin"), 0):
            rows[row["territory_id"]] = row

    for item in _flatten_locations(record):
        if isinstance(item, dict):
            name = item.get("nombre") or item.get("name") or item.get("label") or item.get("comuna") or item.get("provincia") or item.get("region")
            raw_level = str(item.get("nivel") or item.get("level") or "UNKNOWN").upper()
            region = item.get("region")
            lat, lon = item.get("lat"), item.get("lon")
            confidence = item.get("confianza") or item.get("confidence")
            if not name:
                continue
            preferred = raw_level if raw_level in {"COMUNA", "PROVINCIA", "REGION"} else None
            resolved = _resolve_catalog(str(name), preferred)
            if resolved:
                canonical, level, catalog_region = resolved
                add(_row(canonical, level, catalog_region if level != "REGION" else canonical, lat, lon, confidence, "monitor_upstream_catalog", str(name), "UPSTREAM_CATALOG"))
            elif raw_level in _VALID_LEVELS or lat is not None or lon is not None or region:
                add(_row(str(name), raw_level, region, lat, lon, confidence, "monitor_upstream", str(name), "UPSTREAM"))
        else:
            name = str(item)
            resolved = _resolve_catalog(name)
            if resolved:
                canonical, level, region = resolved
                add(_row(canonical, level, region if level != "REGION" else canonical, confidence=0.82, origin="monitor_upstream_catalog", matched_text=name, match_rule="UPSTREAM_CATALOG"))

    for row in _find_catalog_mentions(record):
        add(row)

    direct = list(rows.values())
    for row in direct:
        region = row.get("region")
        if region and row.get("administrative_level") in {"COMUNA", "PROVINCIA"}:
            add(_row(region, "REGION", region, confidence=1.0, origin="derived_hierarchy", matched_text=row["name"], match_rule="PARENT_REGION"))

    return sorted(rows.values(), key=lambda x: (x["administrative_level"], x["name"]))


def geography_catalog_stats() -> dict[str, int]:
    return catalog_counts()
