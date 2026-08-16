from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from radar_prensa.geo_catalog import catalog_counts
from radar_prensa.geography import extract_territories
from radar_prensa.importer import extract_records
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

    def test_end_to_end(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = root / "monitor.json"
            source.write_text(json.dumps(sample_payload()), encoding="utf-8")
            out = root / "exports"
            manifest = run(str(source), str(out))
            self.assertEqual(manifest["version"], "0.2.0")
            self.assertEqual(manifest["counts"]["events"], 3)
            self.assertEqual(manifest["quality"]["geography_catalog"]["communes"], 346)
            self.assertGreaterEqual(manifest["counts"]["temporal_assertions"], 1)
            self.assertTrue((out / "events.jsonl").exists())
            self.assertTrue((out / "temporal_assertions.jsonl").exists())
            self.assertTrue((out / "relationships.jsonl").exists())
            self.assertTrue((out / "manifest.json").exists())


if __name__ == "__main__":
    unittest.main()
