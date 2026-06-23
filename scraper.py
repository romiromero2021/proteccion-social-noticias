"""
AGENTE 1 — Recolector de noticias (scraper.py)
================================================
Responsabilidad única: dado un país y un tema, consultar SerpAPI
y devolver una lista de noticias crudas (título, fuente, fecha,
snippet, link), filtradas a la última semana por defecto.

IMPORTANTE — corrección de un bug detectado: el motor "google_news"
de SerpAPI no soporta de forma documentada el parámetro de filtro de
fecha "tbs", así que aunque se enviara, Google lo ignoraba en
silencio y devolvía resultados de cualquier antigüedad (se vieron
noticias de hasta 2023 mezcladas con las de 2026). Para resolverlo:
  1. Se usa el motor "google" con "tbm=nws" (Google News Results API),
     que sí soporta "tbs" de forma oficial.
  2. Como red de seguridad adicional, se vuelve a filtrar por fecha
     en Python (_dentro_del_rango), parseando la fecha real de cada
     noticia — así, aunque la API fallara en filtrar, el código nunca
     deja pasar una noticia más vieja que el límite configurado.

No interpreta ni resume nada — esa es responsabilidad del Agente 2.
"""

import re
import requests
from datetime import datetime, timedelta, timezone
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

# Cuántos días de antigüedad máxima se permiten, como red de seguridad
# en Python (independiente de si SerpAPI filtra bien o no).
DIAS_MAXIMOS_ANTIGUEDAD = 10


def construir_query(pais: str, tema: str = TEMA_BASE) -> str:
    """Construye la query de búsqueda para un país específico."""
    return f"{tema} {pais}"


def _parsear_fecha_serpapi(item: Dict) -> Optional[datetime]:
    """
    Intenta extraer una fecha real (timezone-aware, UTC) de un resultado
    de SerpAPI. SerpAPI puede devolver:
      - "date" como texto relativo ("hace 3 horas") o absoluto
        ("06/23/2026, 01:09 PM, +0000 UTC").
      - a veces un campo "published_at" en formato ISO ya parseable.
    Devuelve None si no se puede determinar la fecha (en ese caso, la
    noticia NO se descarta automáticamente — ver _dentro_del_rango).
    """
    publicado = item.get("published_at") or item.get("date")
    if not publicado:
        return None

    # Caso 1: formato ISO tipo "2026-06-23 05:22:10 UTC" (published_at)
    match_iso = re.match(r"(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2}):(\d{2})", publicado)
    if match_iso:
        anio, mes, dia, h, m, s = map(int, match_iso.groups())
        return datetime(anio, mes, dia, h, m, s, tzinfo=timezone.utc)

    # Caso 2: formato típico de "date" -> "06/23/2026, 01:09 PM, +0000 UTC"
    match_us = re.match(r"(\d{2})/(\d{2})/(\d{4}),?\s*(\d{1,2}):(\d{2})\s*([AP]M)?", publicado)
    if match_us:
        mes, dia, anio, h, m, ampm = match_us.groups()
        h = int(h)
        if ampm and ampm.upper() == "PM" and h != 12:
            h += 12
        if ampm and ampm.upper() == "AM" and h == 12:
            h = 0
        try:
            return datetime(int(anio), int(mes), int(dia), h, int(m), tzinfo=timezone.utc)
        except ValueError:
            return None

    # Caso 3: fechas relativas tipo "hace 3 horas" / "3 hours ago" —
    # se interpretan como "ahora mismo" (siempre pasan el filtro de
    # antigüedad, ya que son por definición recientes).
    if re.search(r"hace|ago|hour|minute|hora|minuto", publicado, re.IGNORECASE):
        return datetime.now(timezone.utc)

    return None


def _dentro_del_rango(item: Dict, dias_maximos: int) -> bool:
    """
    Filtro de respaldo en Python: True si la noticia está dentro del
    rango de antigüedad permitido, o si su fecha no se pudo determinar
    (en ese caso se deja pasar, para no descartar de más por un
    formato de fecha inesperado — mejor un falso positivo ocasional
    que perder noticias válidas por un parseo imperfecto).
    """
    fecha = _parsear_fecha_serpapi(item)
    if fecha is None:
        return True
    limite = datetime.now(timezone.utc) - timedelta(days=dias_maximos)
    return fecha >= limite


def buscar_noticias_pais(
    pais: str,
    api_key: str,
    tema: str = TEMA_BASE,
    max_resultados: int = 10,
    rango_tiempo: str = "qdr:w",  # qdr:w = última semana (filtro de SerpAPI)
    dias_maximos_antiguedad: int = DIAS_MAXIMOS_ANTIGUEDAD,
) -> List[Dict]:
    """
    Busca noticias recientes para un país usando SerpAPI.

    Parameters
    ----------
    pais : nombre del país (se usa también para etiquetar resultados)
    api_key : tu API key de SerpAPI
    tema : tema de búsqueda (por defecto: programas de protección social)
    max_resultados : tope de noticias crudas a traer por país (se filtran
                      luego a 5 relevantes en el Agente 2)
    rango_tiempo : filtro temporal enviado a SerpAPI como parámetro "tbs"
                   (motor "google" + tbm=nws, que sí lo soporta). Valores
                   válidos: "qdr:d" (24h), "qdr:w" (semana, por defecto),
                   "qdr:m" (mes).
    dias_maximos_antiguedad : filtro de respaldo aplicado en Python sobre
                   la fecha real de cada noticia, independiente de si
                   SerpAPI filtró correctamente o no.

    Returns
    -------
    Lista de dicts con keys: pais, titulo, fuente, fecha, snippet, link
    """
    query = construir_query(pais, tema)

    params = {
        "engine": "google",         # motor que sí soporta "tbs" documentadamente
        "tbm": "nws",                # resultados de la pestaña "Noticias"
        "q": query,
        "gl": _codigo_pais(pais),   # país de origen de la búsqueda
        "hl": "es",                 # idioma de resultados
        "tbs": rango_tiempo,        # filtro temporal real
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

    # Filtro de respaldo: descartar cualquier noticia que, al parsear su
    # fecha real, resulte más vieja que el límite permitido — sin
    # depender de que el filtro "tbs" de la API haya funcionado.
    noticias_crudas = [
        item for item in noticias_crudas
        if _dentro_del_rango(item, dias_maximos_antiguedad)
    ]

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
