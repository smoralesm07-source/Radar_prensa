from __future__ import annotations

from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from . import PRODUCER_ID, __version__
from .entities import extract_entities, extract_explicit_relationships
from .geography import extract_territories, geography_catalog_stats
from .importer import extract_records, load_monitor
from .taxonomy import classify_text
from .temporal import event_temporal, publication_time
from .utils import canonical_url, now_iso, sha256_text, stable_id, write_jsonl


def _get(record: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if record.get(key) not in (None, "", []):
            return record.get(key)
    return None


def _list_codes(value: Any) -> list[str]:
    if not value:
        return []
    if isinstance(value, list):
        out = []
        for item in value:
            if isinstance(item, dict):
                out.append(str(item.get("clave") or item.get("code") or item.get("label") or "").strip())
            else:
                out.append(str(item).strip())
        return [x for x in out if x]
    return [str(value)]


def _article_text(record: dict[str, Any], title: str, summary: str) -> str:
    values: list[str] = [title, summary]
    for key in (
        "tema", "bajada", "descripcion", "texto_enriquecido", "texto",
        "contenido", "content", "evidencia_uaf",
    ):
        value = record.get(key)
        if value:
            values.append(str(value))
    return "\n".join(dict.fromkeys(x for x in values if x))


def transform(payload: dict[str, Any], retrieved_at: str | None = None) -> dict[str, list[dict[str, Any]]]:
    retrieved_at = retrieved_at or now_iso()
    documents: list[dict[str, Any]] = []
    evidence: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []
    entities: dict[str, dict[str, Any]] = {}
    territories: dict[str, dict[str, Any]] = {}
    mentions: list[dict[str, Any]] = []
    event_territories: list[dict[str, Any]] = []
    event_entities: list[dict[str, Any]] = []
    relationships: list[dict[str, Any]] = []
    sectors: dict[str, dict[str, Any]] = {}
    temporal_assertions: list[dict[str, Any]] = []

    seen_urls: set[str] = set()
    for record in extract_records(payload):
        url = canonical_url(_get(record, "link", "url", "source_url"))
        if not url or url in seen_urls:
            continue
        seen_urls.add(url)

        title = str(_get(record, "titulo", "title", "tema") or "Sin título").strip()
        summary = str(_get(record, "resumen", "tema", "summary", "bajada", "descripcion") or "").strip()
        article_text = _article_text(record, title, summary)
        body_hint = str(_get(record, "texto_enriquecido", "texto", "contenido", "content", "evidencia_uaf") or "").strip()
        source_name = str(_get(record, "medio", "source", "fuente") or "Fuente de prensa").strip()
        source_id = stable_id("source:press", source_name)
        doc_id = stable_id("document:press", url)
        evidence_id = stable_id("evidence:press", url)
        publication = publication_time(record)

        classification = classify_text(title, summary, body_hint, _get(record, "fenomeno", "fenomenos"), _get(record, "topicos"))
        uaf_explicit = bool(record.get("uaf_chile") or record.get("uaf")) or classification["uaf_explicit_mention"]
        aml_relevant = bool(record.get("nucleo")) or classification["aml_context_relevance"]
        upstream_phenomena = _list_codes(_get(record, "fenomenos", "fenomeno", "casos"))
        upstream_topics = _list_codes(_get(record, "topicos", "temas"))
        upstream_nature = str(_get(record, "naturaleza", "nature") or "").strip().upper()
        phenomena = sorted({p["code"] for p in classification["phenomena"]} | set(upstream_phenomena))
        nature = upstream_nature or classification["nature"]

        sector_codes = sorted(set(_list_codes(_get(record, "sujetos_obligados", "sectores"))))
        sector_ids = []
        for code in sector_codes:
            sid = f"sector:uaf:{__import__('re').sub(r'[^a-z0-9]+', '-', __import__('unicodedata').normalize('NFKD', code).encode('ascii', 'ignore').decode().casefold()).strip('-')}"
            sector_ids.append(sid)
            sectors[sid] = {"sector_id": sid, "label": code, "taxonomy": "MONITOR_UAF", "producer_id": PRODUCER_ID}

        temporal = event_temporal(record, article_text=article_text)

        documents.append({
            "document_id": doc_id,
            "producer_id": PRODUCER_ID,
            "source_id": source_id,
            "source_name": source_name,
            "source_url": url,
            "title": title,
            "summary": summary,
            "published_at": publication,
            "retrieved_at": retrieved_at,
            "document_type": "PRESS_ARTICLE",
            "uaf_explicit_mention": uaf_explicit,
            "aml_context_relevance": aml_relevant or bool(upstream_topics or upstream_phenomena),
            "phenomena": phenomena,
            "topics": upstream_topics,
            "nature": nature,
            "schema_version": "1.1",
        })

        excerpt = (body_hint or summary or title)[:500]
        evidence.append({
            "evidence_id": evidence_id,
            "producer_id": PRODUCER_ID,
            "source_id": source_id,
            "ultimate_source_id": source_id,
            "source_url": url,
            "source_tier": "PRESS",
            "capture_method": "MONITOR_UAF_ADAPTER",
            "source_run_id": None,
            "content_sha256": sha256_text("\n".join([title, summary, body_hint, url])),
            "quality_status": "VALID" if title and url else "PARTIAL",
            "source_published_at": publication,
            "retrieved_at": retrieved_at,
            "ingested_at": retrieved_at,
            "excerpt": excerpt,
            "schema_version": "1.0",
        })

        doc_entities = extract_entities(record, evidence_id)
        doc_territories = extract_territories(record)

        for row in doc_entities:
            existing = entities.get(row["entity_id"])
            if existing:
                existing["evidence_ids"] = sorted(set(existing["evidence_ids"] + row["evidence_ids"]))
            else:
                entities[row["entity_id"]] = row
            mentions.append({
                "mention_id": stable_id("mention:press", doc_id, row["entity_id"]),
                "document_id": doc_id,
                "entity_id": row["entity_id"],
                "evidence_id": evidence_id,
                "mention_role": "PRESS_MENTION",
            })

        for row in doc_territories:
            territories[row["territory_id"]] = row

        event_id = stable_id("event:press", url, ",".join(phenomena), nature)
        events.append({
            "event_id": event_id,
            "event_type": "PRESS_CONTEXT_EVENT",
            "producer_id": PRODUCER_ID,
            "entity_ids": sorted(row["entity_id"] for row in doc_entities),
            "territory_ids": sorted(row["territory_id"] for row in doc_territories),
            "sector_ids": sector_ids,
            "evidence_ids": [evidence_id],
            "temporal": temporal,
            "attributes": {
                "document_id": doc_id,
                "headline": title,
                "source_name": source_name,
                "nature": nature,
                "phenomena": phenomena,
                "topics": upstream_topics,
                "uaf_explicit_mention": uaf_explicit,
                "aml_context_relevance": aml_relevant or bool(upstream_topics or upstream_phenomena),
                "interpretation_guardrail": "Contexto de prensa: no atribuye por sí solo conducta, delito ni riesgo AML a una entidad.",
            },
        })

        if temporal.get("occurrence_date_precision") != "UNKNOWN":
            temporal_assertions.append({
                "temporal_assertion_id": stable_id("temporal:press", event_id, temporal.get("occurrence_date_rule"), temporal.get("occurrence_date_from"), temporal.get("occurrence_date_to")),
                "producer_id": PRODUCER_ID,
                "event_id": event_id,
                "document_id": doc_id,
                "evidence_id": evidence_id,
                "occurrence_date_from": temporal.get("occurrence_date_from"),
                "occurrence_date_to": temporal.get("occurrence_date_to"),
                "occurrence_date_anchor": temporal.get("occurrence_date_anchor"),
                "precision": temporal.get("occurrence_date_precision"),
                "basis": temporal.get("occurrence_date_basis"),
                "rule": temporal.get("occurrence_date_rule"),
                "confidence": temporal.get("occurrence_date_confidence"),
                "evidence_excerpt": temporal.get("occurrence_date_evidence"),
                "publication_date": temporal.get("publication_date"),
                "semantics": "TEMPORAL_CONTEXT_ASSERTION",
            })

        relationships.extend(extract_explicit_relationships(record, doc_entities, evidence_id, event_id))
        for row in doc_entities:
            event_entities.append({"event_id": event_id, "entity_id": row["entity_id"], "evidence_id": evidence_id})
        for row in doc_territories:
            event_territories.append({
                "event_id": event_id,
                "territory_id": row["territory_id"],
                "evidence_id": evidence_id,
                "association_method": row.get("match_rule") or row.get("origin"),
                "confidence": row.get("confidence"),
                "is_derived_parent": row.get("origin") == "derived_hierarchy",
            })

    return {
        "documents": documents,
        "events": events,
        "evidence": evidence,
        "entities": list(entities.values()),
        "territories": list(territories.values()),
        "entity_mentions": mentions,
        "event_entities": event_entities,
        "event_territories": event_territories,
        "relationships": relationships,
        "sectors": list(sectors.values()),
        "temporal_assertions": temporal_assertions,
    }


def derive_context_signals(bundle: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    """Señales contextuales explicables. Nunca son scores AML."""
    events = bundle["events"]
    by_day_phen = Counter()
    by_territory_phen = Counter()
    sources_by_phen: dict[str, set[str]] = defaultdict(set)

    for event in events:
        attrs = event.get("attributes", {})
        day = event.get("temporal", {}).get("publication_date")
        for phenomenon in attrs.get("phenomena", []):
            if day:
                by_day_phen[(day, phenomenon)] += 1
            sources_by_phen[phenomenon].add(attrs.get("source_name") or "")
            for territory_id in event.get("territory_ids", []):
                by_territory_phen[(territory_id, phenomenon)] += 1

    signals: list[dict[str, Any]] = []
    for (day, phenomenon), count in sorted(by_day_phen.items()):
        if count >= 3:
            signals.append({
                "signal_id": stable_id("signal:press", "media_burst", day, phenomenon),
                "producer_id": PRODUCER_ID,
                "signal_type": "MEDIA_BURST",
                "scope": {"date": day, "phenomenon": phenomenon, "time_basis": "PUBLICATION_DATE"},
                "value": count,
                "threshold": 3,
                "semantics": "CONTEXT_ONLY",
                "explanation": f"{count} publicaciones clasificadas en {phenomenon} el {day}.",
            })

    for (territory_id, phenomenon), count in sorted(by_territory_phen.items()):
        if count >= 3:
            signals.append({
                "signal_id": stable_id("signal:press", "geo_concentration", territory_id, phenomenon),
                "producer_id": PRODUCER_ID,
                "signal_type": "GEOGRAPHIC_CONCENTRATION",
                "scope": {"territory_id": territory_id, "phenomenon": phenomenon},
                "value": count,
                "threshold": 3,
                "semantics": "CONTEXT_ONLY",
                "explanation": f"{count} acontecimientos de prensa asociados al territorio y fenómeno indicados.",
            })

    for phenomenon, source_names in sorted(sources_by_phen.items()):
        clean = {x for x in source_names if x}
        if len(clean) >= 3:
            signals.append({
                "signal_id": stable_id("signal:press", "source_convergence", phenomenon, *sorted(clean)),
                "producer_id": PRODUCER_ID,
                "signal_type": "SOURCE_CONVERGENCE",
                "scope": {"phenomenon": phenomenon},
                "value": len(clean),
                "threshold": 3,
                "semantics": "CONTEXT_ONLY",
                "explanation": f"El fenómeno aparece en {len(clean)} fuentes de prensa distintas.",
            })
    return signals


def _quality_metrics(bundle: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    events = bundle["events"]
    known_temporal = [e for e in events if e.get("temporal", {}).get("occurrence_date_precision") != "UNKNOWN"]
    geo_events = [e for e in events if e.get("territory_ids")]
    precision = Counter(e.get("temporal", {}).get("occurrence_date_precision", "UNKNOWN") for e in events)
    return {
        "geography_catalog": geography_catalog_stats(),
        "events_with_territory": len(geo_events),
        "territorial_coverage_pct": round(100 * len(geo_events) / len(events), 2) if events else 0.0,
        "events_with_occurrence_time": len(known_temporal),
        "occurrence_time_coverage_pct": round(100 * len(known_temporal) / len(events), 2) if events else 0.0,
        "temporal_precision": dict(sorted(precision.items())),
    }


def run(source: str, output: str = "data/exports") -> dict[str, Any]:
    payload = load_monitor(source)
    retrieved_at = now_iso()
    bundle = transform(payload, retrieved_at=retrieved_at)
    signals = derive_context_signals(bundle)

    out = Path(output)
    out.mkdir(parents=True, exist_ok=True)
    for key, rows in bundle.items():
        write_jsonl(out / f"{key}.jsonl", rows)
    write_jsonl(out / "signals.jsonl", signals)

    manifest = {
        "producer_id": PRODUCER_ID,
        "version": __version__,
        "generated_at": retrieved_at,
        "input": str(source),
        "counts": {**{k: len(v) for k, v in bundle.items()}, "signals": len(signals)},
        "quality": _quality_metrics(bundle),
        "contracts": {
            "events": "Intelligence_Fusion_Layer/schemas/event.schema.json",
            "evidence": "Intelligence_Fusion_Layer/schemas/evidence.schema.json",
            "entities": "Intelligence_Fusion_Layer/schemas/entity.schema.json",
        },
        "guardrails": [
            "Prensa es contexto y evidencia secundaria; no acredita hechos por sí sola.",
            "Fecha de publicación no se usa automáticamente como fecha de ocurrencia.",
            "Las inferencias temporales desde texto conservan regla, evidencia, precisión y confianza.",
            "Mención, coaparición o proximidad territorial no propaga riesgo AML.",
            "La jerarquía comuna/provincia→región es contexto geográfico, no relación entre entidades.",
            "Las señales de Radar Prensa son CONTEXT_ONLY y no son probabilidad de delito o LA/FT.",
        ],
    }
    (out / "manifest.json").write_text(__import__("json").dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest
