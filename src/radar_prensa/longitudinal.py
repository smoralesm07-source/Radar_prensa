from __future__ import annotations

import math
from collections import Counter, defaultdict
from datetime import date, timedelta
from typing import Any, Iterable

from . import PRODUCER_ID
from .utils import stable_id

# Política determinística v0.3. Estas reglas describen contexto de prensa; no son scoring AML.
RECENT_DAYS = 7
BASELINE_DAYS = 28
MIN_BASELINE_DAYS = 14
MIN_BASELINE_DAYS_FOR_NEW = 21
RECURRENT_ENTITY_MIN_EVENTS = 4
RECURRENT_ENTITY_MIN_DATES = 3
RECURRENT_ENTITY_MIN_SOURCES = 2
CLUSTER_MAX_GAP_DAYS = 21
CLUSTER_SIGNAL_MIN_EVENTS = 3
CLUSTER_SIGNAL_MIN_SOURCES = 2

_SIGNAL_ENTITY_TYPES = {"PERSON", "LEGAL_ENTITY", "OSFL"}


def longitudinal_policy() -> dict[str, Any]:
    return {
        "version": "1.0",
        "time_basis": "PUBLICATION_DATE",
        "recent_days": RECENT_DAYS,
        "baseline_days": BASELINE_DAYS,
        "minimum_baseline_days": MIN_BASELINE_DAYS,
        "minimum_baseline_days_for_new_activity": MIN_BASELINE_DAYS_FOR_NEW,
        "entity_recurrence": {
            "minimum_events": RECURRENT_ENTITY_MIN_EVENTS,
            "minimum_distinct_dates": RECURRENT_ENTITY_MIN_DATES,
            "minimum_distinct_sources": RECURRENT_ENTITY_MIN_SOURCES,
        },
        "event_cluster": {
            "maximum_publication_gap_days": CLUSTER_MAX_GAP_DAYS,
            "signal_minimum_events": CLUSTER_SIGNAL_MIN_EVENTS,
            "signal_minimum_sources": CLUSTER_SIGNAL_MIN_SOURCES,
        },
        "guardrail": "Las métricas longitudinales describen recurrencia, concentración y cambio de cobertura periodística; no estiman probabilidad de delito ni riesgo LA/FT.",
    }


def _parse_date(value: Any) -> date | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        return date.fromisoformat(raw[:10])
    except ValueError:
        return None


def _publication_date(event: dict[str, Any]) -> date | None:
    return _parse_date(event.get("temporal", {}).get("publication_date"))


def _source_name(event: dict[str, Any]) -> str:
    return str(event.get("attributes", {}).get("source_name") or "").strip()


def _phenomena(event: dict[str, Any]) -> set[str]:
    return {str(x).strip() for x in event.get("attributes", {}).get("phenomena", []) if str(x).strip()}


def _stable_signal_phenomenon(value: str) -> bool:
    code = str(value or "").strip().casefold()
    return bool(code) and not code.startswith("din_") and code not in {"otro", "otros", "unknown"}


def _analysis_window(events: list[dict[str, Any]]) -> dict[str, Any]:
    dates = sorted(d for d in (_publication_date(e) for e in events) if d)
    if not dates:
        return {
            "time_basis": "PUBLICATION_DATE",
            "dataset_start": None,
            "anchor_date": None,
            "recent_from": None,
            "recent_to": None,
            "baseline_from": None,
            "baseline_to": None,
            "baseline_observed_from": None,
            "baseline_observed_days": 0,
            "baseline_quality": "INSUFFICIENT",
        }

    dataset_start = dates[0]
    anchor = dates[-1]
    recent_from = anchor - timedelta(days=RECENT_DAYS - 1)
    baseline_to = recent_from - timedelta(days=1)
    baseline_from = baseline_to - timedelta(days=BASELINE_DAYS - 1)
    observed_from = max(dataset_start, baseline_from)
    observed_days = (baseline_to - observed_from).days + 1 if observed_from <= baseline_to else 0
    quality = "FULL" if observed_days >= BASELINE_DAYS else ("PARTIAL" if observed_days >= MIN_BASELINE_DAYS else "INSUFFICIENT")
    return {
        "time_basis": "PUBLICATION_DATE",
        "dataset_start": dataset_start.isoformat(),
        "anchor_date": anchor.isoformat(),
        "recent_from": recent_from.isoformat(),
        "recent_to": anchor.isoformat(),
        "baseline_from": baseline_from.isoformat(),
        "baseline_to": baseline_to.isoformat(),
        "baseline_observed_from": observed_from.isoformat() if observed_days else None,
        "baseline_observed_days": observed_days,
        "baseline_quality": quality,
    }


