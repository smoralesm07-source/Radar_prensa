from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from radar_prensa.geo_catalog import catalog_counts
from radar_prensa.geography import extract_territories
from radar_prensa.importer import extract_records
from radar_prensa.longitudinal import derive_longitudinal
from radar_prensa.pipeline import derive_context_signals, run, transform
from radar_prensa.temporal import event_temporal


def sample_payload():
    common_entities = [
        {
            "entidad_id": "ENT-A",
            "nombre": "Importadora Norte SpA",
            "tipo": "EMPRESA",
            "naturaleza": "PERSONA_JURIDICA",
            "confianza_score": 0.9,
            "relaciones_explicitas": [{"tipo": "TRANSACCION_ENTRE", "contraparte_id": "ENT-B", "contraparte": "Persona Uno", "confianza": "media"}],
        },
        {"entidad_id": "ENT-B", "nombre": "Persona Uno", "tipo": "PERSONA", "naturaleza": "PERSONA_NATURAL", "confianza_score": 0.95},
    ]
    return {
        "prensa": [
            {
                "fecha": "2026-08-15", "fecha_iso": "2026-08-15T10:00:00-04:00",
                "medio": "Medio A", "titulo": "Operativo de PDI por contrabando en Iquique",
                "tema": "La investigación comenzó en noviembre de 2025.", "link": "https://example.com/a?utm_source=x",
                "lugares": [{"nombre": "Iquique", "nivel": "comuna", "confianza": "alta"}],
                "nomina_entidades": common_entities, "sujetos_obligados": ["casas_cambio"], "nucleo": True,
            },
            {"fecha": "2026-08-15", "medio": "Medio B", "titulo": "Fiscalía investiga contrabando en Iquique", "link": "https://example.com/b"},
            {"fecha": "2026-08-15", "medio": "Medio C", "titulo": "Nueva arista de contrabando en Iquique", "link": "https://example.com/c"},
        ]
    }


def longitudinal_payload():
    entity = {
        "entidad_id": "ENT-RECURRENTE",
        "nombre": "Importadora Norte SpA",
        "tipo": "EMPRESA",
        "naturaleza": "PERSONA_JURIDICA",
        "rut": "76123456-7",
        "confianza_score": 0.95,
    }

    def article(day: str, source: str, suffix: str, phenomenon: str = "contrabando", with_entity: bool = True):
        return {
            "fecha": day,
            "medio": source,
            "titulo": f"Fiscalía investiga {phenomenon} en Iquique {suffix}",
            "tema": f"Nuevos antecedentes sobre {phenomenon} en la comuna de Iquique.",
            "link": f"https://example.com/longitudinal/{suffix}",
            "fenomenos": [phenomenon],
            "lugares": [{"nombre": "Iquique", "nivel": "comuna", "confianza": 0.98}],
            "nomina_entidades": [entity] if with_entity else [],
            "nucleo": True,
        }

    return {
        "prensa": [
            {
                "fecha": "2026-07-01",
                "medio": "Medio Histórico",
                "titulo": "Reporte económico sin relación con contrabando",
                "tema": "Informe financiero general.",
                "link": "https://example.com/longitudinal/coverage-anchor",
                "fenomenos": ["delitos_economicos"],
            },
            article("2026-07-20", "Medio Base", "baseline"),
            article("2026-08-10", "Medio A", "recent-a"),
            article("2026-08-11", "Medio B", "recent-b"),
            article("2026-08-14", "Medio C", "recent-c"),
            article("2026-08-16", "Medio D", "recent-d"),
        ]
    }


def recent_only_payload():
    entity = {
        "entidad_id": "ENT-NEW",
        "nombre": "Sociedad Reciente SpA",
        "tipo": "EMPRESA",
        "naturaleza": "PERSONA_JURIDICA",
        "confianza_score": 0.92,
    }
    return {
        "prensa": [
            {
                "fecha": day,
                "medio": source,
                "titulo": f"Operativo por contrabando en Iquique {idx}",
                "tema": "Caso de contrabando en la comuna de Iquique.",
                "link": f"https://example.com/recent-only/{idx}",
                "fenomenos": ["contrabando"],
                "lugares": [{"nombre": "Iquique", "nivel": "comuna", "confianza": 0.98}],
                "nomina_entidades": [entity],
            }
            for idx, (day, source) in enumerate([
                ("2026-08-11", "Medio A"),
                ("2026-08-13", "Medio B"),
                ("2026-08-16", "Medio C"),
            ], start=1)
        ]
    }


