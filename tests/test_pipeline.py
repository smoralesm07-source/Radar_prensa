from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from radar_prensa.importer import extract_records
from radar_prensa.pipeline import derive_context_signals, run, transform


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
                "tema": "Investigación penal y contrabando", "link": "https://example.com/a?utm_source=x",
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

    def test_temporal_guardrail_and_contracts(self):
        bundle = transform(sample_payload(), retrieved_at="2026-08-16T12:00:00Z")
        self.assertEqual(len(bundle["documents"]), 3)
        event = bundle["events"][0]
        self.assertEqual(event["producer_id"], "radar_prensa")
        self.assertTrue(event["evidence_ids"])
        self.assertEqual(event["temporal"]["occurrence_date_precision"], "UNKNOWN")
        self.assertEqual(event["temporal"]["publication_date"], "2026-08-15")
        self.assertTrue(event["sector_ids"])
        self.assertTrue(event["territory_ids"])
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

    def test_end_to_end(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = root / "monitor.json"
            source.write_text(json.dumps(sample_payload()), encoding="utf-8")
            out = root / "exports"
            manifest = run(str(source), str(out))
            self.assertEqual(manifest["counts"]["events"], 3)
            self.assertTrue((out / "events.jsonl").exists())
            self.assertTrue((out / "relationships.jsonl").exists())
            self.assertTrue((out / "manifest.json").exists())


if __name__ == "__main__":
    unittest.main()
