# Radar Prensa · v0.3.1

Radar OSINT de prensa contextual y longitudinal para el ecosistema de radares AML/LA-FT. No reemplaza el **Monitor UAF**: transforma publicaciones detectadas y enriquecidas en memoria histórica interoperable para aportar contexto temporal, territorial, sectorial, relacional y longitudinal al **Intelligence Fusion Layer**.

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
                    LONGITUDINAL ENGINE
                               |
                +--------------+----------------+
                |              |                |
         ENTITY ACTIVITY   PHENOMENON      EVENT CLUSTERS
                           / TERRITORY
                              WINDOWS
                \              |                /
                 +-------------+---------------+
                               |
                        CONTEXT SIGNALS
                               |
                               v
                    Intelligence Fusion Layer
```

El radar consume el `datos.json` enriquecido de `Monitor/monitor-state`. El Monitor conserva el discovery probado; Radar Prensa mantiene su propio modelo histórico, reglas analíticas y salidas.

## v0.3 — Inteligencia longitudinal

La familia v0.3 incorpora una capa determinística para detectar **recurrencia, cambio y continuidad** en la memoria de prensa. No genera scores de delito ni de LA/FT.

### 1. Recurrencia de entidades

`entity_activity.jsonl` consolida primera/última aparición, número de eventos, días activos, fuentes, evolución mensual, fenómenos, territorios y evidencia. Una entidad se clasifica como `RECURRENT` cuando aparece en al menos **4 eventos**, **3 fechas distintas** y **2 fuentes**. La clasificación describe recurrencia periodística, no participación o responsabilidad.

### 2. Emergencia y momentum de fenómenos

`phenomenon_windows.jsonl` compara una ventana reciente de **7 días** con un baseline previo de **28 días**. La ventana se ancla en la última fecha de publicación disponible para que el cálculo sea reproducible.

Estados principales: `NEW_ACTIVITY`, `ELEVATED`, `STABLE`, `LOW_VOLUME` e `INSUFFICIENT_BASELINE`. Para emitir una señal se exigen múltiples fuentes y al menos dos días activos. Desde v0.3.1, `PHENOMENON_EMERGENCE` y `PHENOMENON_MOMENTUM` sólo se emiten para la taxonomía gobernada `PHENOMENA`; etiquetas de caso o upstream se conservan como contexto, pero no se promueven a fenómeno emergente.

### 3. Momentum temporal-territorial

`territorial_windows.jsonl` aplica la misma lógica a cada combinación `territorio + fenómeno` observada al menos dos veces. La asociación territorial sigue siendo contextual: no acredita lugar de ocurrencia ni mayor riesgo AML del territorio.

### 4. Clusters de acontecimientos · hardening v0.3.1

`event_clusters.jsonl` usa `STABLE_ENTITY_ANCHOR`: un cluster sólo puede formarse alrededor de **la misma entidad ancla estable**. Se eliminó el bridging transitivo que podía unir casos sucesivamente mediante entidades diferentes.

Política de clustering v1.1:

- máximo gap entre publicaciones de una misma ancla: **21 días**;
- confianza mínima del ancla: **0,75**;
- una entidad presente en más del **10 %** del universo no actúa como ancla, evitando entidades-hub;
- ningún cluster puede superar el **15 %** del dataset;
- clusters con exactamente el mismo conjunto de eventos se consolidan;
- `event_ids` dentro de productos analíticos deben ser únicos.

Un cluster es una **hipótesis de continuidad analítica para revisión humana**. No fusiona automáticamente publicaciones en un único caso, investigación o red criminal.

### 5. Identidad de documentos e IDs · v0.3.1

El importador colapsa aliases del mismo artículo cuando coinciden simultáneamente URL normalizada, medio, título y fecha. Esto evita duplicados derivados, por ejemplo, de diferencias de mayúsculas/minúsculas en paths sin asumir que toda URL web sea globalmente case-insensitive. CI exige unicidad de `document_id` y `event_id` antes de publicar `radar-state`.

## Time basis y baseline

La inteligencia longitudinal usa `PUBLICATION_DATE` como base temporal general. La fecha de ocurrencia se conserva como enriquecimiento, pero no se utiliza para el baseline general mientras su cobertura sea parcial.

Política longitudinal v1.1:

```text
ventana reciente             = 7 días
baseline previo              = 28 días
mínimo baseline útil         = 14 días
mínimo para NEW_ACTIVITY     = 21 días
recurrencia entidad          = 4 eventos + 3 fechas + 2 fuentes
máximo gap cluster           = 21 días
máximo presencia ancla       = 10 % del universo
máximo tamaño cluster        = 15 % del universo
bridging transitivo cluster  = deshabilitado
```

Las reglas quedan registradas en `manifest.json`.

## Familia v0.2 — territorio y Temporal Intelligence

Se mantienen íntegramente:

- catálogo DPA versionado con 16 regiones, 56 provincias y 346 comunas;
- jerarquía comuna/provincia → región;
- hardening de homónimos y falsos positivos geográficos;
- extracción temporal determinística desde texto;
- separación fecha de publicación / fecha de ocurrencia;
- `temporal_assertions.jsonl` con regla, evidencia, intervalo, precisión y confianza.

Principio territorial: **es preferible perder cobertura a inventar territorio**.

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
- `entity_activity.jsonl`
- `phenomenon_windows.jsonl`
- `territorial_windows.jsonl`
- `event_clusters.jsonl`
- `signals.jsonl`
- `manifest.json`

`events`, `evidence` y `entities` conservan compatibilidad con los campos obligatorios de los contratos canónicos equivalentes del Intelligence Fusion Layer.

## Signals

Se mantienen `MEDIA_BURST`, `GEOGRAPHIC_CONCENTRATION` y `SOURCE_CONVERGENCE`. La familia v0.3 agrega `ENTITY_RECURRENCE`, `PHENOMENON_EMERGENCE`, `PHENOMENON_MOMENTUM`, `TERRITORIAL_MOMENTUM` y `CROSS_SOURCE_EVENT_CLUSTER`.

Todas las señales son `CONTEXT_ONLY`, conservan regla/ventana/métricas cuando corresponde y referencias a `event_ids` y `evidence_ids` en las señales longitudinales.

## Guardrails metodológicos

- Prensa es **evidencia secundaria y contexto**, no acreditación de un hecho.
- Fecha de publicación ≠ fecha de ocurrencia.
- Inferencias temporales conservan regla, evidencia, precisión y confianza.
- Mención, coaparición, recurrencia o proximidad territorial no atribuye conducta ni propaga riesgo AML.
- Sólo se conservan relaciones entre entidades que el Monitor marcó como explícitas.
- Momentum o emergencia = cambio de cobertura periodística, no aumento probado de incidencia delictual.
- Clustering = agrupación analítica para revisión, no consolidación automática de un caso.
- Un acontecimiento de prensa no equivale a hallazgo AML, delito, incumplimiento ni responsabilidad.

## Ejecución

```bash
PYTHONPATH=src python -m unittest discover -s tests -v
PYTHONPATH=src python -m radar_prensa.cli \
  --source https://raw.githubusercontent.com/smoralesm07-source/Monitor/monitor-state/datos.json \
  --output data/exports
```

## Automatización

`.github/workflows/radar.yml` ejecuta pruebas, reconstruye el snapshot desde `Monitor/monitor-state`, valida unicidad y guardrails v0.3.1 y publica en `radar-state`. En pull requests construye y valida, pero no publica estado. La actualización automática se mantiene cada tres horas y no requiere SMTP, secretos externos ni servidor.

## Próximos pasos

- seguir auditando umbrales longitudinales con evidencia empírica;
- formalizar el adaptador de señales al **Signals Registry** del Intelligence Fusion Layer;
- incorporar colectores propios de prensa manteniendo compatibilidad con Monitor;
- avanzar hacia deduplicación semántica/caso-evento sin perder trazabilidad de cada publicación.
