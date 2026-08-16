# Radar Prensa · v0.3.0

Radar OSINT de prensa contextual y longitudinal para el ecosistema de radares AML/LA-FT. No reemplaza el **Monitor UAF**: transforma publicaciones ya detectadas y enriquecidas en memoria histórica interoperable para aportar contexto temporal, territorial, sectorial, relacional y longitudinal al **Intelligence Fusion Layer**.

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

La v0.3 incorpora una capa determinística para detectar **recurrencia, cambio y continuidad** en la memoria de prensa. No genera scores de delito ni de LA/FT.

### 1. Recurrencia de entidades

`entity_activity.jsonl` consolida para cada entidad:

- primera y última aparición por fecha de publicación;
- número de eventos, días activos y fuentes distintas;
- evolución mensual;
- fenómenos y territorios asociados;
- cobertura conocida de fecha de ocurrencia;
- eventos y evidencia que sustentan el perfil.

Una entidad se clasifica como `RECURRENT` cuando aparece en al menos **4 eventos**, **3 fechas distintas** y **2 fuentes**. Esta clasificación describe recurrencia periodística, no participación o responsabilidad.

### 2. Emergencia y momentum de fenómenos

`phenomenon_windows.jsonl` compara una ventana reciente de **7 días** con un baseline previo de **28 días**.

La ventana se ancla en la última fecha de publicación disponible en el snapshot, no en la hora del sistema, para que el cálculo sea reproducible.

Estados principales:

- `NEW_ACTIVITY`: actividad reciente con baseline suficientemente observado y sin antecedentes en la ventana basal;
- `ELEVATED`: actividad reciente materialmente superior a la tasa semanal basal;
- `STABLE`: sin cambio suficiente;
- `LOW_VOLUME`: volumen reciente insuficiente;
- `INSUFFICIENT_BASELINE`: no existe historia suficiente para afirmar emergencia o momentum.

Para emitir una señal longitudinal se exigen además **múltiples fuentes** y **al menos dos días activos**, evitando convertir republicaciones masivas de una misma noticia en una falsa tendencia.

### 3. Momentum temporal-territorial

`territorial_windows.jsonl` aplica la misma lógica a cada combinación `territorio + fenómeno` observada al menos dos veces.

Esto permite identificar preguntas como:

> ¿Aumentó recientemente la cobertura de contrabando asociada a una región o comuna respecto de su propio baseline?

La asociación territorial sigue siendo contextual: no acredita que todos los hechos hayan ocurrido allí ni que el territorio tenga mayor riesgo AML.

### 4. Clusters de acontecimientos

`event_clusters.jsonl` agrupa eventos cercanos en el tiempo cuando existen anclas compartidas suficientemente fuertes:

- entidad relevante compartida; o
- múltiples entidades compartidas; o
- territorio compartido junto con múltiples fenómenos comunes.

La distancia máxima entre publicaciones conectables es de **21 días**. El cluster conserva eventos, fuentes, entidades, territorios, fenómenos y evidencia.

Un cluster es una **hipótesis de continuidad analítica para revisión humana**. No fusiona automáticamente publicaciones en un único caso, investigación o red criminal.

## Time basis y baseline

La inteligencia longitudinal usa `PUBLICATION_DATE` como base temporal general. Esto es deliberado: la fecha de publicación tiene cobertura completa, mientras la fecha de ocurrencia sólo existe cuando la evidencia permite inferirla de forma trazable.

La fecha de ocurrencia se conserva como enriquecimiento y contexto histórico, pero no se utiliza para calcular el baseline general mientras su cobertura sea parcial.

Política v1.0:

```text
ventana reciente        = 7 días
baseline previo         = 28 días
mínimo baseline útil    = 14 días
mínimo para NEW_ACTIVITY= 21 días
recurrencia entidad     = 4 eventos + 3 fechas + 2 fuentes
máximo gap cluster      = 21 días
```

Las reglas y parámetros quedan registrados en `manifest.json`.

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
- `entity_activity.jsonl` **(v0.3)**
- `phenomenon_windows.jsonl` **(v0.3)**
- `territorial_windows.jsonl` **(v0.3)**
- `event_clusters.jsonl` **(v0.3)**
- `signals.jsonl`
- `manifest.json`

`events`, `evidence` y `entities` conservan compatibilidad con los campos obligatorios de los contratos canónicos equivalentes del Intelligence Fusion Layer.

## Signals v0.3

Se mantienen:

- `MEDIA_BURST`
- `GEOGRAPHIC_CONCENTRATION`
- `SOURCE_CONVERGENCE`

Se agregan:

- `ENTITY_RECURRENCE`
- `PHENOMENON_EMERGENCE`
- `PHENOMENON_MOMENTUM`
- `TERRITORIAL_MOMENTUM`
- `CROSS_SOURCE_EVENT_CLUSTER`

Todas las señales son `CONTEXT_ONLY`, conservan regla/ventana/métricas cuando corresponde y, en las señales longitudinales, referencias directas a `event_ids` y `evidence_ids`.

## Guardrails metodológicos

- Prensa es **evidencia secundaria y contexto**, no acreditación de un hecho.
- Fecha de publicación ≠ fecha de ocurrencia.
- Inferencias temporales conservan regla, evidencia, precisión y confianza.
- Mención, coaparición, recurrencia o proximidad territorial no atribuye conducta ni propaga riesgo AML.
- Jerarquía territorial no es relación entre entidades.
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

`.github/workflows/radar.yml` ejecuta pruebas, reconstruye el snapshot desde `Monitor/monitor-state`, valida los productos v0.3 y publica en `radar-state`. En pull requests construye y valida, pero no publica estado.

La actualización automática se mantiene cada tres horas y no requiere SMTP, secretos externos ni servidor.

## Próximos pasos

- auditar longitudinalmente el snapshot real y ajustar umbrales sólo con evidencia empírica;
- formalizar el adaptador de señales al **Signals Registry** del Intelligence Fusion Layer;
- incorporar en una versión posterior colectores propios de prensa manteniendo compatibilidad con Monitor;
- avanzar hacia deduplicación semántica/caso-evento sin perder trazabilidad de cada publicación.