def _event_evidence_ids(events: Iterable[dict[str, Any]]) -> list[str]:
    return sorted({eid for event in events for eid in event.get("evidence_ids", []) if eid})


def _window_stats(events: list[dict[str, Any]], window: dict[str, Any]) -> dict[str, Any]:
    anchor = _parse_date(window.get("anchor_date"))
    recent_from = _parse_date(window.get("recent_from"))
    baseline_to = _parse_date(window.get("baseline_to"))
    observed_from = _parse_date(window.get("baseline_observed_from"))
    observed_days = int(window.get("baseline_observed_days") or 0)
    if not anchor or not recent_from:
        return {
            "recent_count": 0,
            "recent_source_count": 0,
            "recent_active_days": 0,
            "baseline_count": 0,
            "baseline_source_count": 0,
            "baseline_observed_days": observed_days,
            "baseline_weekly_rate": 0.0,
            "recent_vs_baseline_ratio": None,
            "status": "INSUFFICIENT_BASELINE",
            "signal_eligible": False,
            "recent_event_ids": [],
            "baseline_event_ids": [],
            "recent_evidence_ids": [],
        }

    recent: list[dict[str, Any]] = []
    baseline: list[dict[str, Any]] = []
    for event in events:
        d = _publication_date(event)
        if not d:
            continue
        if recent_from <= d <= anchor:
            recent.append(event)
        elif observed_from and baseline_to and observed_from <= d <= baseline_to:
            baseline.append(event)

    recent_sources = {_source_name(e) for e in recent if _source_name(e)}
    baseline_sources = {_source_name(e) for e in baseline if _source_name(e)}
    recent_dates = {_publication_date(e) for e in recent if _publication_date(e)}
    baseline_rate = (len(baseline) / observed_days * 7) if observed_days else 0.0
    ratio = round(len(recent) / baseline_rate, 2) if baseline_rate > 0 else None

    if observed_days < MIN_BASELINE_DAYS:
        status = "INSUFFICIENT_BASELINE"
    elif len(recent) < 3:
        status = "LOW_VOLUME"
    elif not baseline:
        status = "NEW_ACTIVITY" if observed_days >= MIN_BASELINE_DAYS_FOR_NEW else "PARTIAL_BASELINE_ZERO"
    else:
        threshold = max(3, math.ceil(baseline_rate * 2))
        status = "ELEVATED" if len(recent) >= threshold and (len(recent) - baseline_rate) >= 2 else "STABLE"

    signal_eligible = status in {"NEW_ACTIVITY", "ELEVATED"} and len(recent_sources) >= 2 and len(recent_dates) >= 2
    return {
        "recent_count": len(recent),
        "recent_source_count": len(recent_sources),
        "recent_active_days": len(recent_dates),
        "baseline_count": len(baseline),
        "baseline_source_count": len(baseline_sources),
        "baseline_observed_days": observed_days,
        "baseline_weekly_rate": round(baseline_rate, 2),
        "recent_vs_baseline_ratio": ratio,
        "status": status,
        "signal_eligible": signal_eligible,
        "recent_event_ids": sorted(e["event_id"] for e in recent),
        "baseline_event_ids": sorted(e["event_id"] for e in baseline),
        "recent_evidence_ids": _event_evidence_ids(recent),
    }


