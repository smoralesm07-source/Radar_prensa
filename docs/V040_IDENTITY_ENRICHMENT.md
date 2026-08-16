# Radar Prensa v0.4.0 · Identity Enrichment

## Objetivo

Resolver, de forma conservadora y trazable, parte de las entidades de prensa que actualmente sólo poseen identidad `SOURCE_NATIVE`, para que puedan interoperar con el Entity Hub del `Intelligence_Fusion_Layer` mediante RUT exacto.

La resolución de identidad **no convierte prensa en señal AML** y no atribuye conducta ilícita a una entidad.

## Fuentes habilitadas

v0.4 utiliza como referencia oficial el perfil público gobernado de `Radar_SII`, release `fusion-v1`, dataset `entity_search.parquet`.

Campos usados:

- `legal_name`;
- `rut`;
- `entity_id`.

No se utilizan actividad económica, ventas, trabajadores, territorio ni otras variables para resolver identidad.

## Regla de promoción

Una entidad de prensa sin RUT sólo pasa a `RUT_EXACT` si se cumplen simultáneamente:

1. es una entidad no-persona elegible (`LEGAL_ENTITY`, `OSFL` o `PUBLIC_BODY`);
2. posee nombre;
3. el nombre coincide exactamente después de una normalización determinística de mayúsculas, espacios y puntuación;
4. la coincidencia en SII conduce a **un único RUT válido**;
5. el RUT supera validación de dígito verificador chileno.

Si un mismo nombre oficial corresponde a más de un RUT, el resultado es `AMBIGUOUS` y no se resuelve.

No se habilita:

- fuzzy matching;
- distancia de Levenshtein;
- embeddings;
- coincidencia por comuna o región;
- coincidencia por actividad económica;
- co-mención;
- inferencia de grupo empresarial;
- selección arbitraria del primer resultado.

## Canonicalización para Entity Hub

Cuando una entidad queda resuelta, Radar Prensa deja de utilizar una clave local derivada del nombre y adopta directamente la misma clave global declarada por Radar SII:

`ENT-RUT-{RUT_NORMALIZADO}`

Ejemplo:

`76.123.456-0 -> ENT-RUT-761234560`

Esta decisión permite que `FusionStore` consolide la observación de prensa y la entidad SII en el **mismo nodo del Entity Hub**, en lugar de mantener dos nodos que sólo comparten RUT.

El remapeo se propaga a:

- eventos;
- menciones;
- enlaces evento-entidad;
- relaciones explícitas.

Si una entidad por nombre y una entidad extraída como RUT explícito terminan en el mismo RUT, ambas se consolidan antes de construir recurrencia, clusters y señales longitudinales.

## Producto de auditoría

Se publica `data/exports/identity_resolutions.jsonl`.

Cada intento contiene:

- ID antes y después;
- razón social de prensa;
- nombre normalizado;
- estado `RESOLVED`, `AMBIGUOUS` o `NO_MATCH`;
- RUT cuando corresponde;
- `global_entity_key` cuando la resolución es positiva;
- método de resolución;
- radar de referencia;
- release y digest del asset SII;
- cardinalidad del match;
- guardrail aplicable.

Este archivo es un producto analítico derivado de auditoría. No reemplaza evidencia primaria.

## Validación de RUT

v0.4 endurece también la extracción existente: un RUT proveniente del upstream o encontrado mediante regex sólo puede etiquetarse como `RUT_EXACT` si su dígito verificador es válido.

Todo RUT válido observado explícitamente utiliza inmediatamente la clave global `ENT-RUT-{RUT_NORMALIZADO}`. Los RUT inválidos se descartan como identidad exacta y quedan registrados como `invalid_rut_rejected` cuando provienen de una entidad estructurada del Monitor.

## GitHub Actions

En `pull_request`:

- no se descarga el perfil SII;
- se ejecutan tests determinísticos con fixtures;
- el manifest declara `NOT_RUN_NO_REFERENCE`.

En `push` a `main`, `schedule` y `workflow_dispatch`:

1. se consulta metadata del release `Radar_SII/fusion-v1`;
2. se construye una clave de caché con asset ID, fecha de actualización y digest;
3. se restaura el perfil desde `actions/cache`;
4. sólo si el asset cambió se descarga el ZIP público;
5. se extrae `entity_search.parquet`;
6. se ejecuta el enriquecimiento;
7. el snapshot final se publica en `radar-state`.

## Integración con Intelligence Fusion Layer v0.7

La salida esperada es:

```text
Radar Prensa SOURCE_NATIVE
        │
        ├── no match / ambiguo ──> permanece SOURCE_NATIVE
        │
        └── match SII exacto + único + RUT válido
                          │
                          ▼
                       RUT_EXACT
                          │
                          ▼
                  ENT-RUT-{RUT}
                          │
                          ▼
                     Entity Hub
                          │
                          ▼
              PRESS_ENTITY_CONVERGENCE
                          │
                          ▼
                 Analytical Workbench
```

El `Intelligence_Fusion_Layer` conserva sus propios guardrails: una entidad de prensa sólo puede generar convergencia estratégica de entidad cuando además existe una condición analítica independiente. La resolución de identidad por sí sola no genera finding ni score AML.
