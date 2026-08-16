from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from radar_prensa.entities import extract_entities
from radar_prensa.identity_enrichment import (
    canonical_rut,
    enrich_bundle_from_rows,
    enrich_bundle_with_sii,
    global_rut_entity_id,
    normalize_rut,
    valid_chilean_rut,
)
from radar_prensa.utils import stable_id


class IdentityEnrichmentTests(unittest.TestCase):
    def test_chilean_rut_validation(self):
        self.assertEqual(normalize_rut("76.123.456-0"), "761234560")
        self.assertEqual(canonical_rut("76.123.456-0"), "76123456-0")
        self.assertTrue(valid_chilean_rut("76.123.456-0"))
        self.assertFalse(valid_chilean_rut("76.123.456-7"))
        self.assertEqual(global_rut_entity_id("76.123.456-0"), "ENT-RUT-76123456-0")

    def test_invalid_upstream_rut_is_not_exact_identity(self):
        rows = extract_entities(
            {
                "nomina_entidades": [
                    {
                        "entidad_id": "UP-1",
                        "nombre": "Importadora Norte SpA",
                        "tipo": "EMPRESA",
                        "naturaleza": "PERSONA_JURIDICA",
                        "rut": "76.123.456-7",
                    }
                ]
            },
            "EVD-1",
        )
        self.assertEqual(len(rows), 1)
        self.assertIsNone(rows[0]["rut_normalized"])
        self.assertEqual(rows[0]["identity_method"], "SOURCE_NATIVE")
        self.assertEqual(rows[0]["attributes"]["invalid_rut_rejected"], "761234567")

    def test_valid_upstream_rut_uses_global_entity_key(self):
        rows = extract_entities(
            {
                "nomina_entidades": [
                    {
                        "entidad_id": "UP-1",
                        "nombre": "Importadora Norte SpA",
                        "tipo": "EMPRESA",
                        "naturaleza": "PERSONA_JURIDICA",
                        "rut": "76.123.456-0",
                    }
                ]
            },
            "EVD-1",
        )
        self.assertEqual(rows[0]["entity_id"], "ENT-RUT-76123456-0")
        self.assertEqual(rows[0]["rut_normalized"], "76123456-0")
        self.assertEqual(rows[0]["identity_method"], "RUT_EXACT")

    def test_unique_official_name_match_promotes_and_remaps_identity(self):
        name_id = stable_id("entity:press", "Importadora Norte SpA")
        rut_id = "ENT-RUT-76123456-0"
        person_id = stable_id("entity:press", "Persona Uno")
        bundle = {
            "entities": [
                {
                    "entity_id": name_id,
                    "entity_type": "LEGAL_ENTITY",
                    "canonical_name": "Importadora Norte SpA",
                    "rut_normalized": None,
                    "aliases": [],
                    "roles": ["PRESS_MENTION"],
                    "producer_ids": ["radar_prensa"],
                    "evidence_ids": ["EVD-A"],
                    "identity_method": "SOURCE_NATIVE",
                    "identity_confidence": 0.9,
                    "attributes": {},
                },
                {
                    "entity_id": rut_id,
                    "entity_type": "UNKNOWN",
                    "canonical_name": None,
                    "rut_normalized": "76123456-0",
                    "aliases": [],
                    "roles": ["PRESS_MENTION"],
                    "producer_ids": ["radar_prensa"],
                    "evidence_ids": ["EVD-B"],
                    "identity_method": "RUT_EXACT",
                    "identity_confidence": 1.0,
                    "attributes": {},
                },
                {
                    "entity_id": person_id,
                    "entity_type": "PERSON",
                    "canonical_name": "Persona Uno",
                    "rut_normalized": None,
                    "aliases": [],
                    "roles": ["PRESS_MENTION"],
                    "producer_ids": ["radar_prensa"],
                    "evidence_ids": ["EVD-A"],
                    "identity_method": "SOURCE_NATIVE",
                    "identity_confidence": 0.9,
                    "attributes": {},
                },
            ],
            "events": [{"event_id": "EVT-1", "entity_ids": [name_id, rut_id, person_id]}],
            "entity_mentions": [
                {"mention_id": "M1", "document_id": "DOC-1", "entity_id": name_id, "evidence_id": "EVD-A"},
                {"mention_id": "M2", "document_id": "DOC-1", "entity_id": rut_id, "evidence_id": "EVD-A"},
            ],
            "event_entities": [
                {"event_id": "EVT-1", "entity_id": name_id, "evidence_id": "EVD-A"},
                {"event_id": "EVT-1", "entity_id": rut_id, "evidence_id": "EVD-A"},
            ],
            "relationships": [
                {
                    "relationship_id": "REL-OLD",
                    "event_id": "EVT-1",
                    "source_entity_id": name_id,
                    "target_entity_id": person_id,
                    "relationship_type": "TRANSACCION_ENTRE",
                    "evidence_ids": ["EVD-A"],
                }
            ],
        }
        stats = enrich_bundle_from_rows(
            bundle,
            [
                {
                    "entity_id": "ENT-RUT-76123456-0",
                    "rut": "76123456-0",
                    "legal_name": "IMPORTADORA NORTE SPA",
                }
            ],
            {"release_tag": "fusion-v1", "asset_digest": "sha256:test"},
        )

        self.assertEqual(stats["resolved"], 1)
        self.assertEqual(stats["ambiguous"], 0)
        self.assertEqual(stats["global_entity_key_policy"], "ENT-RUT-{RUT_CANONICO_CON_GUION}")
        resolved = next(row for row in bundle["entities"] if row.get("rut_normalized") == "76123456-0")
        self.assertEqual(resolved["entity_id"], rut_id)
        self.assertEqual(resolved["identity_method"], "RUT_EXACT")
        self.assertEqual(resolved["canonical_name"], "Importadora Norte SpA")
        self.assertEqual(set(resolved["evidence_ids"]), {"EVD-A", "EVD-B"})
        self.assertEqual(bundle["events"][0]["entity_ids"], sorted({rut_id, person_id}))
        self.assertEqual(len(bundle["entity_mentions"]), 1)
        self.assertEqual(bundle["relationships"][0]["source_entity_id"], rut_id)
        resolution = bundle["identity_resolutions"][0]
        self.assertEqual(resolution["status"], "RESOLVED")
        self.assertEqual(resolution["global_entity_key"], rut_id)
        self.assertEqual(resolution["rut_normalized"], "76123456-0")
        self.assertEqual(resolution["reference_asset_digest"], "sha256:test")

    def test_duckdb_parquet_path_matches_production_shape(self):
        import duckdb

        name_id = stable_id("entity:press", "Importadora Norte SpA")
        bundle = {
            "entities": [
                {
                    "entity_id": name_id,
                    "entity_type": "LEGAL_ENTITY",
                    "canonical_name": "Importadora Norte SpA",
                    "rut_normalized": None,
                    "aliases": [],
                    "roles": ["PRESS_MENTION"],
                    "producer_ids": ["radar_prensa"],
                    "evidence_ids": ["EVD-A"],
                    "identity_method": "SOURCE_NATIVE",
                    "identity_confidence": 0.9,
                    "attributes": {},
                }
            ],
            "events": [{"event_id": "EVT-1", "entity_ids": [name_id]}],
            "entity_mentions": [],
            "event_entities": [],
            "relationships": [],
        }
        with tempfile.TemporaryDirectory() as td:
            parquet = Path(td) / "entity_search.parquet"
            con = duckdb.connect()
            try:
                target = str(parquet).replace("'", "''")
                con.execute(
                    f"COPY (SELECT 'ENT-RUT-76123456-0' AS entity_id, '76123456-0' AS rut, "
                    f"'IMPORTADORA NORTE SPA' AS legal_name) TO '{target}' (FORMAT PARQUET)"
                )
            finally:
                con.close()

            stats = enrich_bundle_with_sii(bundle, parquet)

        self.assertEqual(stats["status"], "ACTIVE")
        self.assertEqual(stats["resolved"], 1)
        self.assertEqual(bundle["entities"][0]["entity_id"], "ENT-RUT-76123456-0")
        self.assertEqual(bundle["entities"][0]["rut_normalized"], "76123456-0")
        self.assertEqual(bundle["identity_resolutions"][0]["status"], "RESOLVED")

    def test_ambiguous_official_name_does_not_promote(self):
        name_id = stable_id("entity:press", "Servicios del Norte SpA")
        bundle = {
            "entities": [
                {
                    "entity_id": name_id,
                    "entity_type": "LEGAL_ENTITY",
                    "canonical_name": "Servicios del Norte SpA",
                    "rut_normalized": None,
                    "aliases": [],
                    "roles": ["PRESS_MENTION"],
                    "producer_ids": ["radar_prensa"],
                    "evidence_ids": ["EVD-A"],
                    "identity_method": "SOURCE_NATIVE",
                    "identity_confidence": 0.9,
                    "attributes": {},
                }
            ],
            "events": [],
            "entity_mentions": [],
            "event_entities": [],
            "relationships": [],
        }
        stats = enrich_bundle_from_rows(
            bundle,
            [
                {"entity_id": "ENT-RUT-76123456-0", "rut": "76123456-0", "legal_name": "Servicios del Norte SpA"},
                {"entity_id": "ENT-RUT-76543210-3", "rut": "76543210-3", "legal_name": "SERVICIOS DEL NORTE SPA"},
            ],
        )
        self.assertEqual(stats["resolved"], 0)
        self.assertEqual(stats["ambiguous"], 1)
        self.assertEqual(bundle["entities"][0]["identity_method"], "SOURCE_NATIVE")
        self.assertIsNone(bundle["entities"][0]["rut_normalized"])
        self.assertEqual(bundle["identity_resolutions"][0]["status"], "AMBIGUOUS")
        self.assertIsNone(bundle["identity_resolutions"][0]["global_entity_key"])


if __name__ == "__main__":
    unittest.main()
