from __future__ import annotations

import unittest

from radar_prensa.importer import extract_records
from radar_prensa.longitudinal import derive_event_clusters, _stable_signal_phenomenon


def event(event_id: str, doc_id: str, day: str, entities: list[str], source: str = "Medio"):
    return {
        "event_id": event_id,
        "entity_ids": entities,
        "territory_ids": [],
        "evidence_ids": [f"evidence:{doc_id}"],
        "temporal": {"publication_date": day},
        "attributes": {
            "document_id": doc_id,
            "source_name": source,
            "phenomena": ["lavado_activos"],
        },
    }


def entity(entity_id: str, name: str, confidence: float = 0.90):
    return {
        "entity_id": entity_id,
        "canonical_name": name,
        "entity_type": "PERSON",
        "identity_confidence": confidence,
        "identity_method": "SOURCE_NATIVE",
        "rut_normalized": None,
    }


class LongitudinalHardeningTests(unittest.TestCase):
    def test_importer_dedupes_case_variant_url_alias(self):
        common = {
            "fecha": "2026-08-13",
            "medio": "SoyChile",
            "titulo": "Mismo artículo",
            "tema": "Mismo contenido",
        }
        payload = {
            "prensa": [
                {**common, "link": "https://soychile.cl/antofagasta/policial/2026/08/13/961233/noticia.html"},
                {**common, "link": "https://soychile.cl/Antofagasta/Policial/2026/08/13/961233/noticia.html"},
            ]
        }
        self.assertEqual(len(extract_records(payload)), 1)

    def test_cluster_does_not_bridge_transitively_across_different_anchors(self):
        core = [
            event("e1", "d1", "2026-08-10", ["A"], "Medio A"),
            event("e2", "d2", "2026-08-11", ["A", "B"], "Medio B"),
            event("e3", "d3", "2026-08-12", ["B"], "Medio C"),
        ]
        fillers = [
            event(f"f{i}", f"fd{i}", f"2026-07-{(i % 28) + 1:02d}", [], f"Filler {i % 5}")
            for i in range(47)
        ]
        bundle = {"entities": [entity("A", "Persona A"), entity("B", "Persona B")], "events": core + fillers}
        clusters = derive_event_clusters(bundle)
        event_sets = {tuple(row["event_ids"]) for row in clusters}
        self.assertIn(("e1", "e2"), event_sets)
        self.assertIn(("e2", "e3"), event_sets)
        self.assertNotIn(("e1", "e2", "e3"), event_sets)
        self.assertTrue(all(row["cluster_type"] == "STABLE_ENTITY_ANCHOR" for row in clusters))

    def test_hub_entity_cannot_create_supercluster(self):
        events = [event(f"e{i}", f"d{i}", f"2026-08-{(i % 15) + 1:02d}", ["HUB"], f"Medio {i % 4}") for i in range(20)]
        bundle = {"entities": [entity("HUB", "Entidad ubicua")], "events": events}
        self.assertEqual(derive_event_clusters(bundle), [])

    def test_cluster_event_ids_are_unique_and_share_is_bounded(self):
        bundle = {
            "entities": [entity("A", "Persona A")],
            "events": [
                event("e1", "d1", "2026-08-10", ["A"], "Medio A"),
                event("e2", "d2", "2026-08-11", ["A"], "Medio B"),
                event("e3", "d3", "2026-08-12", ["A"], "Medio C"),
                event("e4", "d4", "2026-08-13", [], "Medio D"),
                event("e5", "d5", "2026-08-14", [], "Medio E"),
                event("e6", "d6", "2026-08-15", [], "Medio F"),
                event("e7", "d7", "2026-08-16", [], "Medio G"),
                event("e8", "d8", "2026-08-16", [], "Medio H"),
                event("e9", "d9", "2026-08-16", [], "Medio I"),
                event("e10", "d10", "2026-08-16", [], "Medio J"),
                event("e11", "d11", "2026-08-16", [], "Medio K"),
                event("e12", "d12", "2026-08-16", [], "Medio L"),
                event("e13", "d13", "2026-08-16", [], "Medio M"),
                event("e14", "d14", "2026-08-16", [], "Medio N"),
                event("e15", "d15", "2026-08-16", [], "Medio O"),
                event("e16", "d16", "2026-08-16", [], "Medio P"),
                event("e17", "d17", "2026-08-16", [], "Medio Q"),
                event("e18", "d18", "2026-08-16", [], "Medio R"),
                event("e19", "d19", "2026-08-16", [], "Medio S"),
                event("e20", "d20", "2026-08-16", [], "Medio T"),
            ],
        }
        clusters = derive_event_clusters(bundle)
        self.assertTrue(clusters)
        for row in clusters:
            self.assertEqual(len(row["event_ids"]), len(set(row["event_ids"])))
            self.assertLessEqual(row["dataset_share_pct"], 15.0)

    def test_case_labels_are_not_promoted_as_governed_phenomena(self):
        self.assertTrue(_stable_signal_phenomenon("lavado_activos"))
        self.assertTrue(_stable_signal_phenomenon("investigacion_penal"))
        self.assertFalse(_stable_signal_phenomenon("sartor"))
        self.assertFalse(_stable_signal_phenomenon("din_123456"))


if __name__ == "__main__":
    unittest.main()
