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
  4. ESTRATEGIA AMPLIADA:
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
  5. Se detectó que varios nombres institucionales NO son únicos por
     país: "Secretaría de Desarrollo Social" existe en México Y
     Honduras Y municipios de Venezuela; "MTSS" es Cuba Y Uruguay. Una
     noticia sobre "Secretaría de Desarrollo Social de Veracruz" (un
     estado mexicano) colaba en el reporte de Honduras porque nunca
     menciona "México" ni "mexicano" explícitamente, solo el nombre
     del estado. Se agregó un filtro adicional (_dominio_de_otro_pais)
     que detecta el TLD del link de la noticia (ej. ".uy", ".ve") y
     descarta si pertenece a un país distinto al buscado — más
     confiable que detectar nombres de subdivisiones, que son
     prácticamente infinitas y no se pueden enumerar exhaustivamente.

No interpreta ni resume nada — esa es responsabilidad del Agente 2.
"""

import re
import requests
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Optional
from urllib.parse import urlparse

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

# ---------------------------------------------------------------------------
# DOMINIOS DE MEDIOS DE PRENSA REALES POR PAÍS (ESTRATEGIA HÍBRIDA)
# ---------------------------------------------------------------------------
# Investigados manualmente (búsquedas verificadas, 23-24 jun 2026). Se usan
# con el operador "site:" para restringir la búsqueda SOLO a estos dominios
# — esto resuelve estructuralmente el problema de noticias de otros países
# coladas (Uruguay en Cuba, Veracruz en Honduras, etc.), porque un sitio que
# no está en esta lista no puede aparecer, sin importar qué tan bien
# escondido esté el nombre del país en el texto. Es la causa raíz que los
# filtros de texto (demónimos, TLD, subdivisiones) no podían cubrir del
# todo, al ser listas inherentemente incompletas.
#
# MANTENIMIENTO: si un país empieza a mostrar pocos o ningún resultado de
# forma sostenida, puede ser que falte agregar un medio relevante a su
# lista — no necesariamente significa que no haya cobertura real.
SITIOS_PAIS = {
    "Costa Rica": [
        "nacion.com", "crhoy.com", "lateja.cr", "diarioextra.com",
        "semanariouniversidad.com",
    ],
    "Cuba": [
        "cibercuba.com", "14ymedio.com", "diariodecuba.com",
        "oncubanews.com", "cubanet.org", "periodicocubano.com",
    ],
    "El Salvador": [
        "elsalvador.com", "laprensagrafica.com", "diario.elmundo.sv",
        "elmundo.sv", "gatoencerrado.news",
    ],
    "Guatemala": [
        "prensalibre.com", "soy502.com", "plazapublica.com.gt",
        "lahora.gt", "republica.gt",
    ],
    "Haití": [
        "lenouvelliste.com", "haitilibre.com", "ayibopost.com",
        "loophaiti.com", "alterpresse.org",
    ],
    "Honduras": [
        "laprensa.hn", "latribuna.hn", "tiempo.hn", "elheraldo.hn",
    ],
    "México": [
        "eluniversal.com.mx", "excelsior.com.mx", "milenio.com",
        "jornada.com.mx", "elfinanciero.com.mx",
    ],
    "Nicaragua": [
        "laprensani.com", "confidencial.digital", "el19digital.com",
    ],
    "Panamá": [
        "prensa.com", "tvn-2.com", "telemetro.com", "panamaamerica.com.pa",
    ],
    "República Dominicana": [
        "diariolibre.com", "listindiario.com", "elnuevodiario.com.do",
        "elnacional.com.do", "elcaribe.com.do",
    ],
}

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
# NOTA: este diccionario ya NO se usa para construir queries (ver
# construir_query) — se mantiene como referencia documental, y porque
# las siglas/nombres aquí listados sí se usan en PALABRAS_CLAVE_RELEVANCIA
# para el filtro de relevancia (_es_relevante_al_tema). Se descartó su
# uso como ancla de país porque varias instituciones tienen el mismo
# nombre en más de un país del proyecto (ver docstring de construir_query).
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
        "FISDL",          # Fondo de Inversión Social para el Desarrollo Local — cerrado
                          # en 2021/2022, sus funciones pasaron a MINDEL y la DOM, pero
                          # la prensa y la población siguen usando este nombre heredado
        "Red Solidaria",  # nombre histórico del principal programa de transferencias
                          # monetarias condicionadas, todavía referido así en prensa
        "Pensión Básica Universal",
        "Instituto Salvadoreño del Seguro Social",
        "ISSS",                                   # seguridad social real (salud, pensiones)
        "Superintendencia del Sistema Financiero",
        "Ministerio de Hacienda",                  # gasto social / presupuesto social
        "DIGESTYC",                                # Dirección General de Estadística y
                                                    # Censos — fuente de informes de pobreza
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

# Términos temáticos en francés, exclusivos para Haití (único país
# francófono de los 10). Sin esto, la búsqueda en español filtra de
# raíz casi toda la prensa haitiana real (Le Nouvelliste, AyiboPost,
# Radio Métropole, etc.), dejando solo cobertura *sobre* Haití escrita
# por medios internacionales en español. Verificados contra fuentes
# oficiales del MAST (Ministère des Affaires Sociales et du Travail).
TERMINOS_TEMATICOS_FRANCES = [
    "protection sociale",
    "sécurité sociale",
    "politique sociale",
    "assistance sociale",
    "transferts monétaires",
    "ministère des affaires sociales",
]

# Palabras clave de relevancia en francés, para que _es_relevante_al_tema
# reconozca noticias haitianas genuinas en ese idioma en vez de
# descartarlas por no calzar con las palabras clave en español.
PALABRAS_CLAVE_RELEVANCIA_FRANCES = [
    "protection sociale",
    "sécurité sociale", "securite sociale",
    "politique sociale", "politiques sociales",
    "assistance sociale",
    "transfert monétaire", "transferts monétaires",
    "développement social",
    "pauvreté", "pauvrete",
    "vulnérabilité", "vulnerabilite",
    "ministère des affaires sociales",
    "mast",
    "pnpps",  # Politique Nationale de Protection et de Promotion Sociales
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
    "fisdl", "red solidaria",
    "isss", "digestyc",
]

# Siglas de 2-3 letras: alto riesgo de ambigüedad en contextos no
# relacionados (ej. "css" de hojas de estilo). Se buscan SOLO en
# mayúsculas exactas dentro del texto original.
SIGLAS_ESTRICTAS_MAYUSCULAS = [
    "CSS",   # Panamá (Caja de Seguro Social)
    "RD",    # República Dominicana (abreviación común en titulares)
    "SSF",   # El Salvador (Superintendencia del Sistema Financiero) — 3 letras,
             # riesgo de ambigüedad con otras siglas, se exige mayúsculas exactas
]

TEMA_BASE = TERMINOS_TEMATICOS[0]  # se mantiene por compatibilidad con código existente

# Cuántos días de antigüedad máxima se permiten, como red de seguridad
# en Python (independiente de si SerpAPI filtra bien o no).
DIAS_MAXIMOS_ANTIGUEDAD = 10


def construir_query_site(pais: str, terminos: Optional[List[str]] = None) -> str:
    """
    Construye la query de búsqueda usando el operador "site:" para
    restringir los resultados SOLO a los dominios de medios reales de
    ese país (ver SITIOS_PAIS). Esta es la estrategia PRINCIPAL —
    elimina estructuralmente el ruido de otros países, ya que un sitio
    que no está en la lista no puede aparecer, sin depender de
    detectar nombres de país, demónimos, ciudades o siglas en el texto.

    Para Haití se agregan también los términos temáticos en francés.

    Ejemplo de query resultante para Honduras:
    ("programas de protección social" OR "seguridad social" OR ...)
    (site:laprensa.hn OR site:latribuna.hn OR site:tiempo.hn OR site:elheraldo.hn)
    """
    terminos = terminos or TERMINOS_TEMATICOS
    if pais == "Haití":
        terminos = list(terminos) + TERMINOS_TEMATICOS_FRANCES

    terminos_con_or = " OR ".join(f'"{t}"' for t in terminos)

    sitios = SITIOS_PAIS.get(pais, [])
    sitios_con_or = " OR ".join(f"site:{s}" for s in sitios)

    return f'({terminos_con_or}) ({sitios_con_or})'


def construir_query(pais: str, terminos: Optional[List[str]] = None) -> str:
    """
    Construye la query de búsqueda usando anclas de texto (nombre del
    país + demónimo), SIN restricción de dominio.

    Esta es la estrategia de RESPALDO — se usa solo si construir_query_site
    no trae ningún resultado relevante para ese país (ver
    buscar_noticias_pais), como red de seguridad ante el caso de que la
    lista de SITIOS_PAIS no cubra algún medio relevante todavía no
    identificado.

    IMPORTANTE: ya NO se incluyen las instituciones (INSTITUCIONES_PAIS)
    como ancla en esta query. Antes se usaban con OR junto al nombre
    del país, pero varias instituciones tienen el MISMO nombre en más
    de un país del proyecto (ej. "Ministerio de Desarrollo Social"
    existe tanto en Guatemala como en Panamá; "MTSS" en Cuba y
    Uruguay). Si la institución sola bastaba para el match, una
    noticia de un país podía colarse en el reporte de otro sin que
    ningún filtro de exclusión lo detectara (el filtro
    _menciona_otro_pais no ayuda cuando ambos países pertenecen al
    proyecto). Por eso ahora SOLO se usa el nombre del país y sus
    demónimos — más estricto, pero sin ese riesgo estructural.

    Para Haití (único país francófono de los 10), se agregan también
    los términos temáticos en francés y la grafía "Haïti".

    Ejemplo de query resultante para Panamá:
    ("programas de protección social" OR "seguridad social" OR ...)
    ("Panamá" OR "panameño" OR "panameña" OR "panameños" OR "panameñas")
    """
    terminos = terminos or TERMINOS_TEMATICOS
    if pais == "Haití":
        terminos = list(terminos) + TERMINOS_TEMATICOS_FRANCES

    terminos_con_or = " OR ".join(f'"{t}"' for t in terminos)

    pais_y_demonimos = [pais] + DEMONIMOS_PAIS.get(pais, [])
    if pais == "Haití":
        # "Haïti" (con ï francesa) es una cadena Unicode DISTINTA de
        # "Haití" (con í española) — sin esta variante, ninguna noticia
        # escrita en francés que use la grafía francesa del país hace
        # match con la query.
        pais_y_demonimos += ["Haïti"]

    anclas_pais_con_or = " OR ".join(f'"{a}"' for a in pais_y_demonimos)

    # El nombre del país/demónimo es SIEMPRE obligatorio (cláusula AND
    # independiente). Las instituciones NO se usan en construir_query
    # como ancla alternativa al país, precisamente porque varias se
    # repiten entre países del proyecto (ver docstring) — combinarlas
    # con OR permitiría que la institución sola bastara para el match.
    return f'({terminos_con_or}) ({anclas_pais_con_or})'


def _es_relevante_al_tema(item: Dict, palabras_clave: Optional[List[str]] = None) -> bool:
    """
    Filtro de relevancia en Python: True si el título o snippet de la
    noticia contiene al menos una de las palabras clave del tema.

    Usa coincidencia de palabra completa (no subcadena) para evitar
    falsos positivos con siglas cortas. Las frases/siglas largas se
    buscan sin distinguir mayúsculas; las siglas de alto riesgo de
    ambigüedad (SIGLAS_ESTRICTAS_MAYUSCULAS) solo cuentan si aparecen
    en mayúsculas exactas en el texto original.

    Siempre incluye también PALABRAS_CLAVE_RELEVANCIA_FRANCES (para
    Haití), sin riesgo relevante de falsos positivos en los otros 9
    países, ya que esas palabras en francés casi nunca aparecerían en
    una noticia en español de un país hispanohablante.
    """
    palabras_clave = list(palabras_clave or PALABRAS_CLAVE_RELEVANCIA) + PALABRAS_CLAVE_RELEVANCIA_FRANCES
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


def _buscar_una_vez(
    pais: str,
    api_key: str,
    query: str,
    rango_tiempo: str,
    max_resultados: int,
    dias_maximos_antiguedad: int,
) -> Dict:
    """
    Ejecuta una sola consulta a SerpAPI con un rango de tiempo dado.

    El filtro de FECHA se aplica de forma estricta (sin ambigüedad: una
    noticia más vieja que el límite nunca se acepta). Los otros 4
    filtros (relevancia temática, país cruzado por texto, TLD de
    dominio, subdivisiones de riesgo) se usan para CLASIFICAR cada
    noticia en "aceptada" o "descartada_marginal", en vez de eliminarla
    de inmediato — así, si después hacen falta más noticias de las que
    sobrevivieron, el agente verificador de Groq (ver summarizer.py)
    puede revisar las descartadas marginales y rescatar las que
    realmente sean relevantes, en vez de perderlas para siempre por un
    filtro de texto que no es 100% exhaustivo.

    Returns
    -------
    {"aceptadas": [...], "descartadas_marginales": [...], "error": str|None}
    Cada noticia en ambas listas tiene las keys: pais, titulo, fuente,
    fecha, snippet, link. "error" es None salvo que haya fallado la
    petición HTTP o la API haya devuelto un error.
    """
    idioma_busqueda = "fr" if pais == "Haití" else "es"

    params = {
        "engine": "google",
        "tbm": "nws",
        "q": query,
        "gl": _codigo_pais(pais),
        "hl": idioma_busqueda,
        "tbs": rango_tiempo,
        "api_key": api_key,
    }

    try:
        resp = requests.get(SERPAPI_ENDPOINT, params=params, timeout=20)
        resp.raise_for_status()
        data = resp.json()
    except requests.exceptions.RequestException as e:
        return {"aceptadas": [], "descartadas_marginales": [], "error": f"Error de conexión con SerpAPI: {e}"}

    if "error" in data:
        return {"aceptadas": [], "descartadas_marginales": [], "error": data["error"]}

    noticias_crudas = data.get("news_results", [])

    # Filtro de fecha: estricto, sin clasificar — una noticia vieja
    # jamás debe llegar ni siquiera a la lista de descartadas marginales
    # (no tiene sentido que el LLM "rescate" algo de hace años).
    noticias_crudas = [item for item in noticias_crudas if _dentro_del_rango(item, dias_maximos_antiguedad)]

    def _convertir(item: Dict) -> Dict:
        return {
            "pais": pais,
            "titulo": item.get("title", "Sin título"),
            "fuente": _extraer_fuente(item),
            "fecha": item.get("date", "Fecha no disponible"),
            "snippet": item.get("snippet", ""),
            "link": item.get("link", ""),
        }

    aceptadas = []
    descartadas_marginales = []
    for item in noticias_crudas:
        es_marginal = (
            not _es_relevante_al_tema(item)
            or _menciona_otro_pais(item, pais)
            or _dominio_de_otro_pais(item, pais)
            or _menciona_subdivision_de_riesgo(item, pais)
        )
        if es_marginal:
            descartadas_marginales.append(_convertir(item))
        else:
            aceptadas.append(_convertir(item))

    return {
        "aceptadas": aceptadas[:max_resultados],
        "descartadas_marginales": descartadas_marginales[:max_resultados],
        "error": None,
    }


def buscar_noticias_pais(
    pais: str,
    api_key: str,
    terminos: Optional[List[str]] = None,
    max_resultados: int = 10,
    rango_tiempo: str = "qdr:w",  # qdr:w = última semana (filtro de SerpAPI)
    dias_maximos_antiguedad: int = DIAS_MAXIMOS_ANTIGUEDAD,
    n_noticias_necesarias: int = 5,
) -> Dict:
    """
    Busca noticias recientes para un país usando SerpAPI, con una
    estrategia en capas:

    1. PRINCIPAL — query con "site:" restringido a medios reales del
       país (ver SITIOS_PAIS / construir_query_site). Elimina
       estructuralmente el ruido de otros países: un sitio que no está
       en la lista no puede aparecer, sin depender de detectar texto.
    2. RESPALDO/COMPLEMENTO — si la capa 1 no llega a n_noticias_necesarias
       (ej. la lista de sitios no cubre algún medio relevante todavía
       no identificado, o simplemente hubo poca cobertura), se
       consulta también la query de anclas de texto (nombre del país
       + demónimo), sin restricción de dominio, y se combinan los
       resultados de ambas capas (sin duplicar por link).
    3. FALLBACK DE FECHA — en cualquiera de las dos capas, si el rango
       de 1 semana no trae nada, se reintenta con 2 semanas.

    El filtro de fecha es estricto (una noticia vieja nunca se acepta).
    Los demás filtros (relevancia, país cruzado, TLD, subdivisiones)
    clasifican cada noticia en "aceptada" o "descartada_marginal" en
    vez de eliminarla — las descartadas marginales quedan disponibles
    para que el agente verificador de Groq (summarizer.py) las revise
    si después de todo no hay suficientes noticias aceptadas.

    Parameters
    ----------
    pais : nombre del país (se usa también para etiquetar resultados)
    api_key : tu API key de SerpAPI
    terminos : lista de términos temáticos a combinar con OR (por
                defecto: TERMINOS_TEMATICOS)
    max_resultados : tope de noticias crudas a traer por consulta a
                      SerpAPI (no es el cupo final — ver
                      n_noticias_necesarias para eso)
    rango_tiempo : filtro temporal inicial enviado a SerpAPI como "tbs".
                   Valores válidos: "qdr:d" (24h), "qdr:w" (semana, por
                   defecto), "qdr:m" (mes).
    dias_maximos_antiguedad : filtro de respaldo aplicado en Python sobre
                   la fecha real de cada noticia. Si se usa el fallback
                   a 2 semanas, este límite también se amplía a 14 días.
    n_noticias_necesarias : cupo real de noticias que se necesitan para
                   este país (debe coincidir con n_noticias usado en
                   summarizer.procesar_pais). Se usa para decidir si
                   hace falta consultar la capa 2 — si la capa 1 ya
                   alcanzó este cupo, no se gasta cuota adicional.

    Returns
    -------
    {"aceptadas": [...], "descartadas_marginales": [...], "error": str|None}
    """

    def _buscar_con_fallback_fecha(query: str) -> Dict:
        """Aplica el fallback de 1 semana -> 2 semanas para una query dada."""
        resultado = _buscar_una_vez(pais, api_key, query, rango_tiempo, max_resultados, dias_maximos_antiguedad)
        if resultado["error"] is not None:
            return resultado
        if len(resultado["aceptadas"]) == 0 and rango_tiempo == "qdr:w":
            resultado_2sem = _buscar_una_vez(pais, api_key, query, "qdr:w2", max_resultados, dias_maximos_antiguedad=14)
            if resultado_2sem["error"] is not None:
                return resultado_2sem
            # Combinar descartadas marginales de ambos intentos, por si
            # el verificador LLM necesita más candidatas para revisar.
            resultado_2sem["descartadas_marginales"] = (
                resultado["descartadas_marginales"] + resultado_2sem["descartadas_marginales"]
            )
            return resultado_2sem
        return resultado

    # Capa 1: query con site: (estrategia principal)
    query_site = construir_query_site(pais, terminos)
    resultado = _buscar_con_fallback_fecha(query_site)

    if resultado["error"] is not None:
        return resultado  # error de conexión/API, no tiene sentido reintentar con otra query

    if len(resultado["aceptadas"]) >= n_noticias_necesarias:
        return resultado

    # Capa 2: respaldo con anclas de texto, sin restricción de dominio.
    # Se consulta SIEMPRE que la capa 1 no haya llegado al cupo
    # solicitado (max_resultados) — no solo cuando la capa 1 quedó en
    # cero — para poder COMPLEMENTAR (no solo reemplazar) lo que site:
    # ya encontró. Se combinan tanto las aceptadas como las descartadas
    # marginales de ambas capas, para maximizar las candidatas
    # disponibles para el verificador LLM si después de todo hace falta.
    query_anclas = construir_query(pais, terminos)
    resultado_anclas = _buscar_con_fallback_fecha(query_anclas)

    if resultado_anclas["error"] is not None:
        # La capa 2 falló por error de conexión/API — se devuelve lo que
        # sí se obtuvo de la capa 1 en vez de perderlo todo.
        return resultado

    # Combinar aceptadas de ambas capas, evitando duplicados por link
    # (es posible que el mismo artículo aparezca en ambas búsquedas).
    links_ya_vistos = {n["link"] for n in resultado["aceptadas"]}
    aceptadas_combinadas = list(resultado["aceptadas"])
    for noticia in resultado_anclas["aceptadas"]:
        if noticia["link"] not in links_ya_vistos:
            aceptadas_combinadas.append(noticia)
            links_ya_vistos.add(noticia["link"])

    descartadas_combinadas = resultado["descartadas_marginales"] + resultado_anclas["descartadas_marginales"]

    return {
        "aceptadas": aceptadas_combinadas[:max_resultados],
        "descartadas_marginales": descartadas_combinadas[:max_resultados],
        "error": None,
    }


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


# TLDs (dominios de país) de la región que más frecuentemente generan
# ruido cruzado en estas búsquedas, mapeados a su país real. No es
# necesario listar los 10 países del proyecto aquí — solo los que
# históricamente han causado el problema (México, Uruguay, Venezuela,
# Argentina, Paraguay...). Si en el futuro aparece ruido de otro TLD,
# agregarlo aquí es la forma más confiable de filtrarlo, mucho más
# precisa que intentar enumerar nombres de ciudades/estados.
TLD_A_PAIS = {
    "mx": "México",
    "uy": "Uruguay",
    "ve": "Venezuela",
    "ar": "Argentina",
    "py": "Paraguay",
    "co": "Colombia",
    "cl": "Chile",
    "pe": "Perú",
    "ec": "Ecuador",
    "bo": "Bolivia",
    "br": "Brasil",
}

# Subdivisiones (estados/provincias/departamentos/municipios) de otros
# países que han causado ruido confirmado en la práctica, para noticias
# publicadas en dominios genéricos (.com, .org) donde el filtro de TLD
# no aplica. A diferencia de TLD_A_PAIS, esta lista NO intenta ser
# exhaustiva — sería una lista casi infinita de nombres de lugares en
# toda la región. Se agrega un nombre aquí solo cuando se confirma un
# caso real de ruido en un reporte generado (no de forma preventiva),
# mapeado al país real al que pertenece esa subdivisión.
SUBDIVISIONES_DE_RIESGO_CONFIRMADAS = {
    "veracruz": "México",  # confirmado: coló en reporte de Honduras (24-jun-2026)
}


def _dominio_de_otro_pais(item: Dict, pais_buscado: str) -> bool:
    """
    Filtro de exclusión por dominio: True si el link de la noticia
    tiene un TLD de país (ej. ".uy", ".ve", ".mx") que NO corresponde
    al país buscado.

    Esto resuelve el caso de instituciones con nombres genéricos que
    se repiten en varios países (ej. "Secretaría de Desarrollo
    Social" existe en México, Honduras, y municipios de Venezuela;
    "MTSS" es tanto Cuba como Uruguay) — el TLD del sitio que publica
    la noticia es una señal mucho más confiable del país real que el
    texto del título/snippet, que rara vez menciona el nombre del país
    cuando ya está implícito para sus lectores locales.

    No descarta nada si el TLD es genérico (.com, .org, etc.) o no
    está en TLD_A_PAIS — en ese caso, los demás filtros (relevancia,
    menciona_otro_pais) siguen aplicando.
    """
    link = item.get("link", "")
    if not link:
        return False

    dominio = urlparse(link).netloc.lower()
    # Extraer el TLD final (ej. "www.gub.uy" -> "uy", "ladiaria.com.uy" -> "uy")
    partes = dominio.split(".")
    if len(partes) < 2:
        return False
    tld = partes[-1]

    pais_del_tld = TLD_A_PAIS.get(tld)
    if pais_del_tld is None:
        return False  # TLD genérico o no mapeado, no se descarta por esta vía

    return pais_del_tld != pais_buscado


def _menciona_subdivision_de_riesgo(item: Dict, pais_buscado: str) -> bool:
    """
    Filtro complementario al de TLD: True si el título o snippet
    menciona una subdivisión (estado/provincia) de otro país que ya
    se confirmó como fuente de ruido (ver SUBDIVISIONES_DE_RIESGO_CONFIRMADAS),
    útil para noticias publicadas en dominios genéricos donde el TLD
    no revela el país real.
    """
    texto = f"{item.get('title', '')} {item.get('snippet', '')}".lower()
    for subdivision, pais_real in SUBDIVISIONES_DE_RIESGO_CONFIRMADAS.items():
        if pais_real == pais_buscado:
            continue  # no aplica si la subdivisión es del propio país buscado
        if re.search(r"\b" + re.escape(subdivision) + r"\b", texto):
            return True
    return False


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
    Dict {pais: resultado_busqueda}, donde resultado_busqueda es el
    dict {"aceptadas", "descartadas_marginales", "error"} devuelto por
    buscar_noticias_pais.
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
