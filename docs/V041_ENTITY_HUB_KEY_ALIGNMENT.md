# Radar Prensa v0.4.1 · alineación exacta de clave Entity Hub

## Corrección

La primera corrida productiva v0.4.0 confirmó que la resolución SII funcionaba, pero detectó una diferencia de representación entre productores:

- Radar Prensa: `ENT-RUT-70819400K`
- Radar SII: `ENT-RUT-70819400-K`

Ambos representan el mismo RUT, por lo que el Convergence Engine podía reconciliarlos normalizando el RUT. Sin embargo, `FusionStore` los mantenía como dos nodos distintos porque la clave `entity_id` no era idéntica.

v0.4.1 corrige la representación en origen.

## Política canónica

Todo RUT exacto se representa como:

- `rut_normalized = CUERPO-DV`
- `entity_id = ENT-RUT-CUERPO-DV`

Ejemplo:

- RUT: `70.819.400-K`
- `rut_normalized`: `70819400-K`
- `entity_id`: `ENT-RUT-70819400-K`

Cuando la identidad proviene del match contra `Radar_SII/fusion-v1`, Radar Prensa exige además que el `entity_id` de referencia publicado por SII coincida exactamente con la clave que deriva del RUT. Si no coincide, el pipeline falla en vez de inventar una equivalencia.

## Efecto

Con v0.4.1, la observación de prensa y la entidad SII se fusionan en el mismo nodo del Entity Hub. Esto evita:

- duplicación de entidades por formato de RUT;
- reconciliación tardía innecesaria;
- productores separados para un mismo sujeto canónico;
- ambigüedad en el handoff hacia Analytical Workbench.

El cambio no altera los guardrails de v0.4.0: un match de nombre sigue requiriendo coincidencia exacta, única, RUT válido y referencia SII trazable; prensa continúa siendo `CONTEXT_ONLY`.
