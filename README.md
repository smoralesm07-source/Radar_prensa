# Radar Prensa · v0.2.0

Radar OSINT de prensa contextual para el ecosistema de radares AML/LA-FT. Su objetivo no es reemplazar el **Monitor UAF**, sino convertir publicaciones ya detectadas y clasificadas en objetos históricos interoperables que aporten contexto temporal, territorial, sectorial y relacional al **Intelligence Fusion Layer**.

## Arquitectura

```text
Monitor UAF (detección / alerta / dashboard)
                 |
                 v
        Radar Prensa Adapter
                 |
                 v
DOCUMENT -> EVIDENCE -> PRESS_CONTEXT_EVENT
                 |             |
              ENTITY        TERRITORY
                 |             |
                 |        16 REGIONES
                 |        56 PROVINCIAS
                 |       346 COMUNAS
                 |             |
                 +------ TEMPORAL ASSERTION
                               |
                               v
                       CONTEXT SIGNALS
                               |
                               v
                    Intelligence Fusion Layer
```

Radar Prensa consume el `datos.json` enriquecido de la rama operacional `monitor-state` del Monitor. Esto permite aprovechar los criterios, fuentes, deduplicación, clasificación, entidades, lugares y relaciones explícitas que ya funcionan, pero el modelo histórico y las salidas pertenecen a Radar Prensa.

## Novedades v0.2

### 1. Cobertura territorial completa

La v0.2 incorpora un catálogo DPA versionado dentro del radar con:

- 16 regiones;
- 56 provincias;
- 346 comunas.

El catálogo se deriva de la capa geográfica ya probada en Monitor, pero se copia dentro de Radar Prensa para mantener independencia en tiempo de ejecución.

El motor:

- normaliza nombres y alias regionales;
- recupera nivel administrativo desde el catálogo cuando el Monitor entrega una mención genérica;
- busca topónimos también en título, resumen y texto enriquecido;
- prioriza coincidencias largas para evitar solapamientos (`San Pedro de Atacama` antes que `San Pedro`);
- exige contexto geográfico para nombres especialmente ambiguos;
- conserva la región padre de comunas y provincias;
- agrega la región padre como territorio derivado para facilitar consultas regionales;
- mantiene `match_rule`, origen y confianza de la asociación territorial.

Ejemplo:

```json
{
  "name": "General Lagos",
  "administrative_level": "COMUNA",
  "region": "Arica y Parinacota",
  "parent_region_id": "territory:cl:region:arica-y-parinacota",
  "match_rule": "PLACE_PREPOSITION",
  "origin": "text_catalog_v0.2"
}
```

### 2. Temporal Intelligence conservadora

La fecha de publicación sigue separada de la fecha de ocurrencia. La v0.2 puede extraer de forma determinística referencias temporales desde el texto cuando aparecen asociadas a lenguaje de acontecimiento.

Patrones admitidos inicialmente:

- fecha exacta: `3 de mayo de 2024`, `03/05/2024`, `2024-05-03`;
- mes y año: `la investigación comenzó en noviembre de 2025`;
- semestre: `durante el primer semestre de 2025`;
- rango anual: `entre 2023 y 2024`;
- año: `durante 2024`;
- relativos: `ayer`, `anteayer`;
- día de semana retrospectivo: `el operativo se realizó el viernes`.

Las referencias relativas usan la fecha de publicación como **ancla**, no como fecha del hecho.

Cada inferencia conserva:

```text
occurrence_date_from
occurrence_date_to
occurrence_date_anchor
occurrence_date_precision
occurrence_date_basis
occurrence_date_rule
occurrence_date_confidence
occurrence_date_evidence
publication_date
```

Ejemplo:

```json
{
  "occurrence_date_from": "2025-11-01",
  "occurrence_date_to": "2025-11-30",
  "occurrence_date_anchor": null,
  "occurrence_date_precision": "MONTH",
  "occurrence_date_basis": "ARTICLE_TEXT",
  "occurrence_date_rule": "MONTH_YEAR_WITH_EVENT_CUE",
  "occurrence_date_confidence": 0.84,
  "occurrence_date_evidence": "La investigación comenzó en noviembre de 2025...",
  "publication_date": "2026-08-16"
}
```

