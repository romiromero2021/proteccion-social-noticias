"""
SECCIÓN REGIONAL: CEPAL / ReDeSoc
=================================

Define la sección del reporte dedicada a lo que publica la propia
CEPAL sobre desarrollo y protección social en la región, en vez de
depender de que la prensa nacional la cite.

HISTORIA DE ESTE MÓDULO (importa para no repetir el camino)
-----------------------------------------------------------
Intento 1 — la palabra "CEPAL" en los términos de búsqueda. No podía
funcionar: la capa 1 restringe con site: a medios de prensa
nacionales, y cepal.org no está —ni puede estar— en la lista de ningún
país, porque es un organismo regional. En la capa 2 se buscaba como
frase exacta, que no aparece literalmente en ningún titular.

Intento 2 — leer los feeds RSS de ReDeSoc (la Red de Desarrollo Social
de la CEPAL). Era la vía ideal: gratis, ya curada por la propia
División de Desarrollo Social, sin gastar cuota de SerpAPI. **Pero los
feeds están rotos del lado de la CEPAL**: verificado el 29-sep-2026,
tanto https://dds.cepal.org/redesoc/rss/redesoc-rss.php como
.../redesoc-proteccionsocial.php devuelven error HTTP 500. El reporte
de ese día salió con la sección vacía por ese motivo.

Intento 3 — el actual: buscar con SerpAPI restringido a los dominios
de la CEPAL, exactamente igual que se hace con los medios curados de
cada país. Es más pobre que el RSS (depende de lo que Google haya
indexado y gasta 1 búsqueda por reporte), pero usa maquinaria que ya
está probada en producción para los otros 10 países, en vez de un
camino propio que solo falla en silencio.

Si algún día los feeds vuelven a responder, conviene reconsiderarlo:
la página de referencia es https://dds.cepal.org/redesoc/noticias y
ahí se listan los canales temáticos.

QUÉ ENTRA EN ESTA SECCIÓN
-------------------------
Todo lo que publique la CEPAL sobre el tema y sea relevante para la
subregión, **incluidas las notas sobre los 10 países**. No se excluyen
las de países concretos: una nota de la CEPAL sobre Honduras es
material de la CEPAL y es justo lo que esta sección debe mostrar. Por
eso, para esta sección, los filtros de país cruzado no se aplican (ver
_buscar_una_vez en scraper.py): aquí mencionar a Honduras no es ruido,
es el contenido.

Prueba rápida de la búsqueda, sin tocar la app:

    export SERPAPI_KEY="tu_key"
    python3 cepal.py
"""

from typing import List

# Nombre de la sección en el reporte. Se usa como si fuera un "país"
# más, para que el resto de la app (pestañas, caché, documento Word)
# la trate sin cambios estructurales.
SECCION_CEPAL = "CEPAL (regional)"

# Dominios de la CEPAL. Se registran en SITIOS_PAIS bajo la clave de
# la sección, así que el operador site: y el reconocimiento de "medio
# curado" funcionan igual que con la prensa nacional.
SITIOS_CEPAL = [
    "cepal.org",       # sitio institucional (incluye www.cepal.org)
    "dds.cepal.org",   # División de Desarrollo Social y ReDeSoc
]

# Términos temáticos de la sección. Más amplios que los de los países,
# porque aquí no hay que acotar a un territorio: interesa la
# producción de la CEPAL sobre el tema, sea de un país o regional.
TERMINOS_CEPAL = [
    "protección social",
    "desarrollo social",
    "seguridad social",
    "pobreza",
    "transferencias monetarias",
    "políticas sociales",
]

# Página de referencia de ReDeSoc, para citarla en la interfaz.
URL_REDESOC = "https://dds.cepal.org/redesoc/noticias"


def construir_query_cepal(terminos: List[str] = None) -> str:
    """
    Query para la sección regional: términos temáticos con OR,
    restringidos a los dominios de la CEPAL.
    """
    terminos = terminos or TERMINOS_CEPAL
    terminos_con_or = " OR ".join(f'"{t}"' for t in terminos)
    sitios_con_or = " OR ".join(f"site:{s}" for s in SITIOS_CEPAL)
    return f"({terminos_con_or}) ({sitios_con_or})"


if __name__ == "__main__":
    import json
    import os
    import sys

    api_key = os.environ.get("SERPAPI_KEY")
    if not api_key:
        sys.exit("Falta la variable de entorno SERPAPI_KEY.")

    from scraper import buscar_noticias_pais

    print(f"Query: {construir_query_cepal()}\n")
    resultado = buscar_noticias_pais(SECCION_CEPAL, api_key, n_noticias_necesarias=5)

    if resultado.get("error"):
        sys.exit(f"Error de búsqueda: {resultado['error']}")

    aceptadas = resultado["aceptadas"]
    print(f"{len(aceptadas)} noticia(s) aceptada(s):\n")
    for noticia in aceptadas:
        print(f"  [{noticia.get('fecha','s/f')}] {noticia['titulo'][:95]}")
        print(f"      {noticia['link']}")
    print(f"\n{len(resultado['descartadas_marginales'])} marginal(es) para el verificador.")
