# Instituciones rectoras de protección/desarrollo social — 10 países

Última verificación: 23 de junio de 2026
Fuente principal: CEPAL — Red de Desarrollo Social de América Latina y el
Caribe (ReDeSoc), https://dds.cepal.org/redesoc/ministerios

| País | Institución(es) | Año de creación | Notas |
|---|---|---|---|
| Costa Rica | Ministerio de Desarrollo Humano e Inclusión Social (MDHIS) / Instituto Mixto de Ayuda Social (IMAS) | 2018 | El MDHIS es la cartera política; el IMAS es la institución ejecutora de programas. Ambos se incluyen en la búsqueda. |
| Cuba | Ministerio de Trabajo y Seguridad Social (MTSS) | 1994 | No existe un "ministerio de desarrollo social" separado; la seguridad social está integrada al ministerio de trabajo. |
| El Salvador | Ministerio de Trabajo y Previsión Social (MTPS) / Ministerio de Desarrollo Local (MINDEL) | — | El Salvador no tiene un ministerio de desarrollo social centralizado (no aparece en la tabla de CEPAL). Se usan las dos instituciones más relevantes al tema. |
| Guatemala | Ministerio de Desarrollo Social (MIDES) | 2012 | — |
| Haití | Ministerio de Asuntos Sociales y Trabajo (MAST) | 1983 | — |
| Honduras | Secretaría de Desarrollo Social | 2022 | El nombre exacto puede variar entre "Secretaría" y "Ministerio" según la fuente; verificar con el sitio oficial vigente. |
| México | Secretaría del Bienestar | 2018 | Antes llamada Secretaría de Desarrollo Social (SEDESOL) hasta 2018. |
| Nicaragua | Ministerio de la Familia, Adolescencia y Niñez (MIFAN) | 2007 | — |
| Panamá | Ministerio de Desarrollo Social (MIDES) / Caja de Seguro Social (CSS) | 2005 | El MIDES gestiona programas sociales; la CSS gestiona seguridad social/pensiones. Ambos relevantes al tema. |
| República Dominicana | Gabinete de Coordinación de Políticas Sociales | 2004 | Coordina el Sistema de Protección Social; el programa "Supérate" es su principal vehículo de transferencias condicionadas. |

## Cómo se usan estos nombres en el código

Viven en `scraper.py`, en el diccionario `INSTITUCIONES_PAIS`. Se combinan
con el nombre del país (operador OR) para anclar la búsqueda de SerpAPI a
ese país específico de forma más precisa que solo el nombre del país.

## Mantenimiento — cuándo revisar esta lista

Los nombres institucionales cambian con cada gobierno o reforma
administrativa (ejemplos históricos: Costa Rica cambió de nombre en 2018,
México en 2018, Argentina fusionó varios ministerios en 2023). Revisar:

1. Cada vez que el reporte generado muestre muy pocas o ninguna noticia
   para un país durante varios días seguidos (puede indicar que el
   nombre institucional cambió y la búsqueda ya no encuentra coincidencias).
2. Periódicamente (sugerido: cada 6 meses) contra la fuente de CEPAL:
   https://dds.cepal.org/redesoc/ministerios
3. Si una noticia real de algún país menciona un nombre institucional
   distinto al aquí registrado, actualizar `INSTITUCIONES_PAIS` en
   `scraper.py` con el nombre nuevo (se puede dejar el anterior también,
   por si vuelve a usarse en noticias retrospectivas).
