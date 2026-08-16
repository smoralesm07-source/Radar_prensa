# Radar Prensa · v0.1.0

Radar OSINT de prensa contextual para el ecosistema de radares AML/LA-FT. Su objetivo no es reemplazar el **Monitor UAF**, sino convertir publicaciones ya detectadas y clasificadas en objetos históricos interoperables que puedan aportar contexto temporal, territorial, sectorial y relacional al **Intelligence Fusion Layer**.

## Principio de arquitectura

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
                 \             /
                  \           /
               CONTEXT SIGNALS
                 |
                 v
        Intelligence Fusion Layer
```

La v0.1 consume el `datos.json` enriquecido de la rama operacional `monitor-state` del Monitor. Esto permite aprovechar inmediatamente los criterios, fuentes, deduplicación, clasificación, entidades, lugares y relaciones explícitas que ya funcionan, pero el modelo de almacenamiento y las salidas pertenecen a Radar Prensa.

## Guardrails metodológicos

- Una publicación de prensa es **evidencia secundaria y contexto**, no acreditación de un hecho.
- La fecha de publicación **no se transforma automáticamente en fecha de ocurrencia**.
- Una mención, coaparición o cercanía territorial no atribuye conducta ni propaga riesgo AML.
- Sólo se conservan relaciones que el Monitor marcó como explícitas en el texto.
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
- `signals.jsonl`
- `manifest.json`

`events`, `evidence` y `entities` respetan desde esta versión los campos obligatorios de los contratos canónicos equivalentes del Intelligence Fusion Layer.

## Temporalidad

Un artículo puede tener una fecha de publicación conocida y fecha de ocurrencia desconocida:

```json
{
  "occurrence_date_from": null,
  "occurrence_date_to": null,
  "occurrence_date_precision": "UNKNOWN",
  "occurrence_date_basis": "NO_EXPLICIT_OCCURRENCE_DATE",
  "publication_date": "2026-08-15"
}
```

Sólo un campo explícito de acontecimiento (`occurrence_date`, `fecha_hecho`, `fecha_evento`, `event_date`) promueve una fecha a `EXACT`.

## Ejecución

Sin instalar dependencias externas:

```bash
PYTHONPATH=src python -m unittest discover -s tests -v
PYTHONPATH=src python -m radar_prensa.cli --source https://raw.githubusercontent.com/smoralesm07-source/Monitor/monitor-state/datos.json --output data/exports
```

También se puede usar un `datos.json` local:

```bash
PYTHONPATH=src python -m radar_prensa.cli --source ./datos.json --output data/exports
```

## Automatización

`.github/workflows/radar.yml` ejecuta en cada cambio relevante de `main`, manualmente y cada tres horas:

1. pruebas unitarias sin dependencias externas;
2. importación del Monitor desde `monitor-state`;
3. transformación canónica;
4. validación básica de productos;
5. publicación del snapshot en la rama `radar-state`.

No requiere SMTP, secretos externos ni servidor.

## Alcance v0.1

Esta es una versión **adapter-first**. El Monitor continúa siendo el motor de descubrimiento probado. Radar Prensa ya crea memoria histórica estructurada e interoperable. Las siguientes versiones pueden incorporar colectores propios y desacoplar progresivamente el discovery sin duplicar de inmediato la lógica madura del Monitor.

### Próximos pasos previstos

- v0.2: inferencia temporal conservadora desde texto y evidencia de la regla utilizada;
- v0.2: catálogo territorial completo reutilizable del Monitor/Context Hub;
- v0.3: colectores propios de prensa, manteniendo compatibilidad con Monitor;
- v0.3: detección longitudinal de emergencia de fenómenos y recurrencia de entidades;
- adaptador formal en Intelligence Fusion Layer una vez estabilizado el contrato de Radar Prensa.
