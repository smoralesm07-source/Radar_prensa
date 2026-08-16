from __future__ import annotations

import re
from typing import Any

from .identity_enrichment import canonical_rut, global_rut_entity_id, normalize_rut, valid_chilean_rut
from .utils import norm_text, stable_id

LEGAL_SUFFIX = re.compile(r"\b(spa|s\.a\.?|ltda\.?|eirl|e\.i\.r\.l\.?|fundacion|corporacion|asociacion|agf)\b", re.I)
RUT = re.compile(r"\b\d{1,2}(?:\.\d{3}){2}-[0-9kK]\b|\b\d{7,8}-[0-9kK]\b")


def _map_type(raw: Any, name: str, nature: Any = None) -> str:
    key = norm_text(f"{raw or ''} {nature or ''}")
    if "persona natural" in key or key.strip() == "persona":
        return "PERSON"
    if "public" in key or "organismo" in key or "municip" in key:
        return "PUBLIC_BODY"
    if "osfl" in key or "sin fines" in key or "fundacion" in key:
        return "OSFL"
    if "persona juridica" in key or "empresa" in key or "organizacion" in key or "institucion financiera" in key or LEGAL_SUFFIX.search(name or ""):
        return "LEGAL_ENTITY"
    return "UNKNOWN"


def _iter_upstream(record: dict[str, Any]):
    for key in ("nomina_entidades", "entidades", "entities", "personas", "organizaciones"):
        value = record.get(key)
        if isinstance(value, list):
            yield from value


def _validated_rut(value: Any) -> tuple[str | None, str | None]:
    normalized = normalize_rut(value)
    if not normalized:
        return None, None
    if valid_chilean_rut(normalized):
        return canonical_rut(normalized), None
    return None, normalized


def extract_entities(record: dict[str, Any], evidence_id: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in _iter_upstream(record):
        if isinstance(item, dict):
            name = item.get("nombre") or item.get("name") or item.get("texto") or item.get("canonical_name")
            raw_type = item.get("tipo") or item.get("type")
            nature = item.get("naturaleza")
            ruts = item.get("ruts") if isinstance(item.get("ruts"), list) else []
            raw_rut = item.get("rut") or item.get("rut_normalized") or (ruts[0] if ruts else None)
            rut, invalid_rut = _validated_rut(raw_rut)
            confidence = item.get("confianza_score") or item.get("score") or item.get("confidence") or 0.75
            upstream_id = item.get("entidad_id") or item.get("entity_id")
            roles = item.get("roles") if isinstance(item.get("roles"), list) else []
            if item.get("rol_principal") and item.get("rol_principal") not in roles:
                roles = [item.get("rol_principal"), *roles]
        else:
            name = str(item)
            raw_type = None
            nature = None
            rut = None
            invalid_rut = None
            confidence = 0.60
            upstream_id = None
            roles = []
        if not name:
            continue
        entity_type = _map_type(raw_type, name, nature)
        entity_id = global_rut_entity_id(rut) if rut else stable_id("entity:press", name)
        if entity_id in seen:
            continue
        seen.add(entity_id)
        attributes = {
            "origin": "monitor_upstream",
            "upstream_entity_id": upstream_id,
            "upstream_nature": nature,
            "requires_validation": bool(item.get("requiere_validacion")) if isinstance(item, dict) else False,
        }
        if rut:
            attributes["global_entity_key"] = entity_id
        if invalid_rut:
            attributes["invalid_rut_rejected"] = invalid_rut
            attributes["requires_validation"] = True
        out.append({
            "entity_id": entity_id,
            "entity_type": entity_type,
            "canonical_name": name,
            "rut_normalized": rut,
            "aliases": [],
            "roles": sorted(set(str(r) for r in (["PRESS_MENTION"] + roles) if r)),
            "producer_ids": ["radar_prensa"],
            "evidence_ids": [evidence_id],
            "identity_method": "RUT_EXACT" if rut else "SOURCE_NATIVE",
            "identity_confidence": 1.0 if rut else max(0.0, min(float(confidence), 1.0)),
            "attributes": attributes,
        })
    text = " ".join(str(record.get(k) or "") for k in ("titulo", "title", "tema", "resumen", "texto", "contenido"))
    for raw_rut in RUT.findall(text):
        rut, _ = _validated_rut(raw_rut)
        if not rut:
            continue
        entity_id = global_rut_entity_id(rut)
        if entity_id in seen:
            continue
        seen.add(entity_id)
        out.append({
            "entity_id": entity_id,
            "entity_type": "UNKNOWN",
            "canonical_name": None,
            "rut_normalized": rut,
            "aliases": [],
            "roles": ["PRESS_MENTION"],
            "producer_ids": ["radar_prensa"],
            "evidence_ids": [evidence_id],
            "identity_method": "RUT_EXACT",
            "identity_confidence": 1.0,
            "attributes": {
                "origin": "explicit_valid_rut_regex",
                "upstream_entity_id": None,
                "global_entity_key": entity_id,
            },
        })
    return out


def extract_explicit_relationships(record: dict[str, Any], local_entities: list[dict[str, Any]], evidence_id: str, event_id: str) -> list[dict[str, Any]]:
    """Conserva sólo relaciones que el Monitor marcó como explícitas en el texto."""
    by_upstream = {e.get("attributes", {}).get("upstream_entity_id"): e["entity_id"] for e in local_entities if e.get("attributes", {}).get("upstream_entity_id")}
    by_name = {norm_text(e.get("canonical_name")): e["entity_id"] for e in local_entities if e.get("canonical_name")}
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in record.get("nomina_entidades", []) if isinstance(record.get("nomina_entidades"), list) else []:
        if not isinstance(item, dict):
            continue
        source = by_upstream.get(item.get("entidad_id")) or by_name.get(norm_text(item.get("nombre")))
        if not source:
            continue
        for rel in item.get("relaciones_explicitas", []) if isinstance(item.get("relaciones_explicitas"), list) else []:
            if not isinstance(rel, dict):
                continue
            target = by_upstream.get(rel.get("contraparte_id")) or by_name.get(norm_text(rel.get("contraparte")))
            if not target or target == source:
                continue
            rel_type = str(rel.get("tipo") or "EXPLICIT_PRESS_RELATION").upper()
            relation_id = stable_id("relationship:press", event_id, source, rel_type, target)
            if relation_id in seen:
                continue
            seen.add(relation_id)
            out.append({
                "relationship_id": relation_id,
                "producer_id": "radar_prensa",
                "source_entity_id": source,
                "target_entity_id": target,
                "relationship_type": rel_type,
                "event_id": event_id,
                "evidence_ids": [evidence_id],
                "confidence": rel.get("confianza") or "UNKNOWN",
                "label": rel.get("etiqueta"),
                "semantics": "EXPLICIT_PRESS_RELATION_ONLY",
                "guardrail": "Relación reportada explícitamente en la publicación; no implica control, beneficio final, delito ni riesgo AML.",
            })
    return out