def derive_entity_activity(bundle: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    entities = {e["entity_id"]: e for e in bundle.get("entities", [])}
    event_map: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for event in bundle.get("events", []):
        for entity_id in set(event.get("entity_ids", [])):
            event_map[entity_id].append(event)

    rows: list[dict[str, Any]] = []
    for entity_id, events in sorted(event_map.items()):
        entity = entities.get(entity_id, {})
        dated = sorted(
            ((d, e) for e in events if (d := _publication_date(e))),
            key=lambda item: (item[0], item[1].get("event_id", "")),
        )
        publication_dates = sorted({d.isoformat() for d, _ in dated})
        source_names = sorted({_source_name(e) for e in events if _source_name(e)})
        phenomena = sorted({p for e in events for p in _phenomena(e)})
        territories = sorted({t for e in events for t in e.get("territory_ids", [])})
        evidence_ids = _event_evidence_ids(events)
        monthly = Counter(d.strftime("%Y-%m") for d, _ in dated)
        occurrence_from = sorted(
            x for e in events
            if e.get("temporal", {}).get("occurrence_date_precision") != "UNKNOWN"
            if (x := e.get("temporal", {}).get("occurrence_date_from"))
        )
        occurrence_to = sorted(
            x for e in events
            if e.get("temporal", {}).get("occurrence_date_precision") != "UNKNOWN"
            if (x := e.get("temporal", {}).get("occurrence_date_to"))
        )
        known_occurrence_count = sum(1 for e in events if e.get("temporal", {}).get("occurrence_date_precision") != "UNKNOWN")
        recurrent = (
            len(events) >= RECURRENT_ENTITY_MIN_EVENTS
            and len(publication_dates) >= RECURRENT_ENTITY_MIN_DATES
            and len(source_names) >= RECURRENT_ENTITY_MIN_SOURCES
        )
        status = "RECURRENT" if recurrent else ("REPEATED" if len(events) >= 2 else "SINGLE")
        first_seen = publication_dates[0] if publication_dates else None
        last_seen = publication_dates[-1] if publication_dates else None
        first_date = _parse_date(first_seen)
        last_date = _parse_date(last_seen)
        rows.append({
            "entity_activity_id": stable_id("entity-activity:press", entity_id),
            "producer_id": PRODUCER_ID,
            "entity_id": entity_id,
            "canonical_name": entity.get("canonical_name"),
            "entity_type": entity.get("entity_type"),
            "rut_normalized": entity.get("rut_normalized"),
            "identity_method": entity.get("identity_method"),
            "identity_confidence": entity.get("identity_confidence"),
            "time_basis": "PUBLICATION_DATE",
            "first_seen_publication": first_seen,
            "last_seen_publication": last_seen,
            "publication_span_days": ((last_date - first_date).days + 1) if first_date and last_date else 0,
            "event_count": len(events),
            "active_publication_days": len(publication_dates),
            "source_count": len(source_names),
            "source_names": source_names,
            "monthly_event_counts": dict(sorted(monthly.items())),
            "phenomena": phenomena,
            "territory_ids": territories,
            "event_ids": sorted(e["event_id"] for e in events),
            "evidence_ids": evidence_ids,
            "occurrence_known_event_count": known_occurrence_count,
            "first_known_occurrence_from": occurrence_from[0] if occurrence_from else None,
            "last_known_occurrence_to": occurrence_to[-1] if occurrence_to else None,
            "recurrence_status": status,
            "recurrence_rule": f">={RECURRENT_ENTITY_MIN_EVENTS} eventos, >={RECURRENT_ENTITY_MIN_DATES} fechas y >={RECURRENT_ENTITY_MIN_SOURCES} fuentes",
            "semantics": "PRESS_RECURRENCE_CONTEXT",
            "interpretation_guardrail": "Recurrencia significa repetición de menciones/eventos de prensa; no acredita relación causal, conducta, delito ni riesgo AML.",
        })
    return rows


def derive_phenomenon_windows(bundle: dict[str, list[dict[str, Any]]], window: dict[str, Any]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for event in bundle.get("events", []):
        for phenomenon in _phenomena(event):
            grouped[phenomenon].append(event)
    rows = []
    for phenomenon, events in sorted(grouped.items()):
        rows.append({
            "phenomenon_window_id": stable_id("phen-window:press", phenomenon, window.get("anchor_date")),
            "producer_id": PRODUCER_ID,
            "phenomenon": phenomenon,
            "time_basis": "PUBLICATION_DATE",
            "window": dict(window),
            "stable_signal_taxonomy": _stable_signal_phenomenon(phenomenon),
            **_window_stats(events, window),
            "semantics": "LONGITUDINAL_PRESS_CONTEXT",
            "interpretation_guardrail": "El cambio refleja variación de cobertura periodística en ventanas comparables; no equivale a cambio de incidencia delictual o riesgo LA/FT.",
        })
    return rows


def derive_territorial_windows(bundle: dict[str, list[dict[str, Any]]], window: dict[str, Any]) -> list[dict[str, Any]]:
    territory_lookup = {t["territory_id"]: t for t in bundle.get("territories", [])}
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for event in bundle.get("events", []):
        for territory_id in set(event.get("territory_ids", [])):
            for phenomenon in _phenomena(event):
                grouped[(territory_id, phenomenon)].append(event)
    rows = []
    for (territory_id, phenomenon), events in sorted(grouped.items()):
        if len(events) < 2:
            continue
        territory = territory_lookup.get(territory_id, {})
        rows.append({
            "territorial_window_id": stable_id("territory-window:press", territory_id, phenomenon, window.get("anchor_date")),
            "producer_id": PRODUCER_ID,
            "territory_id": territory_id,
            "territory_name": territory.get("name"),
            "administrative_level": territory.get("administrative_level"),
            "phenomenon": phenomenon,
            "time_basis": "PUBLICATION_DATE",
            "window": dict(window),
            "stable_signal_taxonomy": _stable_signal_phenomenon(phenomenon),
            **_window_stats(events, window),
            "semantics": "TEMPORAL_TERRITORIAL_PRESS_CONTEXT",
            "interpretation_guardrail": "La concentración territorial refleja publicaciones asociadas al territorio; no implica que el hecho haya ocurrido allí ni que el territorio tenga mayor riesgo AML.",
        })
    return rows


def _strong_entity(entity_id: str, entity_lookup: dict[str, dict[str, Any]]) -> bool:
    row = entity_lookup.get(entity_id, {})
    return row.get("entity_type") in _SIGNAL_ENTITY_TYPES or bool(row.get("rut_normalized"))


def derive_event_clusters(bundle: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    events = [e for e in bundle.get("events", []) if _publication_date(e)]
    by_id = {e["event_id"]: e for e in events}
    entity_lookup = {e["entity_id"]: e for e in bundle.get("entities", [])}
    parent = {eid: eid for eid in by_id}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: str, b: str) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    by_phenomenon: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for event in events:
        for phenomenon in _phenomena(event):
            if _stable_signal_phenomenon(phenomenon):
                by_phenomenon[phenomenon].append(event)

    for group in by_phenomenon.values():
        ordered = sorted(group, key=lambda e: (_publication_date(e) or date.min, e["event_id"]))
        for i, left in enumerate(ordered):
            left_date = _publication_date(left)
            if not left_date:
                continue
            left_entities = set(left.get("entity_ids", []))
            left_territories = set(left.get("territory_ids", []))
            left_phenomena = _phenomena(left)
            for right in ordered[i + 1:]:
                right_date = _publication_date(right)
                if not right_date:
                    continue
                if (right_date - left_date).days > CLUSTER_MAX_GAP_DAYS:
                    break
                shared_entities = left_entities & set(right.get("entity_ids", []))
                shared_territories = left_territories & set(right.get("territory_ids", []))
                shared_phenomena = left_phenomena & _phenomena(right)
                strong_shared = {eid for eid in shared_entities if _strong_entity(eid, entity_lookup)}
                if strong_shared or len(shared_entities) >= 2 or (shared_territories and len(shared_phenomena) >= 2):
                    union(left["event_id"], right["event_id"])

    components: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for event in events:
        components[find(event["event_id"])].append(event)

    rows = []
    for component in components.values():
        if len(component) < 2:
            continue
        component = sorted(component, key=lambda e: (_publication_date(e) or date.min, e["event_id"]))
        entity_counts = Counter(eid for e in component for eid in set(e.get("entity_ids", [])))
        territory_counts = Counter(tid for e in component for tid in set(e.get("territory_ids", [])))
        phenomenon_counts = Counter(p for e in component for p in _phenomena(e))
        shared_entities = sorted(eid for eid, n in entity_counts.items() if n >= 2)
        shared_territories = sorted(tid for tid, n in territory_counts.items() if n >= 2)
        recurring_phenomena = sorted(p for p, n in phenomenon_counts.items() if n >= 2)
        strong_shared = sorted(eid for eid in shared_entities if _strong_entity(eid, entity_lookup))
        sources = sorted({_source_name(e) for e in component if _source_name(e)})
        dates = sorted({_publication_date(e) for e in component if _publication_date(e)})
        if not shared_entities and not shared_territories:
            continue
        strength = "STRONG" if strong_shared and len(sources) >= 2 else ("MODERATE" if len(sources) >= 2 else "WEAK")
        event_ids = sorted(e["event_id"] for e in component)
        rows.append({
            "cluster_id": stable_id("cluster:press", *event_ids),
            "producer_id": PRODUCER_ID,
            "cluster_type": "ENTITY_ANCHORED" if strong_shared else "MULTI_ANCHOR",
            "cluster_strength": strength,
            "time_basis": "PUBLICATION_DATE",
            "publication_date_from": dates[0].isoformat() if dates else None,
            "publication_date_to": dates[-1].isoformat() if dates else None,
            "publication_span_days": ((dates[-1] - dates[0]).days + 1) if dates else 0,
            "event_count": len(component),
            "active_publication_days": len(dates),
            "source_count": len(sources),
            "source_names": sources,
            "event_ids": event_ids,
            "evidence_ids": _event_evidence_ids(component),
            "shared_entity_ids": shared_entities,
            "strong_shared_entity_ids": strong_shared,
            "shared_territory_ids": shared_territories,
            "recurring_phenomena": recurring_phenomena,
            "semantics": "CONTEXTUAL_EVENT_CLUSTER",
            "explanation": "Eventos próximos en el tiempo conectados por fenómenos y anclas compartidas (entidades y/o territorios).",
            "interpretation_guardrail": "El cluster es una agrupación analítica de publicaciones; no prueba que todos los eventos correspondan al mismo hecho, caso o red criminal.",
        })
    return sorted(rows, key=lambda r: (-r["event_count"], r["cluster_id"]))


def derive_longitudinal_signals(
    entity_activity: list[dict[str, Any]],
    phenomenon_windows: list[dict[str, Any]],
    territorial_windows: list[dict[str, Any]],
    event_clusters: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    signals: list[dict[str, Any]] = []

    for row in entity_activity:
        if row.get("recurrence_status") != "RECURRENT":
            continue
        entity_type = row.get("entity_type")
        if entity_type not in _SIGNAL_ENTITY_TYPES and not row.get("rut_normalized"):
            continue
        if float(row.get("identity_confidence") or 0.0) < 0.70:
            continue
        signals.append({
            "signal_id": stable_id("signal:press", "entity_recurrence", row["entity_id"], row.get("last_seen_publication")),
            "producer_id": PRODUCER_ID,
            "signal_type": "ENTITY_RECURRENCE",
            "rule_version": "longitudinal-v1.0",
            "scope": {"entity_id": row["entity_id"], "canonical_name": row.get("canonical_name"), "entity_type": entity_type, "time_basis": "PUBLICATION_DATE"},
            "value": row["event_count"],
            "threshold": RECURRENT_ENTITY_MIN_EVENTS,
            "metrics": {
                "active_publication_days": row["active_publication_days"],
                "source_count": row["source_count"],
                "first_seen_publication": row.get("first_seen_publication"),
                "last_seen_publication": row.get("last_seen_publication"),
            },
            "event_ids": row["event_ids"],
            "evidence_ids": row["evidence_ids"],
            "semantics": "CONTEXT_ONLY",
            "explanation": f"La entidad aparece en {row['event_count']} eventos, {row['active_publication_days']} fechas y {row['source_count']} fuentes.",
            "interpretation_guardrail": "Recurrencia de prensa no implica participación, responsabilidad ni riesgo AML.",
        })

    for row in phenomenon_windows:
        if not row.get("signal_eligible") or not row.get("stable_signal_taxonomy"):
            continue
        status = row.get("status")
        signal_type = "PHENOMENON_EMERGENCE" if status == "NEW_ACTIVITY" else "PHENOMENON_MOMENTUM"
        signals.append({
            "signal_id": stable_id("signal:press", signal_type, row["phenomenon"], row.get("window", {}).get("anchor_date")),
            "producer_id": PRODUCER_ID,
            "signal_type": signal_type,
            "rule_version": "longitudinal-v1.0",
            "scope": {"phenomenon": row["phenomenon"], "time_basis": "PUBLICATION_DATE"},
            "value": row["recent_count"],
            "threshold": 3,
            "window": row["window"],
            "baseline": {"count": row["baseline_count"], "observed_days": row["baseline_observed_days"], "weekly_rate": row["baseline_weekly_rate"]},
            "metrics": {
                "status": status,
                "recent_source_count": row["recent_source_count"],
                "recent_active_days": row["recent_active_days"],
                "recent_vs_baseline_ratio": row["recent_vs_baseline_ratio"],
            },
            "event_ids": row["recent_event_ids"],
            "evidence_ids": row["recent_evidence_ids"],
            "semantics": "CONTEXT_ONLY",
            "explanation": f"{row['phenomenon']} registra {row['recent_count']} publicaciones recientes frente a una tasa basal semanal de {row['baseline_weekly_rate']}.",
            "interpretation_guardrail": "La señal mide cambio de cobertura periodística, no aumento probado de actividad delictual ni de riesgo LA/FT.",
        })

    for row in territorial_windows:
        if not row.get("signal_eligible") or not row.get("stable_signal_taxonomy"):
            continue
        signals.append({
            "signal_id": stable_id("signal:press", "territorial_momentum", row["territory_id"], row["phenomenon"], row.get("window", {}).get("anchor_date")),
            "producer_id": PRODUCER_ID,
            "signal_type": "TERRITORIAL_MOMENTUM",
            "rule_version": "longitudinal-v1.0",
            "scope": {
                "territory_id": row["territory_id"],
                "territory_name": row.get("territory_name"),
                "administrative_level": row.get("administrative_level"),
                "phenomenon": row["phenomenon"],
                "time_basis": "PUBLICATION_DATE",
            },
            "value": row["recent_count"],
            "threshold": 3,
            "window": row["window"],
            "baseline": {"count": row["baseline_count"], "observed_days": row["baseline_observed_days"], "weekly_rate": row["baseline_weekly_rate"]},
            "metrics": {
                "status": row["status"],
                "recent_source_count": row["recent_source_count"],
                "recent_active_days": row["recent_active_days"],
                "recent_vs_baseline_ratio": row["recent_vs_baseline_ratio"],
            },
            "event_ids": row["recent_event_ids"],
            "evidence_ids": row["recent_evidence_ids"],
            "semantics": "CONTEXT_ONLY",
            "explanation": f"Aumenta la cobertura reciente de {row['phenomenon']} asociada a {row.get('territory_name') or row['territory_id']}.",
            "interpretation_guardrail": "La señal territorial refleja asociación en prensa; no acredita lugar de ocurrencia ni mayor riesgo del territorio.",
        })

    for row in event_clusters:
        if row.get("event_count", 0) < CLUSTER_SIGNAL_MIN_EVENTS or row.get("source_count", 0) < CLUSTER_SIGNAL_MIN_SOURCES:
            continue
        signals.append({
            "signal_id": stable_id("signal:press", "cross_source_event_cluster", row["cluster_id"]),
            "producer_id": PRODUCER_ID,
            "signal_type": "CROSS_SOURCE_EVENT_CLUSTER",
            "rule_version": "longitudinal-v1.0",
            "scope": {"cluster_id": row["cluster_id"], "cluster_type": row["cluster_type"], "cluster_strength": row["cluster_strength"], "time_basis": "PUBLICATION_DATE"},
            "value": row["event_count"],
            "threshold": CLUSTER_SIGNAL_MIN_EVENTS,
            "metrics": {
                "source_count": row["source_count"],
                "active_publication_days": row["active_publication_days"],
                "publication_date_from": row["publication_date_from"],
                "publication_date_to": row["publication_date_to"],
            },
            "event_ids": row["event_ids"],
            "evidence_ids": row["evidence_ids"],
            "semantics": "CONTEXT_ONLY",
            "explanation": f"Cluster de {row['event_count']} eventos conectados observado en {row['source_count']} fuentes.",
            "interpretation_guardrail": "El cluster sugiere continuidad temática o relacional para revisión humana; no consolida automáticamente los eventos como un único caso.",
        })
    return sorted(signals, key=lambda r: (r["signal_type"], r["signal_id"]))


def derive_longitudinal(bundle: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    window = _analysis_window(bundle.get("events", []))
    entity_activity = derive_entity_activity(bundle)
    phenomenon_windows = derive_phenomenon_windows(bundle, window)
    territorial_windows = derive_territorial_windows(bundle, window)
    event_clusters = derive_event_clusters(bundle)
    signals = derive_longitudinal_signals(entity_activity, phenomenon_windows, territorial_windows, event_clusters)
    return {
        "analysis_window": window,
        "policy": longitudinal_policy(),
        "entity_activity": entity_activity,
        "phenomenon_windows": phenomenon_windows,
        "territorial_windows": territorial_windows,
        "event_clusters": event_clusters,
        "signals": signals,
    }