class RadarPrensaTests(unittest.TestCase):
    def test_extract_records(self):
        self.assertEqual(len(extract_records(sample_payload())), 3)

    def test_geography_catalog_is_complete(self):
        self.assertEqual(catalog_counts(), {"regions": 16, "provinces": 56, "communes": 346})

    def test_geography_full_catalog_and_hierarchy(self):
        rows = extract_territories({"titulo": "Operativo en la comuna de General Lagos, Región de Arica y Parinacota", "fecha": "2026-08-16"})
        by_level = {(r["administrative_level"], r["name"]) for r in rows}
        self.assertIn(("COMUNA", "General Lagos"), by_level)
        self.assertIn(("REGION", "Arica y Parinacota"), by_level)
        commune = next(r for r in rows if r["administrative_level"] == "COMUNA")
        self.assertEqual(commune["parent_region_id"], "territory:cl:region:arica-y-parinacota")

    def test_geography_ambiguous_person_is_not_promoted(self):
        rows = extract_territories({"titulo": "Doña María Elena declaró ante el tribunal"})
        self.assertFalse(any(r["name"] == "María Elena" for r in rows))
        rows = extract_territories({"titulo": "Operativo en la comuna de María Elena deja detenidos"})
        self.assertTrue(any(r["name"] == "María Elena" and r["administrative_level"] == "COMUNA" for r in rows))

    def test_geography_person_surname_does_not_create_commune(self):
        rows = extract_territories({
            "titulo": "Periodista entrega nuevos antecedentes",
            "texto_enriquecido": "La periodista Carolina Saavedra difundió una versión sobre el caso.",
            "nomina_entidades": [{
                "entidad_id": "ENT-PERSON",
                "nombre": "Carolina Saavedra",
                "tipo": "PERSONA",
                "naturaleza": "PERSONA_NATURAL",
            }],
        })
        self.assertFalse(any(r["name"] == "Saavedra" for r in rows))

    def test_geography_foreign_homonym_is_not_chilean_commune(self):
        rows = extract_territories({
            "titulo": "Investigado permanece en Florida, Estados Unidos",
            "texto_enriquecido": "El imputado se encuentra en Sarasota, Florida, Estados Unidos.",
        })
        self.assertFalse(any(r["name"] == "Florida" and r["administrative_level"] == "COMUNA" for r in rows))

    def test_geography_subcommunal_name_is_not_promoted_to_commune(self):
        rows = extract_territories({"titulo": "Operativo en la población San Gregorio dejó detenidos"})
        self.assertFalse(any(r["name"] == "San Gregorio" and r["administrative_level"] == "COMUNA" for r in rows))
        rows = extract_territories({"titulo": "Operativo en la comuna de San Gregorio dejó detenidos"})
        self.assertTrue(any(r["name"] == "San Gregorio" and r["administrative_level"] == "COMUNA" for r in rows))

    def test_geography_requires_place_context_for_text_only_match(self):
        rows = extract_territories({"titulo": "Carolina Saavedra comentó el caso Santiago"})
        self.assertFalse(any(r["name"] in {"Saavedra", "Santiago"} for r in rows))
        rows = extract_territories({"titulo": "El tribunal de Santiago revisó la causa"})
        self.assertTrue(any(r["name"] == "Santiago" and r["administrative_level"] == "COMUNA" for r in rows))

    def test_temporal_month_from_article_text(self):
        temporal = event_temporal({"fecha": "2026-08-16", "titulo": "La investigación comenzó en noviembre de 2025 y continuó durante meses."})
        self.assertEqual(temporal["occurrence_date_precision"], "MONTH")
        self.assertEqual(temporal["occurrence_date_from"], "2025-11-01")
        self.assertEqual(temporal["occurrence_date_to"], "2025-11-30")
        self.assertGreaterEqual(temporal["occurrence_date_confidence"], 0.8)
        self.assertIn("investigación", temporal["occurrence_date_evidence"])

    def test_temporal_weekday_inference_uses_publication_anchor(self):
        temporal = event_temporal({"fecha": "2026-08-16", "titulo": "El operativo se realizó el viernes en Iquique."})
        self.assertEqual(temporal["occurrence_date_precision"], "INFERRED_DAY")
        self.assertEqual(temporal["occurrence_date_anchor"], "2026-08-14")
        self.assertEqual(temporal["occurrence_date_rule"], "WEEKDAY_FROM_PUBLICATION")

    def test_temporal_does_not_promote_generic_publication_year(self):
        temporal = event_temporal({"fecha": "2026-08-16", "titulo": "Informe publicado en agosto de 2026 analiza tendencias regulatorias."})
        self.assertEqual(temporal["occurrence_date_precision"], "UNKNOWN")

    def test_temporal_guardrail_and_contracts(self):
        bundle = transform(sample_payload(), retrieved_at="2026-08-16T12:00:00Z")
        self.assertEqual(len(bundle["documents"]), 3)
        event = bundle["events"][0]
        self.assertEqual(event["producer_id"], "radar_prensa")
        self.assertTrue(event["evidence_ids"])
        self.assertEqual(event["temporal"]["occurrence_date_precision"], "MONTH")
        self.assertEqual(event["temporal"]["publication_date"], "2026-08-15")
        self.assertTrue(event["sector_ids"])
        self.assertTrue(event["territory_ids"])
        self.assertTrue(bundle["temporal_assertions"])
        evidence = bundle["evidence"][0]
        self.assertEqual(len(evidence["content_sha256"]), 64)
        types = {e["entity_type"] for e in bundle["entities"]}
        self.assertIn("LEGAL_ENTITY", types)
        self.assertIn("PERSON", types)
        self.assertTrue(bundle["relationships"])

    def test_context_signals_are_not_aml_scores(self):
        bundle = transform(sample_payload(), retrieved_at="2026-08-16T12:00:00Z")
        signals = derive_context_signals(bundle)
        kinds = {s["signal_type"] for s in signals}
        self.assertIn("MEDIA_BURST", kinds)
        self.assertIn("SOURCE_CONVERGENCE", kinds)
        self.assertTrue(all(s["semantics"] == "CONTEXT_ONLY" for s in signals))
        media = next(s for s in signals if s["signal_type"] == "MEDIA_BURST")
        self.assertEqual(media["scope"]["time_basis"], "PUBLICATION_DATE")

    def test_longitudinal_detects_recurrence_momentum_and_clusters(self):
        bundle = transform(longitudinal_payload(), retrieved_at="2026-08-16T12:00:00Z")
        products = derive_longitudinal(bundle)
        self.assertEqual(products["analysis_window"]["baseline_quality"], "FULL")

        profile = next(r for r in products["entity_activity"] if r.get("canonical_name") == "Importadora Norte SpA")
        self.assertEqual(profile["recurrence_status"], "RECURRENT")
        self.assertGreaterEqual(profile["event_count"], 5)
        self.assertGreaterEqual(profile["source_count"], 5)

        phenomenon = next(r for r in products["phenomenon_windows"] if r["phenomenon"] == "contrabando")
        self.assertEqual(phenomenon["status"], "ELEVATED")
        self.assertTrue(phenomenon["signal_eligible"])
        self.assertEqual(phenomenon["recent_count"], 4)

        territorial = [r for r in products["territorial_windows"] if r["phenomenon"] == "contrabando" and r["recent_count"] >= 4]
        self.assertTrue(territorial)
        self.assertTrue(any(r["signal_eligible"] for r in territorial))

        clusters = [r for r in products["event_clusters"] if r["event_count"] >= 5]
        self.assertTrue(clusters)
        self.assertGreaterEqual(clusters[0]["source_count"], 5)

        kinds = {s["signal_type"] for s in products["signals"]}
        self.assertIn("ENTITY_RECURRENCE", kinds)
        self.assertIn("PHENOMENON_MOMENTUM", kinds)
        self.assertIn("TERRITORIAL_MOMENTUM", kinds)
        self.assertIn("CROSS_SOURCE_EVENT_CLUSTER", kinds)
        self.assertTrue(all(s["semantics"] == "CONTEXT_ONLY" for s in products["signals"]))

    def test_longitudinal_does_not_claim_emergence_without_baseline(self):
        bundle = transform(recent_only_payload(), retrieved_at="2026-08-16T12:00:00Z")
        products = derive_longitudinal(bundle)
        self.assertEqual(products["analysis_window"]["baseline_quality"], "INSUFFICIENT")
        phenomenon = next(r for r in products["phenomenon_windows"] if r["phenomenon"] == "contrabando")
        self.assertEqual(phenomenon["status"], "INSUFFICIENT_BASELINE")
        kinds = {s["signal_type"] for s in products["signals"]}
        self.assertNotIn("PHENOMENON_EMERGENCE", kinds)
        self.assertNotIn("PHENOMENON_MOMENTUM", kinds)
        self.assertNotIn("TERRITORIAL_MOMENTUM", kinds)

    def test_longitudinal_handles_same_day_repeated_entity(self):
        payload = longitudinal_payload()
        duplicate = dict(payload["prensa"][-1])
        duplicate["medio"] = "Medio E"
        duplicate["link"] = "https://example.com/longitudinal/recent-d-same-day"
        payload["prensa"].append(duplicate)
        bundle = transform(payload, retrieved_at="2026-08-16T12:00:00Z")
        products = derive_longitudinal(bundle)
        profile = next(r for r in products["entity_activity"] if r.get("canonical_name") == "Importadora Norte SpA")
        self.assertGreaterEqual(profile["event_count"], 6)
        self.assertEqual(profile["last_seen_publication"], "2026-08-16")

    def test_end_to_end(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = root / "monitor.json"
            source.write_text(json.dumps(longitudinal_payload()), encoding="utf-8")
            out = root / "exports"
            manifest = run(str(source), str(out))
            self.assertEqual(manifest["version"], "0.3.1")
            self.assertEqual(manifest["counts"]["events"], 6)
            self.assertEqual(manifest["quality"]["geography_catalog"]["communes"], 346)
            self.assertGreaterEqual(manifest["counts"]["longitudinal_signals"], 4)
            self.assertEqual(manifest["analysis"]["analysis_window"]["baseline_quality"], "FULL")
            for filename in (
                "events.jsonl", "temporal_assertions.jsonl", "relationships.jsonl",
                "entity_activity.jsonl", "phenomenon_windows.jsonl", "territorial_windows.jsonl",
                "event_clusters.jsonl", "signals.jsonl", "manifest.json",
            ):
                self.assertTrue((out / filename).exists(), filename)


if __name__ == "__main__":
    unittest.main()
