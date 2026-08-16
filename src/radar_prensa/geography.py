from __future__ import annotations

from typing import Any
from .utils import norm_text, slug

REGION_ALIASES = {
    "arica y parinacota": "Arica y Parinacota", "tarapaca": "Tarapacá",
    "antofagasta": "Antofagasta", "atacama": "Atacama", "coquimbo": "Coquimbo",
    "valparaiso": "Valparaíso", "metropolitana": "Metropolitana de Santiago",
    "region metropolitana": "Metropolitana de Santiago", "ohiggins": "Libertador General Bernardo O'Higgins",
    "maule": "Maule", "nuble": "Ñuble", "biobio": "Biobío", "araucania": "La Araucanía",
    "la araucania": "La Araucanía", "los rios": "Los Ríos", "los lagos": "Los Lagos",
    "aysen": "Aysén", "magallanes": "Magallanes y de la Antártica Chilena",
}

KNOWN_PLACES = {
    "arica": ("COMUNA", "Arica"), "iquique": ("COMUNA", "Iquique"),
    "alto hospicio": ("COMUNA", "Alto Hospicio"), "colchane": ("COMUNA", "Colchane"),
    "antofagasta": ("COMUNA", "Antofagasta"), "calama": ("COMUNA", "Calama"),
    "ollague": ("COMUNA", "Ollagüe"), "copiapo": ("COMUNA", "Copiapó"),
    "la serena": ("COMUNA", "La Serena"), "coquimbo": ("COMUNA", "Coquimbo"),
    "valparaiso": ("COMUNA", "Valparaíso"), "vina del mar": ("COMUNA", "Viña del Mar"),
    "santiago": ("COMUNA", "Santiago"), "providencia": ("COMUNA", "Providencia"),
    "las condes": ("COMUNA", "Las Condes"), "rancagua": ("COMUNA", "Rancagua"),
    "talca": ("COMUNA", "Talca"), "chillan": ("COMUNA", "Chillán"),
    "concepcion": ("COMUNA", "Concepción"), "temuco": ("COMUNA", "Temuco"),
    "valdivia": ("COMUNA", "Valdivia"), "puerto montt": ("COMUNA", "Puerto Montt"),
    "coyhaique": ("COMUNA", "Coyhaique"), "punta arenas": ("COMUNA", "Punta Arenas"),
}


def _flatten_locations(record: dict[str, Any]) -> list[Any]:
    found: list[Any] = []
    for key in ("lugares", "locations", "territorios", "location", "lugar", "comuna", "region"):
        value = record.get(key)
        if isinstance(value, list):
            found.extend(value)
        elif value:
            found.append(value)
    return found


def _row(name: str, level: str, region: str | None = None, lat: Any = None, lon: Any = None, confidence: Any = None, origin: str = "rule") -> dict[str, Any]:
    return {
        "territory_id": f"territory:cl:{level.casefold()}:{slug(name)}",
        "name": name,
        "country": "CL",
        "administrative_level": level,
        "region": region,
        "lat": lat,
        "lon": lon,
        "identity_method": "UPSTREAM_OR_RULE_MATCH",
        "confidence": confidence,
        "origin": origin,
    }


def extract_territories(record: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in _flatten_locations(record):
        if isinstance(item, dict):
            name = item.get("nombre") or item.get("name") or item.get("label") or item.get("comuna") or item.get("region")
            level = str(item.get("nivel") or item.get("level") or "UNKNOWN").upper()
            region = item.get("region")
            lat, lon = item.get("lat"), item.get("lon")
            confidence = item.get("confianza") or item.get("confidence")
            if level in {"MENCION", "UNKNOWN"} and lat is None and lon is None and not region:
                continue
        else:
            name = str(item)
            level, region, lat, lon, confidence = "UNKNOWN", None, None, None, None
        if not name:
            continue
        normalized = norm_text(name)
        canonical_region = REGION_ALIASES.get(normalized)
        if canonical_region and level in {"UNKNOWN", "REGION"}:
            name, level = canonical_region, "REGION"
        row = _row(name, level, region, lat, lon, confidence, "monitor_upstream")
        if row["territory_id"] not in seen:
            rows.append(row)
            seen.add(row["territory_id"])

    if not rows:
        text = norm_text(" ".join(str(record.get(k) or "") for k in ("titulo", "title", "resumen", "tema")))
        padded = f" {text} "
        for needle, (level, canonical) in KNOWN_PLACES.items():
            if f" {needle} " in padded:
                row = _row(canonical, level, None, None, None, "media", "text_fallback_v0.1")
                if row["territory_id"] not in seen:
                    rows.append(row)
                    seen.add(row["territory_id"])
    return rows
