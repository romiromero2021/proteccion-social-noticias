"""
AGENTE 1 — Recolector de noticias (scraper.py)
================================================
Responsabilidad única: dado un país y un tema, consultar SerpAPI
(motor google_news) y devolver una lista de noticias crudas
(título, fuente, fecha, snippet, link), filtradas a la última semana
por defecto (ver parámetro rango_tiempo).

No interpreta ni resume nada — esa es responsabilidad del Agente 2.
"""

import requests
from datetime import datetime
from typing import List, Dict, Optional

SERPAPI_ENDPOINT = "https://serpapi.com/search"

PAISES = [
    "Costa Rica",
    "Cuba",
    "El Salvador",
    "Guatemala",
    "Haití",
    "Honduras",
    "México",
    "Nicaragua",
    "Panamá",
    "República Dominicana",
]

TEMA_BASE = "programas de protección social"


def construir_query(pais: str, tema: str = TEMA_BASE) -> str:
    """Construye la query de búsqueda para un país específico."""
    return f"{tema} {pais}"


def buscar_noticias_pais(
    pais: str,
    api_key: str,
    tema: str = TEMA_BASE,
    max_resultados: int = 8,
    rango_tiempo: str = "qdr:w",  # qdr:w = última semana (ver nota abajo)
) -> List[Dict]:
    """
    Busca noticias recientes para un país usando SerpAPI (motor google_news).

    Parameters
    ----------
    pais : nombre del país (se usa también para etiquetar resultados)
    api_key : tu API key de SerpAPI
    tema : tema de búsqueda (por defecto: programas de protección social)
    max_resultados : tope de noticias crudas a traer por país (se filtran
                      luego a 5 relevantes en el Agente 2)
    rango_tiempo : filtro temporal real, enviado a SerpAPI como parámetro
                   "tbs". Valores válidos: "qdr:d" (últimas 24h),
                   "qdr:w" (última semana, valor por defecto — un tema
                   institucional como este no siempre tiene noticias
                   nuevas cada 24h en los 10 países), "qdr:m" (mes).

    Returns
    -------
    Lista de dicts con keys: pais, titulo, fuente, fecha, snippet, link
    """
    query = construir_query(pais, tema)

    params = {
        "engine": "google_news",
        "q": query,
        "gl": _codigo_pais(pais),   # país de origen de la búsqueda
        "hl": "es",                 # idioma de resultados
        "tbs": rango_tiempo,        # filtro temporal real (antes no se enviaba)
        "api_key": api_key,
    }

    try:
        resp = requests.get(SERPAPI_ENDPOINT, params=params, timeout=20)
        resp.raise_for_status()
        data = resp.json()
    except requests.exceptions.RequestException as e:
        return [{"pais": pais, "error": f"Error de conexión con SerpAPI: {e}"}]

    if "error" in data:
        return [{"pais": pais, "error": data["error"]}]

    noticias_crudas = data.get("news_results", [])

    noticias = []
    for item in noticias_crudas[:max_resultados]:
        noticias.append({
            "pais": pais,
            "titulo": item.get("title", "Sin título"),
            "fuente": _extraer_fuente(item),
            "fecha": item.get("date", "Fecha no disponible"),
            "snippet": item.get("snippet", ""),
            "link": item.get("link", ""),
        })

    return noticias


def _extraer_fuente(item: Dict) -> str:
    """SerpAPI a veces anida la fuente en 'source': {'name': ...}."""
    source = item.get("source")
    if isinstance(source, dict):
        return source.get("name", "Fuente desconocida")
    return source or "Fuente desconocida"


def _codigo_pais(pais: str) -> str:
    """Mapea nombre de país a código ISO-2 para el parámetro 'gl' de SerpAPI."""
    mapa = {
        "Costa Rica": "cr",
        "Cuba": "cu",
        "El Salvador": "sv",
        "Guatemala": "gt",
        "Haití": "ht",
        "Honduras": "hn",
        "México": "mx",
        "Nicaragua": "ni",
        "Panamá": "pa",
        "República Dominicana": "do",
    }
    return mapa.get(pais, "us")


def recolectar_todas_las_noticias(
    api_key: str,
    paises: Optional[List[str]] = None,
    tema: str = TEMA_BASE,
    progress_callback=None,
) -> Dict[str, List[Dict]]:
    """
    Orquesta la recolección para todos los países.

    progress_callback: función opcional callback(pais_actual, indice, total)
                        útil para mostrar progreso en Streamlit.

    Returns
    -------
    Dict {pais: [lista de noticias]}
    """
    paises = paises or PAISES
    resultados = {}

    for i, pais in enumerate(paises):
        if progress_callback:
            progress_callback(pais, i + 1, len(paises))

        resultados[pais] = buscar_noticias_pais(pais, api_key, tema)

    return resultados


if __name__ == "__main__":
    # Prueba rápida desde línea de comandos / Colab
    import json
    import os

    key = os.environ.get("SERPAPI_KEY", "TU_API_KEY_AQUI")
    resultado = buscar_noticias_pais("Costa Rica", key)
    print(json.dumps(resultado, indent=2, ensure_ascii=False))
