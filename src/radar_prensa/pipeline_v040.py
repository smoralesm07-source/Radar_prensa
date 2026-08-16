from __future__ import annotations

from pathlib import Path
from typing import Any

from . import PRODUCER_ID, __version__
from .identity_enrichment import enrich_bundle_with_sii
from .importer import load_monitor
from .longitudinal import derive_longitudinal
from .pipeline import _quality_metrics, derive_context_signals, transform
from .utils import now_iso, write_jsonl


def run(
    source: str,
    output: str = "data/exports",
    sii_entity_search: str | None = None,
    sii_reference_meta: str | None = None,
) -> dict[str, Any]:
    payload = load_monitor(source)
    retrieved_at = now_iso()
    bundle = transform(payload, retrieved_at=retrieved_at)

    identity = enrich_bundle_with_sii(
        bundle,
        sii_entity_search=sii_entity_search,
        reference_meta_path=sii_reference_meta,
    )

    # Toda analítica longitudinal se calcula después de la resolución de identidad
    # para que recurrencia y clusters utilicen el mismo entity_id reconciliado.
    longitudinal = derive_longitudinal(bundle)
    context_signals = derive_context_signals(bundle)
    signals = sorted(
        context_signals + longitudinal["signals"],
        key=lambda row: (row.get("signal_type", ""), row.get("signal_id", "")),
    )

    longitudinal_products = {
        "entity_activity": longitudinal["entity_activity"],
        "phenomenon_windows": longitudinal["phenomenon_windows"],
        "territorial_windows": longitudinal["territorial_windows"],
        "event_clusters": longitudinal["event_clusters"],
    }

    out = Path(output)
    out.mkdir(parents=True, exist_ok=True)
    for key, rows in bundle.items():
        write_jsonl(out / f"{key}.jsonl", rows)
    for key, rows in longitudinal_products.items():
        write_jsonl(out / f"{key}.jsonl", rows)
    write_jsonl(out / "signals.jsonl", signals)

    counts = {k: len(v) for k, v in bundle.items()}
    counts.update({k: len(v) for k, v in longitudinal_products.items()})
    counts["signals"] = len(signals)
    counts["longitudinal_signals"] = len(longitudinal["signals"])

    quality = _quality_metrics(bundle, longitudinal)
    quality["identity_enrichment"] = identity

    manifest = {
        "producer_id": PRODUCER_ID,
        "version": __version__,
        "generated_at": retrieved_at,
        "input": str(source),
        "counts": counts,
        "quality": quality,
        "identity_enrichment": identity,
        "analysis": {
            "longitudinal_policy": longitudinal["policy"],
            "analysis_window": longitudinal["analysis_window"],
        },
        "contracts": {
            "events": "Intelligence_Fusion_Layer/schemas/event.schema.json",
            "evidence": "Intelligence_Fusion_Layer/schemas/evidence.schema.json",
            "entities": "Intelligence_Fusion_Layer/schemas/entity.schema.json",
            "signals": "Radar Prensa CONTEXT_ONLY signals adaptados al Signals Registry por Intelligence_Fusion_Layer.",
            "identity_resolutions": "Radar_Prensa v0.4 governed derived audit product; no es evidencia primaria ni señal AML.",
        },
        "guardrails": [
            "Prensa es contexto y evidencia secundaria; no acredita hechos por sí sola.",
            "Fecha de publicación no se usa automáticamente como fecha de ocurrencia.",
            "Las inferencias temporales desde texto conservan regla, evidencia, precisión y confianza.",
            "Mención, coaparición o proximidad territorial no propaga riesgo AML.",
            "La jerarquía comuna/provincia→región es contexto geográfico, no relación entre entidades.",
            "Las señales de Radar Prensa son CONTEXT_ONLY y no son probabilidad de delito o LA/FT.",
            "Emergencia y momentum significan cambio de cobertura periodística respecto de un baseline; no cambio probado de incidencia delictual.",
            "Los clusters son agrupaciones analíticas para revisión humana y no consolidan automáticamente publicaciones en un mismo caso.",
            "RUT_EXACT requiere dígito verificador válido.",
            "Una entidad sin RUT sólo se promueve con coincidencia exacta normalizada y unívoca contra la razón social oficial publicada por Radar SII.",
            "Coincidencia ambigua, fuzzy, por territorio, por co-mención o por similitud de nombre no resuelve identidad.",
            "La resolución de identidad no convierte una noticia en señal AML ni acredita conducta de la entidad.",
        ],
    }
    (out / "manifest.json").write_text(
        __import__("json").dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return manifest
