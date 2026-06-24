"""
AGENTE 1 — Recolector de noticias (scraper.py)
================================================
Responsabilidad única: dado un país, consultar SerpAPI con varios
términos relacionados a protección/seguridad social y devolver una
lista de noticias crudas (título, fuente, fecha, snippet, link),
filtradas a la última semana por defecto, deduplicadas por link.

Historial de correcciones:
  1. El motor "google_news" de SerpAPI no soporta de forma documentada
     el parámetro de filtro de fecha "tbs" — Google lo ignoraba en
     silencio (se vieron noticias de hasta 2020 mezcladas con 2026).
     Se corrigió usando el motor "google" + "tbm=nws", que sí lo
     soporta oficialmente, más un filtro de respaldo en Python
     (_dentro_del_rango) que vuelve a chequear la fecha real de cada
     noticia, independiente de si la API filtró bien o no.
  2. Una sola query de texto libre (sin comillas) perdía precisión por
     país: Google devolvía noticias genéricas de protección social en
     la región que no eran realmente sobre el país pedido. Se corrigió
     usando el nombre del país entre comillas (frase exacta) y
     combinando varios términos temáticos relacionados (protección
     social, seguridad social, CEPAL) en lugar de un solo término fijo.

  3. Aun con comillas y query precisa, Google a veces cuela noticias
     que solo mencionan el país pero no tienen relación real con el
     tema (ej. una noticia sobre buses chinos que de paso menciona
     "el Gobierno de Nicaragua"). Se agregó un filtro de relevancia en
     Python (_es_relevante_al_tema) que exige que el título o snippet
     contenga al menos una palabra clave del tema — no basta con que
     Google haya decidido que la query "calza".

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

# Términos temáticos que se combinan con el país para ampliar la
# cobertura, sin perder el foco del tema. Se combinan con OR en una
# sola query (no se multiplica el número de llamadas a SerpAPI).
TERMINOS_TEMATICOS = [
    "programas de protección social",
    "seguridad social",
    "CEPAL protección social",
]

# Palabras/fragmentos clave usados para el filtro de relevancia en
# Python (_es_relevante_al_tema). Son más granulares que las frases
# completas de arriba — basta que UNA aparezca en título o snippet
# para considerar la noticia relevante. Incluye variaciones del
# idioma (singular/plural, con o sin "de") y siglas de instituciones
# de seguridad/protección social comunes en la región, porque un
# snippet truncado por SerpAPI a menudo menciona la sigla (ej. "INSS")
# en vez de la frase completa "seguridad social".
PALABRAS_CLAVE_RELEVANCIA = [
    # Frases temáticas generales (insensibles a mayúsculas/minúsculas)
    "protección social", "proteccion social",
    "seguridad social", "seguro social",
    "cepal",
    "pensión", "pensiones", "pensionado", "pensionados",
    "transferencia monetaria", "transferencias monetarias",
    "asistencia social",
    "programa social", "programas sociales",
    "bono social", "bonos sociales",
    "subsidio social", "subsidios sociales",
    "ayuda social", "ayudas sociales",
    "beneficio social", "beneficios sociales",
    "red de protección", "red de proteccion",
    "transferencia condicionada", "transferencias condicionadas",
    # Siglas de instituciones de seguridad/protección social de 4+
    # letras (insensibles a mayúsculas — riesgo bajo de ambigüedad)
    "inss",      # Nicaragua, Honduras
    "imas",      # Costa Rica
    "ccss",      # Costa Rica (Caja Costarricense de Seguro Social)
    "issste",    # México
    "imss",      # México
    "sipen",     # República Dominicana
]

# Siglas de 2-3 letras: alto riesgo de ambigüedad en contextos no
# relacionados (ej. "css" de hojas de estilo). Se buscan SOLO en
# mayúsculas exactas dentro del texto original (antes de pasar a
# minúsculas), ya que así es como aparecen las siglas institucionales
# reales en una noticia, a diferencia de términos técnicos en minúsculas.
SIGLAS_ESTRICTAS_MAYUSCULAS = [
    "CSS",   # Panamá (Caja de Seguro Social)
]

TEMA_BASE = TERMINOS_TEMATICOS[0]  # se mantiene por compatibilidad con código existente

# Cuántos días de antigüedad máxima se permiten, como red de seguridad
# en Python (independiente de si SerpAPI filtra bien o no).
DIAS_MAXIMOS_ANTIGUEDAD = 10


def construir_query(pais: str, terminos: Optional[List[str]] = None) -> str:
    """
    Construye la query de búsqueda para un país específico, combinando
    varios términos temáticos relacionados (protección social, seguridad
    social, CEPAL) con el operador OR de Google, en una sola búsqueda
    por país (para no multiplicar el consumo de cuota de SerpAPI).

    El país va entre comillas (frase exacta) para evitar que Google
    devuelva noticias genéricas de la región que no son realmente
    sobre ese país. Cada término temático también va entre comillas
    para que el OR agrupe frases completas y no palabras sueltas.

    Ejemplo de query resultante:
    ("programas de protección social" OR "seguridad social" OR
     "CEPAL protección social") "Nicaragua"
    """
    terminos = terminos or TERMINOS_TEMATICOS
    terminos_con_or = " OR ".join(f'"{t}"' for t in terminos)
    return f'({terminos_con_or}) "{pais}"'


def _es_relevante_al_tema(item: Dict, palabras_clave: Optional[List[str]] = None) -> bool:
    """
    Filtro de relevancia en Python: True si el título o snippet de la
    noticia contiene al menos una de las palabras clave del tema.

    Esto descarta ruido que Google incluye solo por mencionar el país,
    sin relación real con protección/seguridad social (ej. una noticia
    de transporte público que de paso nombra "el Gobierno de Nicaragua").

    Usa coincidencia de palabra completa (no subcadena) para evitar
    falsos positivos con siglas cortas. Las frases/siglas largas se
    buscan sin distinguir mayúsculas; las siglas de alto riesgo de
    ambigüedad (SIGLAS_ESTRICTAS_MAYUSCULAS, ej. "CSS") solo cuentan
    si aparecen en mayúsculas exactas en el texto original, ya que así
    aparecen las siglas institucionales reales en una noticia.
    """
    palabras_clave = palabras_clave or PALABRAS_CLAVE_RELEVANCIA
    texto_original = f"{item.get('title', '')} {item.get('snippet', '')}"
    texto_lower = texto_original.lower()

    coincide_general = any(
        re.search(r"\b" + re.escape(palabra.lower()) + r"\b", texto_lower)
        for palabra in palabras_clave
    )
    if coincide_general:
        return True

    coincide_sigla_estricta = any(
        re.search(r"\b" + re.escape(sigla) + r"\b", texto_original)
        for sigla in SIGLAS_ESTRICTAS_MAYUSCULAS
    )
    return coincide_sigla_estricta


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
    terminos: Optional[List[str]] = None,
    max_resultados: int = 10,
    rango_tiempo: str = "qdr:w",  # qdr:w = última semana (filtro de SerpAPI)
    dias_maximos_antiguedad: int = DIAS_MAXIMOS_ANTIGUEDAD,
) -> List[Dict]:
    """
    Busca noticias recientes para un país usando SerpAPI, combinando
    varios términos temáticos en una sola query (ver construir_query).

    Parameters
    ----------
    pais : nombre del país (se usa también para etiquetar resultados)
    api_key : tu API key de SerpAPI
    terminos : lista de términos temáticos a combinar con OR (por
                defecto: TERMINOS_TEMATICOS — protección social,
                seguridad social, CEPAL protección social)
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
    query = construir_query(pais, terminos)

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

    # Filtro de respaldo 1 (fecha): descartar cualquier noticia que, al
    # parsear su fecha real, resulte más vieja que el límite permitido —
    # sin depender de que el filtro "tbs" de la API haya funcionado.
    noticias_crudas = [
        item for item in noticias_crudas
        if _dentro_del_rango(item, dias_maximos_antiguedad)
    ]

    # Filtro de respaldo 2 (relevancia): descartar noticias que Google
    # devolvió por mencionar el país, pero cuyo título/snippet no tiene
    # relación real con el tema (protección social, seguridad social, etc).
    noticias_crudas = [
        item for item in noticias_crudas
        if _es_relevante_al_tema(item)
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
    terminos: Optional[List[str]] = None,
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

        resultados[pais] = buscar_noticias_pais(pais, api_key, terminos)

    return resultados


if __name__ == "__main__":
    # Prueba rápida desde línea de comandos / Colab
    import json
    import os

    key = os.environ.get("SERPAPI_KEY", "TU_API_KEY_AQUI")
    resultado = buscar_noticias_pais("Costa Rica", key)
    print(json.dumps(resultado, indent=2, ensure_ascii=False))
