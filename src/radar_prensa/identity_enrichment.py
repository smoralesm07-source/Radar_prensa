from __future__ import annotations

import json
import re
import unicodedata
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable

from .utils import stable_id

SII_RADAR_ID = "RADAR_SII"
METHOD = "SII_UNIQUE_NORMALIZED_LEGAL_NAME"
GUARDRAIL = "IDENTITY_ENRICHMENT_REQUIRES_UNIQUE_OFFICIAL_NAME_MATCH_AND_VALID_RUT"
ELIGIBLE_TYPES = {"LEGAL_ENTITY", "OSFL", "PUBLIC_BODY"}
_NAME_RE = re.compile(r"[^0-9A-ZÁÉÍÓÚÜÑ]+", re.UNICODE)


def normalize_legal_name(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).upper().strip()
    return _NAME_RE.sub(" ", text).strip()


def normalize_rut(value: Any) -> str | None:
    raw = re.sub(r"[^0-9Kk]", "", str(value or "")).upper()
    return raw or None


def valid_chilean_rut(value: Any) -> bool:
    rut = normalize_rut(value)
    if not rut or len(rut) < 7 or len(rut) > 9 or not rut[:-1].isdigit():
        return False
    body, observed = rut[:-1], rut[-1]
    total = 0
    factor = 2
    for digit in reversed(body):
        total += int(digit) * factor
        factor = 2 if factor == 7 else factor + 1
    result = 11 - (total % 11)
    expected = "0" if result == 11 else "K" if result == 10 else str(result)
    return observed == expected


def canonical_rut(value: Any) -> str:
    rut = normalize_rut(value)
    if not rut or not valid_chilean_rut(rut):
        raise ValueError("CANONICAL_RUT_REQUIRES_VALID_CHILEAN_RUT")
    return f"{rut[:-1]}-{rut[-1]}"


def global_rut_entity_id(value: Any) -> str:
    return f"ENT-RUT-{canonical_rut(value)}"


