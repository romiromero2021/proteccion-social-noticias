"""
AGENTE 1 — Recolector de noticias (scraper.py)
================================================
Responsabilidad única: dado un país, consultar SerpAPI combinando
términos temáticos con el nombre de la institución rectora de
protección/desarrollo social de ese país, y devolver una lista de
noticias crudas (título, fuente, fecha, snippet, link), filtradas a
la última semana, sin noticias de otros países, y solo si son
genuinamente relevantes al tema.

Historial de correcciones:
  1. El motor "google_news" de SerpAPI no soporta de forma documentada
     el parámetro de filtro de fecha "tbs" — Google lo ignoraba en
     silencio. Se corrigió usando el motor "google" + "tbm=nws", que
     sí lo soporta oficialmente, más un filtro de respaldo en Python
     (_dentro_del_rango) que vuelve a chequear la fecha real de cada
     noticia, independiente de si la API filtró bien o no.
  2. Una sola query de texto libre perdía precisión por país: Google
     devolvía noticias genéricas de protección social en la región
     que no eran realmente sobre el país pedido. Se corrigió usando
     el nombre del país entre comillas y combinando varios términos
     temáticos relacionados (protección social, seguridad social,
     CEPAL) con OR.
  3. Aun con comillas, Google a veces cuela noticias que solo
     mencionan el país pero no tienen relación real con el tema. Se
     agregó un filtro de relevancia en Python (_es_relevante_al_tema)
     que exige que el título o snippet contenga al menos una palabra
     clave del tema.
  4. ESTRATEGIA AMPLIADA (esta versión):
     a) Se incluye en la query el nombre de la institución rectora de
        protección/desarrollo social de cada país (ej. "IMAS" para
        Costa Rica, "MIDES" para Panamá), lo que ancla la búsqueda al
        país de forma mucho más específica que el nombre del país
        solo, ya que esas instituciones casi nunca se mencionan en
        noticias de otro país.
     b) Se agregó un filtro de "exclusión de país cruzado"
        (_menciona_otro_pais) que descarta una noticia si su título o
        snippet menciona explícitamente alguno de los OTROS 9 países
        de la lista (ej. una noticia que mencione "República
        Dominicana" no debe aparecer en el reporte de Costa Rica).
     c) Se amplió la lista de palabras clave de relevancia.

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

# Lista ampliada para el filtro de "exclusión de país cruzado"
# (_menciona_otro_pais). Incluye los 10 países del proyecto MÁS otros
# países de América Latina y España que frecuentemente aparecen como
# ruido en estas búsquedas (ej. una nota sobre Venezuela, o una nota
# de un periódico español que menciona "protección social" sin
# relación con ningún país de la lista del proyecto).
PAISES_A_EXCLUIR_SI_NO_BUSCADOS = PAISES + [
    "Venezuela",
    "Colombia",
    "Argentina",
    "Chile",
    "Perú",
    "Ecuador",
    "Bolivia",
    "Paraguay",
    "Uruguay",
    "Brasil",
]

# Demónimos/adjetivos derivados de cada país, para detectar menciones
# indirectas (ej. una noticia dice "el gobierno venezolano" en vez de
# "Venezuela" explícitamente). Mapeo país -> lista de variantes a buscar
# ADEMÁS del nombre del país. No es exhaustivo, cubre los casos más
# comunes en titulares de noticias.
DEMONIMOS_PAIS = {
    "Costa Rica": ["costarricense", "costarricenses"],
    "Cuba": ["cubano", "cubana", "cubanos", "cubanas"],
    "El Salvador": ["salvadoreño", "salvadoreña", "salvadoreños", "salvadoreñas"],
    "Guatemala": ["guatemalteco", "guatemalteca", "guatemaltecos", "guatemaltecas"],
    "Haití": ["haitiano", "haitiana", "haitianos", "haitianas"],
    "Honduras": ["hondureño", "hondureña", "hondureños", "hondureñas"],
    "México": ["mexicano", "mexicana", "mexicanos", "mexicanas"],
    "Nicaragua": ["nicaragüense", "nicaragüenses"],
    "Panamá": ["panameño", "panameña", "panameños", "panameñas"],
    "República Dominicana": ["dominicano", "dominicana", "dominicanos", "dominicanas"],
    "Venezuela": ["venezolano", "venezolana", "venezolanos", "venezolanas"],
    "Colombia": ["colombiano", "colombiana", "colombianos", "colombianas"],
    "Argentina": ["argentino", "argentina", "argentinos", "argentinas"],
    "Chile": ["chileno", "chilena", "chilenos", "chilenas"],
    "Perú": ["peruano", "peruana", "peruanos", "peruanas"],
    "Ecuador": ["ecuatoriano", "ecuatoriana", "ecuatorianos", "ecuatorianas"],
    "Bolivia": ["boliviano", "boliviana", "bolivianos", "bolivianas"],
    "Paraguay": ["paraguayo", "paraguaya", "paraguayos", "paraguayas"],
    "Uruguay": ["uruguayo", "uruguaya", "uruguayos", "uruguayas"],
    "Brasil": ["brasileño", "brasileña", "brasileños", "brasileñas", "brasilero", "brasilera"],
}

# ---------------------------------------------------------------------------
# INSTITUCIONES RECTORAS DE PROTECCIÓN/DESARROLLO SOCIAL POR PAÍS
# ---------------------------------------------------------------------------
# Fuente principal: CEPAL - Red de Desarrollo Social de América Latina y el
# Caribe (ReDeSoc), https://dds.cepal.org/redesoc/ministerios (consultado
# 2026). El Salvador no aparece en esa tabla porque no tiene un ministerio
# de desarrollo social centralizado; se usan sus dos instituciones más
# relevantes al tema (Ministerio de Trabajo y Previsión Social, y
# Ministerio de Desarrollo Local).
#
# MANTENIMIENTO: estos nombres cambian con cada gobierno (ej. Costa Rica
# cambió de nombre en 2018, México en 2018, Argentina en 2023). Revisar
# periódicamente contra la fuente de CEPAL arriba, o si una noticia del
# propio país menciona un nombre institucional distinto al aquí registrado.
INSTITUCIONES_PAIS = {
    "Costa Rica": [
        "Ministerio de Desarrollo Humano e Inclusión Social",
        "IMAS",
        "MDHIS",
    ],
    "Cuba": [
        "Ministerio de Trabajo y Seguridad Social",
        "MTSS",
    ],
    "El Salvador": [
        "Ministerio de Trabajo y Previsión Social",
        "Ministerio de Desarrollo Local",
        "MTPS",
        "MINDEL",
    ],
    "Guatemala": [
        "Ministerio de Desarrollo Social",
        "MIDES",
    ],
    "Haití": [
        "Ministerio de Asuntos Sociales y Trabajo",
        "MAST",
    ],
    "Honduras": [
        "Secretaría de Desarrollo Social",
        "SEDESOL Honduras",
    ],
    "México": [
        "Secretaría del Bienestar",
    ],
    "Nicaragua": [
        "Ministerio de la Familia, Adolescencia y Niñez",
        "MIFAN",
    ],
    "Panamá": [
        "Ministerio de Desarrollo Social",
        "MIDES",
        "CSS",
    ],
    "República Dominicana": [
        "Gabinete de Coordinación de Políticas Sociales",
        "Supérate",
    ],
}

# Términos temáticos generales que se combinan con el país y su
# institución para ampliar la cobertura. Se combinan con OR en una
# sola query (no se multiplica el número de llamadas a SerpAPI).
TERMINOS_TEMATICOS = [
    "programas de protección social",
    "seguridad social",
    "CEPAL protección social",
    "desarrollo social",
    "asistencia social",
    "transferencias monetarias",
]

# Palabras/fragmentos clave usados para el filtro de relevancia en
# Python (_es_relevante_al_tema). Basta que UNA aparezca en título o
# snippet para considerar la noticia relevante.
PALABRAS_CLAVE_RELEVANCIA = [
    # Frases temáticas generales (insensibles a mayúsculas/minúsculas)
    "protección social", "proteccion social",
    "seguridad social", "seguro social",
    "desarrollo social",
    "cepal",
    "pensión", "pensiones", "pensionado", "pensionados",
    "transferencia monetaria", "transferencias monetarias",
    "transferencia condicionada", "transferencias condicionadas",
    "asistencia social",
    "programa social", "programas sociales",
    "bono social", "bonos sociales",
    "subsidio social", "subsidios sociales",
    "ayuda social", "ayudas sociales",
    "beneficio social", "beneficios sociales",
    "red de protección", "red de proteccion",
    "política social", "politica social", "políticas sociales", "politicas sociales",
    "gasto social", "inversión social", "inversion social",
    "pobreza extrema", "reducción de la pobreza", "reduccion de la pobreza",
    "vulnerabilidad social", "población vulnerable", "poblacion vulnerable",
    "cuidados de larga duración", "cuidados de larga duracion",
    "personas adultas mayores", "adultos mayores",
    "primera infancia",
    # Siglas de instituciones de 4+ letras (riesgo bajo de ambigüedad)
    "inss", "imas", "ccss", "issste", "imss", "sipen",
    "mides", "mifan", "mast", "mdhis", "mtps", "mindel",
    "superate", "supérate",
]

# Siglas de 2-3 letras: alto riesgo de ambigüedad en contextos no
# relacionados (ej. "css" de hojas de estilo). Se buscan SOLO en
# mayúsculas exactas dentro del texto original.
SIGLAS_ESTRICTAS_MAYUSCULAS = [
    "CSS",   # Panamá (Caja de Seguro Social)
    "RD",    # República Dominicana (abreviación común en titulares)
]

TEMA_BASE = TERMINOS_TEMATICOS[0]  # se mantiene por compatibilidad con código existente

# Cuántos días de antigüedad máxima se permiten, como red de seguridad
# en Python (independiente de si SerpAPI filtra bien o no).
DIAS_MAXIMOS_ANTIGUEDAD = 10


def construir_query(pais: str, terminos: Optional[List[str]] = None) -> str:
    """
    Construye la query de búsqueda para un país específico, combinando
    términos temáticos (protección social, seguridad social, CEPAL...)
    con el nombre del país Y el nombre de su institución rectora de
    desarrollo/protección social, todo en una sola query con OR (sin
    multiplicar el consumo de cuota de SerpAPI).

    Incluir la institución ancla la búsqueda al país de forma mucho
    más específica que el nombre del país solo, porque esas
    instituciones casi nunca se mencionan en noticias de otro país.

    Ejemplo de query resultante para Panamá:
    ("programas de protección social" OR "seguridad social" OR ...)
    ("Panamá" OR "Ministerio de Desarrollo Social" OR "MIDES" OR "CSS")
    """
    terminos = terminos or TERMINOS_TEMATICOS
    terminos_con_or = " OR ".join(f'"{t}"' for t in terminos)

    instituciones = INSTITUCIONES_PAIS.get(pais, [])
    anclas_pais = [pais] + instituciones
    anclas_con_or = " OR ".join(f'"{a}"' for a in anclas_pais)

    return f'({terminos_con_or}) ({anclas_con_or})'


def _es_relevante_al_tema(item: Dict, palabras_clave: Optional[List[str]] = None) -> bool:
    """
    Filtro de relevancia en Python: True si el título o snippet de la
    noticia contiene al menos una de las palabras clave del tema.

    Usa coincidencia de palabra completa (no subcadena) para evitar
    falsos positivos con siglas cortas. Las frases/siglas largas se
    buscan sin distinguir mayúsculas; las siglas de alto riesgo de
    ambigüedad (SIGLAS_ESTRICTAS_MAYUSCULAS) solo cuentan si aparecen
    en mayúsculas exactas en el texto original.
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


