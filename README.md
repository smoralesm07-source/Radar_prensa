# Radar Prensa · v0.2.1

Radar OSINT de prensa contextual para el ecosistema de radares AML/LA-FT. No reemplaza el **Monitor UAF**: transforma publicaciones ya detectadas y enriquecidas en memoria histórica interoperable para aportar contexto temporal, territorial, sectorial y relacional al **Intelligence Fusion Layer**.

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

El radar consume el `datos.json` enriquecido de `Monitor/monitor-state`. El Monitor conserva el discovery probado; Radar Prensa mantiene su propio modelo histórico y salidas.

## v0.2 — Cobertura territorial y Temporal Intelligence

La familia v0.2 incorpora:

- catálogo DPA versionado con 16 regiones, 56 provincias y 346 comunas;
- normalización de alias y jerarquía comuna/provincia → región;
- asociaciones territoriales con regla, origen y confianza;
- extracción temporal determinística desde texto;
- separación estricta entre fecha de publicación y fecha/período de ocurrencia;
- `temporal_assertions.jsonl` con evento, evidencia, regla, intervalo, precisión y confianza;
- métricas de cobertura territorial y temporal en `manifest.json`.

### Hardening v0.2.1

La auditoría de muestra de v0.2.0 detectó falsos positivos por homónimos. v0.2.1 endurece la resolución geográfica:

- un nombre del catálogo encontrado en texto **no se promueve sin contexto geográfico**;
- apellidos/nombres ya reconocidos como personas naturales no se convierten en comunas sin evidencia geográfica explícita;
- referencias subcomunales como `población San Gregorio` no se convierten en la comuna homónima;
- homónimos internacionales como `Florida` se bloquean cuando existe contexto de Estados Unidos;
- se mantiene `missing` cuando la evidencia no permite decidir con suficiente confianza.

Principio: **es preferible perder cobertura a inventar territorio**.

## Temporal Intelligence

Patrones iniciales admitidos:

- fecha exacta: `3 de mayo de 2024`, `03/05/2024`, `2024-05-03`;
- mes y año: `la investigación comenzó en noviembre de 2025`;
- semestre: `durante el primer semestre de 2025`;
- rango anual: `entre 2023 y 2024`;
- año: `durante 2024`;
- relativos: `ayer`, `anteayer`;
- día de semana retrospectivo: `el operativo se realizó el viernes`.

Las referencias relativas usan la fecha de publicación únicamente como **ancla**. Si no existe evidencia suficiente:

```text
occurrence_date_precision = UNKNOWN
```

No se sustituye por la fecha de publicación.

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

## Guardrails metodológicos

- Prensa es **evidencia secundaria y contexto**, no acreditación de un hecho.
- Fecha de publicación ≠ fecha de ocurrencia.
- Inferencias temporales conservan regla, evidencia, precisión y confianza.
- Mención, coaparición o proximidad territorial no atribuye conducta ni propaga riesgo AML.
- Jerarquía territorial no es relación entre entidades.
- Sólo se conservan relaciones entre entidades que el Monitor marcó como explícitas.
- `MEDIA_BURST`, `GEOGRAPHIC_CONCENTRATION` y `SOURCE_CONVERGENCE` son `CONTEXT_ONLY`.
- Un acontecimiento de prensa no equivale a hallazgo AML, delito, incumplimiento ni responsabilidad.

## Ejecución

```bash
PYTHONPATH=src python -m unittest discover -s tests -v
PYTHONPATH=src python -m radar_prensa.cli \
  --source https://raw.githubusercontent.com/smoralesm07-source/Monitor/monitor-state/datos.json \
  --output data/exports
```

## Automatización

`.github/workflows/radar.yml` ejecuta pruebas, reconstruye el snapshot desde `Monitor/monitor-state`, valida catálogo/productos y publica en `radar-state`. En pull requests construye y valida, pero no publica estado.

La actualización automática se mantiene cada tres horas y no requiere SMTP, secretos externos ni servidor.

## Próximos pasos

- v0.3: colectores propios de prensa manteniendo compatibilidad con Monitor;
- recurrencia longitudinal de entidades y emergencia de fenómenos;
- convergencia temporal-territorial con ventanas configurables;
- adaptador formal en Intelligence Fusion Layer cuando el contrato de Radar Prensa quede estabilizado.