Si no existe evidencia temporal suficiente, permanece:

```text
occurrence_date_precision = UNKNOWN
```

No se reemplaza por la fecha de publicación.

### 3. Temporal assertions trazables

Las inferencias temporales materializadas se exportan además en:

`temporal_assertions.jsonl`

Cada fila vincula:

`event -> document -> evidence -> regla -> extracto -> intervalo -> confianza`

Esto permite al Fusion Layer utilizar el contexto temporal sin perder la capacidad de auditar cómo fue obtenido.

### 4. Métricas de calidad

`manifest.json` incorpora ahora:

- cobertura territorial de eventos;
- cobertura de fecha/período de ocurrencia;
- distribución por precisión temporal;
- validación del tamaño del catálogo geográfico.

La ausencia de territorio o temporalidad sigue tratándose como **missing**, no como cero.

## Guardrails metodológicos

- Una publicación de prensa es **evidencia secundaria y contexto**, no acreditación de un hecho.
- La fecha de publicación **no se transforma automáticamente en fecha de ocurrencia**.
- Las inferencias temporales conservan regla, evidencia, precisión y confianza.
- Una mención, coaparición o cercanía territorial no atribuye conducta ni propaga riesgo AML.
- La relación comuna/provincia → región es jerarquía geográfica, no relación entre entidades.
- Sólo se conservan relaciones entre entidades que el Monitor marcó como explícitas en el texto.
- `MEDIA_BURST`, `GEOGRAPHIC_CONCENTRATION` y `SOURCE_CONVERGENCE` son señales `CONTEXT_ONLY`.
- `uaf_explicit_mention` y `aml_context_relevance` son dimensiones separadas.
- Un acontecimiento de prensa no equivale a hallazgo AML, delito, incumplimiento ni responsabilidad.

## Productos

Cada corrida genera en `data/exports/`:

- `documents.jsonl`
- `events.jsonl`
- `evidence.jsonl`
- `entities.jsonl`
- `territories.jsonl`
- `entity_mentions.jsonl`
- `event_entities.jsonl`
- `event_territories.jsonl`
- `relationships.jsonl`
- `sectors.jsonl`
- `temporal_assertions.jsonl`
- `signals.jsonl`
- `manifest.json`

`events`, `evidence` y `entities` conservan compatibilidad con los campos obligatorios de los contratos canónicos equivalentes del Intelligence Fusion Layer.

## Ejecución

Sin dependencias Python externas:

```bash
PYTHONPATH=src python -m unittest discover -s tests -v
PYTHONPATH=src python -m radar_prensa.cli --source https://raw.githubusercontent.com/smoralesm07-source/Monitor/monitor-state/datos.json --output data/exports
```

También se puede usar un `datos.json` local.

## Automatización

`.github/workflows/radar.yml` ejecuta:

1. pruebas unitarias;
2. importación desde `Monitor/monitor-state`;
3. transformación v0.2;
4. validación de catálogo, temporalidad y productos;
5. publicación del snapshot en `radar-state`.

En pull requests se ejecutan pruebas y construcción completa, pero **no se publica `radar-state`**. La publicación de estado ocurre solamente desde `main`, ejecución programada o ejecución manual.

La actualización automática se mantiene cada tres horas y no requiere SMTP, secretos externos ni servidor.

## Alcance

La v0.2 continúa siendo **adapter-first**: Monitor sigue siendo el motor de discovery probado y Radar Prensa construye la memoria histórica estructurada. El siguiente salto natural es incorporar colectores propios y señales longitudinales, manteniendo este contrato temporal/territorial como base estable.

### Próximos pasos previstos

- v0.3: colectores propios de prensa, manteniendo compatibilidad con Monitor;
- v0.3: recurrencia longitudinal de entidades y emergencia de fenómenos;
- detección de convergencia temporal-territorial con ventanas configurables;
- adaptador formal en Intelligence Fusion Layer una vez estabilizado el contrato de Radar Prensa.