def _menciona_otro_pais(item: Dict, pais_buscado: str) -> bool:
    """
    Filtro de exclusión de país cruzado: True si el título o snippet
    de la noticia menciona explícitamente otro país (de los 10 del
    proyecto, o de otros países de América Latina que frecuentemente
    aparecen como ruido en estas búsquedas) distinto al que se está
    buscando — ya sea por su nombre o por su demónimo/adjetivo (ej.
    "venezolano" en vez de "Venezuela").

    Esto descarta noticias que, aunque mencionen el país buscado o su
    institución de forma tangencial, son realmente sobre otro país.

    Nota: no se aplica al propio país buscado — solo a la mención
    explícita de OTROS países (o sus demónimos) como palabra completa.
    """
    texto = f"{item.get('title', '')} {item.get('snippet', '')}".lower()

    otros_paises = [p for p in PAISES_A_EXCLUIR_SI_NO_BUSCADOS if p != pais_buscado]

    palabras_a_buscar = list(otros_paises)
    for p in otros_paises:
        palabras_a_buscar.extend(DEMONIMOS_PAIS.get(p, []))

    return any(
        re.search(r"\b" + re.escape(palabra.lower()) + r"\b", texto)
        for palabra in palabras_a_buscar
    )


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
    formato de fecha inesperado).
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
    términos temáticos con el país y su institución rectora (ver
    construir_query), y aplicando tres filtros de respaldo en Python:
    fecha, relevancia temática, y exclusión de menciones de otro país.

    Parameters
    ----------
    pais : nombre del país (se usa también para etiquetar resultados)
    api_key : tu API key de SerpAPI
    terminos : lista de términos temáticos a combinar con OR (por
                defecto: TERMINOS_TEMATICOS)
    max_resultados : tope de noticias crudas a traer por país (se filtran
                      luego a 5 relevantes en el Agente 2)
    rango_tiempo : filtro temporal enviado a SerpAPI como parámetro "tbs"
                   (motor "google" + tbm=nws). Valores válidos: "qdr:d"
                   (24h), "qdr:w" (semana, por defecto), "qdr:m" (mes).
    dias_maximos_antiguedad : filtro de respaldo aplicado en Python sobre
                   la fecha real de cada noticia.

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

    # Filtro de respaldo 1 (fecha)
    noticias_crudas = [
        item for item in noticias_crudas
        if _dentro_del_rango(item, dias_maximos_antiguedad)
    ]

    # Filtro de respaldo 2 (relevancia temática)
    noticias_crudas = [
        item for item in noticias_crudas
        if _es_relevante_al_tema(item)
    ]

    # Filtro de respaldo 3 (exclusión de país cruzado)
    noticias_crudas = [
        item for item in noticias_crudas
        if not _menciona_otro_pais(item, pais)
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
