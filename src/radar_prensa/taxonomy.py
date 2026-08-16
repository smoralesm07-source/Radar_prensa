from __future__ import annotations

from typing import Any
from .utils import norm_text

# Taxonomía contextual, no constituye calificación penal ni AML.
PHENOMENA = {
    "lavado_activos": ["lavado de activos", "lavado de dinero", "blanqueo"],
    "financiamiento_terrorismo": ["financiamiento del terrorismo", "financiacion del terrorismo"],
    "corrupcion": ["corrupcion", "cohecho", "soborno", "malversacion", "fraude al fisco"],
    "contrabando": ["contrabando", "mercancia ilegal", "aduanero"],
    "narcotrafico": ["narcotrafico", "trafico de drogas", "droga incautada"],
    "trata_personas": ["trata de personas", "trafico de migrantes"],
    "crimen_organizado": ["crimen organizado", "organizacion criminal", "banda criminal"],
    "delitos_economicos": ["delitos economicos", "estafa", "fraude", "apropiacion indebida"],
    "evasion_tributaria": ["evasion tributaria", "delito tributario", "facturas falsas"],
    "sancion_regulatoria": ["sancion", "multa", "superintendencia", "resolucion sancionatoria"],
    "investigacion_penal": ["formalizacion", "imputado", "investigacion penal", "fiscalia", "ministerio publico"],
    "operativo_policial": ["operativo policial", "allanamiento", "detenidos", "pdi", "carabineros"],
}

NATURE = {
    "JUDICIAL": ["tribunal", "corte", "juzgado", "formalizacion", "sentencia", "audiencia"],
    "POLICIAL": ["pdi", "carabineros", "operativo", "allanamiento", "detenidos"],
    "REGULATORY": ["superintendencia", "sancion", "multa", "regulador"],
    "LEGISLATIVE": ["senado", "camara de diputados", "proyecto de ley"],
    "ECONOMIC": ["mercado", "industria", "banco", "inversion", "financiero"],
}


def classify_text(*values: Any) -> dict[str, Any]:
    text = norm_text(" ".join(str(v or "") for v in values))
    phenomena = []
    for code, needles in PHENOMENA.items():
        hits = [n for n in needles if norm_text(n) in text]
        if hits:
            phenomena.append({"code": code, "matched_terms": hits})
    nature = "OTHER"
    nature_hits: list[str] = []
    for code, needles in NATURE.items():
        hits = [n for n in needles if norm_text(n) in text]
        if hits:
            nature = code
            nature_hits = hits
            break
    uaf = "unidad de analisis financiero" in text or " uaf " in f" {text} "
    return {
        "phenomena": phenomena,
        "nature": nature,
        "nature_hits": nature_hits,
        "uaf_explicit_mention": uaf,
        "aml_context_relevance": bool(phenomena) or uaf,
    }