def _reference_index(rows: Iterable[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        name = normalize_legal_name(row.get("legal_name"))
        rut = normalize_rut(row.get("rut"))
        if not name or not valid_chilean_rut(rut):
            continue
        out[name].append({
            "rut": rut,
            "entity_id": row.get("entity_id"),
            "legal_name": row.get("legal_name"),
        })
    return out


def _load_sii_reference(path: Path, candidate_names: set[str]) -> dict[str, list[dict[str, Any]]]:
    if not candidate_names:
        return {}
    try:
        import duckdb  # type: ignore
    except Exception as exc:  # pragma: no cover
        raise RuntimeError("DUCKDB_REQUIRED_FOR_SII_IDENTITY_ENRICHMENT") from exc

    db = duckdb.connect()
    try:
        db.execute("CREATE TEMP TABLE press_identity_candidates(norm_name VARCHAR PRIMARY KEY)")
        db.executemany(
            "INSERT INTO press_identity_candidates VALUES (?)",
            [(name,) for name in sorted(candidate_names)],
        )
        parquet = str(path).replace("'", "''")
        sql = f"""
        SELECT c.norm_name, s.rut, s.entity_id, s.legal_name
        FROM press_identity_candidates c
        JOIN read_parquet('{parquet}') s
          ON regexp_replace(
               upper(trim(coalesce(cast(s.legal_name as varchar), ''))),
               '[^0-9A-ZÁÉÍÓÚÜÑ]+', ' ', 'g'
             ) = c.norm_name
        WHERE s.rut IS NOT NULL
        """
        rows = [
            {"norm_name": norm_name, "rut": rut, "entity_id": entity_id, "legal_name": legal_name}
            for norm_name, rut, entity_id, legal_name in db.execute(sql).fetchall()
        ]
    finally:
        db.close()

    return _reference_index(
        {"legal_name": row["legal_name"], "rut": row["rut"], "entity_id": row["entity_id"]}
        for row in rows
    )


def _read_reference_meta(path: Path | None) -> dict[str, Any]:
    if path is None or not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _resolution_id(before_id: str, rut: str | None, status: str) -> str:
    return stable_id("identity-resolution:press", before_id, rut or "NO_RUT", status)


def _dedupe_reference_matches(rows: list[dict[str, Any]]) -> tuple[str, dict[str, Any] | None, int]:
    by_rut: dict[str, dict[str, Any]] = {}
    for row in rows:
        rut = normalize_rut(row.get("rut"))
        if rut and valid_chilean_rut(rut):
            by_rut.setdefault(rut, row)
    if not by_rut:
        return "NO_MATCH", None, 0
    if len(by_rut) > 1:
        return "AMBIGUOUS", None, len(by_rut)
    return "RESOLVED", next(iter(by_rut.values())), 1


def _canonical_id_from_reference(match: dict[str, Any], rut: str) -> str:
    expected = global_rut_entity_id(rut)
    reference_id = str(match.get("entity_id") or "").strip()
    if not reference_id:
        return expected
    if reference_id != expected:
        raise ValueError(
            f"SII_REFERENCE_ENTITY_KEY_MISMATCH:{reference_id}:expected:{expected}"
        )
    return reference_id


def _apply_reference_index(
    bundle: dict[str, list[dict[str, Any]]],
    reference: dict[str, list[dict[str, Any]]],
    reference_meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    meta = reference_meta or {}
    entities = bundle.get("entities", [])
    resolutions: list[dict[str, Any]] = []
    remap: dict[str, str] = {}
    attempted = resolved = ambiguous = no_match = invalid_existing = 0

    for entity in entities:
        before_id = str(entity.get("entity_id") or "")
        existing_rut = normalize_rut(entity.get("rut_normalized"))
        if existing_rut:
            if valid_chilean_rut(existing_rut):
                canonical_id = global_rut_entity_id(existing_rut)
                remap[before_id] = canonical_id
                entity["entity_id"] = canonical_id
                entity["rut_normalized"] = canonical_rut(existing_rut)
                entity["identity_method"] = "RUT_EXACT"
                entity["identity_confidence"] = 1.0
                entity.setdefault("attributes", {})["global_entity_key"] = canonical_id
            else:
                invalid_existing += 1
                entity["rut_normalized"] = None
                entity["identity_method"] = "SOURCE_NATIVE"
                entity["identity_confidence"] = min(float(entity.get("identity_confidence") or 0.5), 0.5)
                entity.setdefault("attributes", {})["invalid_rut_rejected"] = existing_rut
            continue

        if str(entity.get("entity_type") or "") not in ELIGIBLE_TYPES:
            continue
        name = normalize_legal_name(entity.get("canonical_name"))
        if not name:
            continue
        attempted += 1
        status, match, cardinality = _dedupe_reference_matches(reference.get(name, []))
        if status == "RESOLVED" and match is not None:
            rut = normalize_rut(match.get("rut"))
            assert rut is not None
            canonical_id = _canonical_id_from_reference(match, rut)
            formatted_rut = canonical_rut(rut)
            entity["entity_id"] = canonical_id
            entity["rut_normalized"] = formatted_rut
            entity["identity_method"] = "RUT_EXACT"
            entity["identity_confidence"] = 1.0
            attrs = entity.setdefault("attributes", {})
            attrs["global_entity_key"] = canonical_id
            attrs["identity_resolution"] = {
                "method": METHOD,
                "reference_radar_id": SII_RADAR_ID,
                "reference_entity_id": match.get("entity_id"),
                "reference_legal_name": match.get("legal_name"),
                "reference_release_tag": meta.get("release_tag") or "fusion-v1",
                "reference_asset_digest": meta.get("asset_digest") or meta.get("digest"),
                "reference_dataset": "entity_search.parquet",
                "match_cardinality": 1,
                "global_entity_key": canonical_id,
                "guardrail": GUARDRAIL,
            }
            remap[before_id] = canonical_id
            resolved += 1
            resolution_rut = formatted_rut
        else:
            resolution_rut = None
            ambiguous += int(status == "AMBIGUOUS")
            no_match += int(status == "NO_MATCH")

        resolutions.append({
            "resolution_id": _resolution_id(before_id, resolution_rut, status),
            "producer_id": "radar_prensa",
            "press_entity_id_before": before_id,
            "press_entity_id_after": remap.get(before_id, before_id),
            "canonical_name": entity.get("canonical_name"),
            "normalized_name": name,
            "status": status,
            "rut_normalized": resolution_rut,
            "method": METHOD,
            "reference_radar_id": SII_RADAR_ID,
            "reference_release_tag": meta.get("release_tag") or "fusion-v1",
            "reference_asset_digest": meta.get("asset_digest") or meta.get("digest"),
            "reference_dataset": "entity_search.parquet",
            "match_cardinality": cardinality,
            "global_entity_key": remap.get(before_id) if status == "RESOLVED" else None,
            "guardrail": GUARDRAIL,
        })

    merged: dict[str, dict[str, Any]] = {}
    for entity in entities:
        eid = str(entity.get("entity_id") or "")
        if not eid:
            continue
        current = merged.get(eid)
        if current is None:
            entity["aliases"] = sorted({str(x) for x in entity.get("aliases", []) if x})
            merged[eid] = entity
            continue
        names = {str(x) for x in current.get("aliases", []) if x} | {str(x) for x in entity.get("aliases", []) if x}
        if current.get("canonical_name") and entity.get("canonical_name") and current["canonical_name"] != entity["canonical_name"]:
            names.add(str(entity["canonical_name"]))
        if not current.get("canonical_name") and entity.get("canonical_name"):
            current["canonical_name"] = entity["canonical_name"]
        current["aliases"] = sorted(names)
        current["evidence_ids"] = sorted(set(current.get("evidence_ids", [])) | set(entity.get("evidence_ids", [])))
        current["roles"] = sorted(set(current.get("roles", [])) | set(entity.get("roles", [])))
        current["producer_ids"] = sorted(set(current.get("producer_ids", [])) | set(entity.get("producer_ids", [])))
        current["identity_confidence"] = max(float(current.get("identity_confidence") or 0), float(entity.get("identity_confidence") or 0))
        if entity.get("identity_method") == "RUT_EXACT":
            current["identity_method"] = "RUT_EXACT"
            current["rut_normalized"] = entity.get("rut_normalized")
            if (entity.get("attributes") or {}).get("identity_resolution"):
                current.setdefault("attributes", {})["identity_resolution"] = entity["attributes"]["identity_resolution"]
                current["attributes"]["global_entity_key"] = eid

    bundle["entities"] = sorted(merged.values(), key=lambda row: str(row.get("entity_id") or ""))

    def mapped(entity_id: Any) -> str:
        raw = str(entity_id or "")
        return remap.get(raw, raw)

    mention_map: dict[tuple[str, str], dict[str, Any]] = {}
    for row in bundle.get("entity_mentions", []):
        row["entity_id"] = mapped(row.get("entity_id"))
        row["mention_id"] = stable_id("mention:press", row.get("document_id"), row["entity_id"])
        mention_map[(str(row.get("document_id")), row["entity_id"])] = row
    bundle["entity_mentions"] = sorted(mention_map.values(), key=lambda row: str(row.get("mention_id")))

    ee_map: dict[tuple[str, str, str], dict[str, Any]] = {}
    for row in bundle.get("event_entities", []):
        row["entity_id"] = mapped(row.get("entity_id"))
        ee_map[(str(row.get("event_id")), row["entity_id"], str(row.get("evidence_id")))] = row
    bundle["event_entities"] = sorted(ee_map.values(), key=lambda row: (str(row.get("event_id")), row["entity_id"]))

    for event in bundle.get("events", []):
        event["entity_ids"] = sorted({mapped(entity_id) for entity_id in event.get("entity_ids", []) if entity_id})

    relation_map: dict[str, dict[str, Any]] = {}
    for row in bundle.get("relationships", []):
        source = mapped(row.get("source_entity_id"))
        target = mapped(row.get("target_entity_id"))
        if not source or not target or source == target:
            continue
        row["source_entity_id"] = source
        row["target_entity_id"] = target
        row["relationship_id"] = stable_id(
            "relationship:press", row.get("event_id"), source, row.get("relationship_type"), target
        )
        relation_map[row["relationship_id"]] = row
    bundle["relationships"] = sorted(relation_map.values(), key=lambda row: str(row.get("relationship_id")))
    bundle["identity_resolutions"] = sorted(resolutions, key=lambda row: str(row.get("resolution_id")))

    return {
        "status": "ACTIVE",
        "method": METHOD,
        "reference_radar_id": SII_RADAR_ID,
        "reference_release_tag": meta.get("release_tag") or "fusion-v1",
        "reference_asset_digest": meta.get("asset_digest") or meta.get("digest"),
        "global_entity_key_policy": "ENT-RUT-{RUT_CANONICO_CON_GUION}",
        "attempted": attempted,
        "resolved": resolved,
        "ambiguous": ambiguous,
        "no_match": no_match,
        "invalid_existing_rut_rejected": invalid_existing,
        "rut_exact_entities_after": sum(1 for row in bundle["entities"] if row.get("identity_method") == "RUT_EXACT"),
        "guardrail": GUARDRAIL,
    }


def enrich_bundle_from_rows(
    bundle: dict[str, list[dict[str, Any]]],
    reference_rows: Iterable[dict[str, Any]],
    reference_meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return _apply_reference_index(bundle, _reference_index(reference_rows), reference_meta)


def enrich_bundle_with_sii(
    bundle: dict[str, list[dict[str, Any]]],
    sii_entity_search: str | Path | None,
    reference_meta_path: str | Path | None = None,
) -> dict[str, Any]:
    if not sii_entity_search:
        bundle["identity_resolutions"] = []
        return {
            "status": "NOT_RUN_NO_REFERENCE",
            "method": METHOD,
            "global_entity_key_policy": "ENT-RUT-{RUT_CANONICO_CON_GUION}",
            "attempted": 0,
            "resolved": 0,
            "ambiguous": 0,
            "no_match": 0,
            "invalid_existing_rut_rejected": 0,
            "rut_exact_entities_after": sum(1 for row in bundle.get("entities", []) if row.get("identity_method") == "RUT_EXACT"),
            "guardrail": GUARDRAIL,
        }
    path = Path(sii_entity_search)
    if not path.exists():
        raise FileNotFoundError(f"SII entity_search reference not found: {path}")
    candidate_names = {
        normalize_legal_name(row.get("canonical_name"))
        for row in bundle.get("entities", [])
        if not row.get("rut_normalized")
        and str(row.get("entity_type") or "") in ELIGIBLE_TYPES
        and row.get("canonical_name")
    }
    candidate_names.discard("")
    reference = _load_sii_reference(path, candidate_names)
    meta_path = Path(reference_meta_path) if reference_meta_path else None
    return _apply_reference_index(bundle, reference, _read_reference_meta(meta_path))
