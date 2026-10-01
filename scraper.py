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
     desarrollo social) con OR.
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
import time
import unicodedata
import requests
from datetime import datetime, timedelta, timezone

from typing import List, Dict, Optional
from urllib.parse import urlparse

SERPAPI_ENDPOINT = "https://serpapi.com/search"


def _quitar_tildes(texto: str) -> str:
    """Normaliza un texto quitándole los diacríticos."""
    descompuesto = unicodedata.normalize("NFKD", texto or "")
    return "".join(c for c in descompuesto if not unicodedata.combining(c))

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
    # Revisión completa con verificación por búsqueda: 29-sep-2026.
    # Se comprobó uno por uno que el dominio existe, que la grafía es
    # la correcta y que el medio sigue publicando. Hallazgos:
    #   - republica.gt estaba MUERTO (redirige a republica.com/usa), o
    #     sea que una de las cinco entradas de Guatemala no devolvía
    #     nada desde hacía tiempo.
    #   - elmundo.sv y diario.elmundo.sv eran la misma cosa duplicada.
    #   - La lista de Cuba era TODA de medios del exilio; faltaba la
    #     prensa oficial, que es justamente la que informa de las
    #     medidas de protección social del Estado cubano.
    #   - Haití, el país con peor cobertura histórica, tenía solo 5
    #     medios y uno de ellos (loophaiti.com) sin actividad
    #     verificable desde 2020.
    #
    # CRITERIO PARA AÑADIR: diarios nacionales, medios económicos y
    # medios de investigación de alcance nacional. NO se añaden medios
    # locales o estatales — son la causa de las notas de Veracruz,
    # Coahuila y Quintana Roo que se colaron en reportes anteriores.
    #
    # LÍMITE DELIBERADO: unos 8 dominios por país. Cada uno alarga la
    # consulta, y las consultas largas con site: fueron lo que falló en
    # la incidencia de SerpAPI del 20-sep-2026. Los sitios oficiales de
    # las instituciones rectoras (IGSS, CCSS, MIDES, ONA…) quedaron
    # fuera a propósito: ya llegan por la capa de anclas cuando son
    # noticia, y en la capa 1 desplazarían al periodismo por
    # comunicados —Guatemala ya salió 4 de 5 con notas del IGSS—.
    # La lista verificada está en el README por si se quiere usar.

    "Costa Rica": [
        "nacion.com", "crhoy.com", "diarioextra.com",
        "semanariouniversidad.com",
        "delfino.cr",            # digital de política pública
        "elmundo.cr",            # ya aportaba notas vía la capa 2 (ojo: NO es elmundo.sv)
        "elfinancierocr.com",    # económico; cubre la reforma de pensiones
        "observador.cr",
        # lateja.cr retirado: es de sucesos y deportes, sin valor para este tema.
    ],
    "Cuba": [
        # Independientes y del exilio.
        "cibercuba.com", "14ymedio.com", "diariodecuba.com",
        "oncubanews.com", "cubanet.org",
        # Oficiales, publicados desde Cuba. Son los que informan de las
        # medidas del Estado: pagos a jubilados, resoluciones del MTSS,
        # escalas salariales. Sin ellos la sección de Cuba solo veía el
        # tema desde fuera.
        "granma.cu",         # órgano del Comité Central del PCC
        "cubadebate.cu",     # publica íntegras las resoluciones del MTSS
        "trabajadores.cu",   # órgano de la CTC: seguridad social directa
        # periodicocubano.com retirado para dejar sitio a la prensa oficial.
    ],
    "El Salvador": [
        "elsalvador.com", "laprensagrafica.com",
        "elmundo.sv",            # cubre también diario.elmundo.sv (match por subdominio)
        "gatoencerrado.news",
        "elfaro.net",            # investigación de referencia
        "diarioelsalvador.com",  # línea oficialista: anuncios de gobierno
        "diariocolatino.com",    # temas laborales y sindicales
        # diario.elmundo.sv retirado: era duplicado de elmundo.sv.
    ],
    "Guatemala": [
        "prensalibre.com", "soy502.com", "plazapublica.com.gt",
        "lahora.gt",
        "agn.gt",                # agencia estatal: anuncios de MIDES e IGSS
        "guatevision.com",
        "agenciaocote.com",      # derechos sociales y política pública
        # republica.gt RETIRADO: dominio muerto, redirige a republica.com/usa.
    ],
    "Haití": [
        # El país con peor cobertura del monitoreo, y el único
        # francófono: se amplía más que los demás a propósito.
        "lenouvelliste.com", "haitilibre.com", "ayibopost.com",
        "alterpresse.org",
        "juno7.ht",          # ya aportaba notas vía la capa 2
        "lenational.org",    # cubrió el foro del ONA sobre pensiones
        "metropole.ht",      # Radio Télé Métropole (NO metropolehaiti.com)
        "gazettehaiti.com",
        "vantbefinfo.com",
        # Ampliación del 30-sep-2026, con cobertura del tema verificada
        # artículo por artículo (no preventiva):
        "rhinews.com",       # Réseau Haïtien de l'Information: serie sobre
                             # la reforma de pensiones del ONA
        "hpninfo.com",       # Haiti Press Network: movilización obrera por
                             # el salario mínimo, sindicato policial
        "icihaiti.com",      # publica el boletín semanal del ONA y notas de
                             # OFATMA. Mismo editor que haitilibre.com, así
                             # que habrá duplicados; los resuelve el editor
        "haitiantimes.com",  # prensa de la diáspora (Nueva York), en inglés:
                             # huelga textil, salario mínimo. OJO: publica
                             # también mucho sobre política migratoria de
                             # EE.UU., que NO es protección social haitiana
        # loophaiti.com RETIRADO: sin publicaciones verificables desde 2020.
    ],
    "Honduras": [
        "laprensa.hn", "latribuna.hn", "tiempo.hn", "elheraldo.hn",
        "criterio.hn",           # cobertura sostenida del IHSS y pensiones
        "proceso.hn",            # ya aportaba notas vía la capa 2
        "contracorriente.red",   # investigación (dominio .red, no .hn)
        "elpais.hn",
    ],
    "México": [
        "eluniversal.com.mx", "excelsior.com.mx", "milenio.com",
        "jornada.com.mx", "elfinanciero.com.mx",
        "eleconomista.com.mx",   # Afores, IMSS, seguridad social
        "expansion.mx",
        "grupoanimal.mx",        # Animal Político: animalpolitico.com redirige aquí
    ],
    "Nicaragua": [
        "laprensani.com",        # dominio vigente: el .com.ni fue cancelado en 2025
        "confidencial.digital", "el19digital.com",
        "divergentes.com",       # ya aportaba notas vía la capa 2
        "despacho505.com",
        "nicaraguainvestiga.com",
    ],
    "Panamá": [
        "prensa.com", "tvn-2.com", "telemetro.com", "panamaamerica.com.pa",
        "laestrella.com.pa",     # tiene sección de Economía propia
        "focopanama.com",
    ],
    "República Dominicana": [
        "diariolibre.com", "listindiario.com", "elnuevodiario.com.do",
        "elnacional.com.do", "elcaribe.com.do",
        "eldinero.com.do",       # único medio especializado en economía
        "acento.com.do",
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
    "España",  # confirmado: noticia de Valladolid coló en El Salvador (17-jul-2026).
               # NOTA: intencionalmente NO se agrega el demónimo "español/a" a
               # DEMONIMOS_PAIS, porque también es el nombre del idioma ("en
               # español") y generaría falsos positivos masivos. España se
               # detecta por su nombre, por sus subdivisiones (ver
               # SUBDIVISIONES_DE_RIESGO_CONFIRMADAS) y por señales textuales
               # como "euros" (ver SENALES_TEXTUALES_PAIS).
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
    "desarrollo social",
    "asistencia social",
    "transferencias monetarias",
]
# Nota (29-sep-2026): aquí había un sexto término, "CEPAL protección
# social". Se retiró porque no podía funcionar: en la capa 1 la query
# va restringida con site: a medios de prensa nacionales, y cepal.org
# no está en ninguna lista (es un organismo regional, no prensa de un
# país); en la capa 2 se busca como frase exacta, y "CEPAL protección
# social" no aparece literalmente en ningún titular. Solo alargaba la
# consulta, y las consultas largas fueron lo que se cayó en la
# incidencia de SerpAPI del 20-sep-2026.
#
# Se intentó también una sección propia con el material de la CEPAL,
# primero por los feeds RSS de ReDeSoc (devuelven error 500 del lado de
# la CEPAL) y después por búsqueda con site:cepal.org (agota el tiempo
# de espera de SerpAPI). Se retiró el 29-sep-2026 tras no conseguir que
# funcionara por ninguna de las dos vías. El README lo documenta.
#
# Lo que SÍ sigue: que una noticia de prensa MENCIONE a la CEPAL se
# detecta con la palabra clave "cepal" de PALABRAS_CLAVE_RELEVANCIA.

# Términos temáticos en francés, exclusivos para Haití (único país
# francófono de los 10). Sin esto, la búsqueda en español filtra de
# raíz casi toda la prensa haitiana real (Le Nouvelliste, AyiboPost,
# Radio Métropole, etc.), dejando solo cobertura *sobre* Haití escrita
# por medios internacionales en español. Verificados contra fuentes
# oficiales del MAST (Ministère des Affaires Sociales et du Travail).
# Nota (30-sep-2026): se retiraron "politique sociale" y "transferts
# monétaires" al ampliar la lista de medios haitianos de 9 a 13. Cada
# término y cada dominio alargan la consulta, y la de Haití ya era la
# más larga de las diez. Se eligieron esos dos por ser los de menor
# rendimiento: "politique sociale" se solapa con "protection sociale",
# y los programas de transferencias monetarias apenas aparecen con ese
# nombre en la prensa haitiana, donde se habla de "filets sociaux".
TERMINOS_TEMATICOS_FRANCES = [
    "protection sociale",
    "sécurité sociale",
    "assistance sociale",
    "ministère des affaires sociales",
    "système de retraite",   # la reforma de pensiones domina la agenda haitiana
    "assurance-vieillesse",
    "filets sociaux",
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
    # Vocabulario agregado el 21-sep-2026 tras comprobar que faltaba lo
    # esencial: dos de las mejores noticias haitianas de la semana —el
    # foro nacional sobre la reforma del sistema de pensiones, en Le
    # Nouvelliste y AlterPresse— eran rechazadas como "no relevantes"
    # porque "retraite" (jubilación) y "ONA" (la caja de pensiones
    # haitiana) no figuraban en esta lista. El equivalente sería
    # descartar en México una nota sobre el IMSS.
    "retraite", "retraites",           # jubilación / pensiones
    "système de retraite",
    "assurance-vieillesse", "assurance vieillesse",
    "pension", "pensions",             # en francés
    "ona",                             # Office National d'Assurance-vieillesse
    "ofatma",                          # Office d'Assurance Accidents du Travail et Maladie
    "filets sociaux", "filet social",  # redes de protección
    "aide sociale",
    "cantine scolaire", "cantines scolaires",  # alimentación escolar
    "klere chimen",                    # programa social haitiano
    "sécurité alimentaire", "securite alimentaire",
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


def construir_query_site(pais: str, terminos: Optional[List[str]] = None,
                         max_terminos: Optional[int] = None,
                         max_sitios: Optional[int] = None) -> str:
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
        # Para Haití se usan SOLO los términos en francés, no la suma de
        # español + francés. La prensa haitiana (Le Nouvelliste,
        # AlterPresse, HaitiLibre, los medios curados del país) publica
        # en francés: los seis términos en español no aportan resultados
        # y solo alargan la consulta. Comprobado el 21-sep-2026: una
        # consulta corta en francés devolvió ocho noticias haitianas
        # pertinentes, cuatro de ellas de medios curados.
        terminos = list(TERMINOS_TEMATICOS_FRANCES)

    if max_terminos is not None:
        terminos = list(terminos)[:max_terminos]

    terminos_con_or = " OR ".join(f'"{t}"' for t in terminos)

    sitios = SITIOS_PAIS.get(pais, [])
    if max_sitios is not None:
        # Se conservan los primeros, que es donde están los diarios
        # nacionales de mayor circulación de cada lista.
        sitios = list(sitios)[:max_sitios]
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
        # Para Haití se usan SOLO los términos en francés, no la suma de
        # español + francés. La prensa haitiana (Le Nouvelliste,
        # AlterPresse, HaitiLibre, los medios curados del país) publica
        # en francés: los seis términos en español no aportan resultados
        # y solo alargan la consulta. Comprobado el 21-sep-2026: una
        # consulta corta en francés devolvió ocho noticias haitianas
        # pertinentes, cuatro de ellas de medios curados.
        terminos = list(TERMINOS_TEMATICOS_FRANCES)

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


def _tema_en_el_titulo(item: Dict) -> bool:
    """
    True si el TÍTULO (no el snippet) contiene una palabra clave del
    tema. Señal más fuerte que la relevancia general: cuando el tema
    aparece solo en el snippet, suele ser una mención de pasada.

    Caso confirmado (21-sep-2026): "¿Cuánto y cómo usa la industria la
    IA en Costa Rica?" entró al reporte porque su snippet mencionaba
    una "conferencia de seguridad social" que el directivo citado iba a
    atender. El título deja claro que la noticia es sobre inteligencia
    artificial en la industria, no sobre protección social.
    """
    return _es_relevante_al_tema({"title": item.get("title", ""), "snippet": ""})


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

    Cuenta también como mención de otro país la presencia de un
    topónimo homónimo (ver TOPONIMOS_HOMONIMOS): si el texto habla de
    "Villa El Salvador", eso no solo deja de ser evidencia de El
    Salvador, es evidencia de que la noticia es peruana.
    """
    texto, paises_delatados = _texto_de_pais(item)

    if paises_delatados - {pais_buscado}:
        return True

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

    # Caso 4: fecha con el mes en letra, "23 sept 2026" o "Sep 23, 2026".
    # Es el formato habitual de los resultados WEB (organic_results),
    # que es lo que llega cuando Google contesta con resultados web en
    # vez de noticias. Sin este caso esas fechas no se interpretaban y
    # el filtro de antigüedad las dejaba pasar todas por defecto,
    # incluidas páginas de hace años.
    fecha_con_mes = _parsear_fecha_con_mes_en_letra(publicado)
    if fecha_con_mes is not None:
        return fecha_con_mes

    return None


# Meses en español e inglés, por sus primeras tres letras sin tilde.
_MESES_POR_ABREVIATURA = {
    "ene": 1, "jan": 1, "feb": 2, "mar": 3, "abr": 4, "apr": 4,
    "may": 5, "jun": 6, "jul": 7, "ago": 8, "aug": 8,
    "sep": 9, "set": 9, "oct": 10, "nov": 11, "dic": 12, "dec": 12,
}


def _parsear_fecha_con_mes_en_letra(texto: str) -> Optional[datetime]:
    """
    Interpreta fechas con el mes escrito: "23 sept 2026", "Sep 23,
    2026", "23 de septiembre de 2026". Devuelve el final del día, por
    el mismo motivo que _fecha_desde_url: el dato no tiene hora, y la
    duda debe jugar a favor de conservar la noticia.
    """
    if not texto:
        return None
    limpio = _quitar_tildes(texto.lower())

    # "23 sept 2026" / "23 de septiembre de 2026"
    m = re.search(r"\b(\d{1,2})\s+(?:de\s+)?([a-z]{3})[a-z.]*\s+(?:de\s+)?(\d{4})\b", limpio)
    if not m:
        # "sep 23, 2026"
        m = re.search(r"\b([a-z]{3})[a-z.]*\s+(\d{1,2}),?\s+(\d{4})\b", limpio)
        if not m:
            return None
        mes_txt, dia, anio = m.group(1), m.group(2), m.group(3)
    else:
        dia, mes_txt, anio = m.group(1), m.group(2), m.group(3)

    mes = _MESES_POR_ABREVIATURA.get(mes_txt)
    if mes is None:
        return None
    try:
        return datetime(int(anio), mes, int(dia), 23, 59, 59, tzinfo=timezone.utc)
    except ValueError:
        return None


# Patrones de fecha incrustada en la URL. Casi todos los gestores de
# contenido (WordPress, Drupal y los CMS de los medios curados) ponen
# la fecha real de publicación en la ruta: /2026/09/23/titulo o
# /noticias/2026-09-23-titulo. Cuando existe, es MÁS confiable que el
# campo "date" de SerpAPI, que refleja lo que Google cree (y Google se
# equivoca en páginas sin fecha propia: las fecha por rastreo).
_PATRONES_FECHA_URL = (
    re.compile(r"/((?:19|20)\d{2})/(\d{1,2})/(\d{1,2})(?:/|$|[-_])"),
    re.compile(r"[/\-_]((?:19|20)\d{2})-(\d{1,2})-(\d{1,2})(?:[/\-_.]|$)"),
)


def _fecha_desde_url(link: str) -> Optional[datetime]:
    """
    Extrae la fecha de publicación incrustada en la URL, si la hay.
    Devuelve None si la URL no lleva fecha o si los componentes no
    forman una fecha válida.
    """
    if not link:
        return None
    for patron in _PATRONES_FECHA_URL:
        match = patron.search(link)
        if not match:
            continue
        anio, mes, dia = (int(g) for g in match.groups())
        try:
            # Fin del día, no medianoche: la URL indica el DÍA de
            # publicación, no la hora. Si se tomara la medianoche, una
            # noticia publicada justo en el límite del rango (ej. hace
            # exactamente 7 días, por la tarde) quedaría fuera por unas
            # horas que el dato nunca tuvo. Al asumir el último instante
            # del día, la duda juega a favor de conservar la noticia.
            return datetime(anio, mes, dia, 23, 59, 59, tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def _anio_antiguo_en(texto: str, anio_corte: int) -> Optional[int]:
    """
    Devuelve el primer año <= anio_corte que aparezca como token
    independiente en el texto, o None si no hay ninguno. Se exige que
    no esté pegado a otros dígitos, para no confundir un año con parte
    de una cifra (ej. "32954" no contiene el año 3295).
    """
    for match in re.finditer(r"(?<!\d)((?:19|20)\d{2})(?!\d)", texto):
        anio = int(match.group(1))
        if anio <= anio_corte:
            return anio
    return None


def _parece_archivo_antiguo(item: Dict) -> bool:
    """
    Detecta páginas de archivo que Google fecha como recientes.

    CASO REAL (29-sep-2026, Guatemala): SerpAPI devolvió
    "Conversatorio-UNOPS-IGSS-Guatemala-2018-2"
    (igssgt.org/noticias/conversatorio-unops-igss-guatemala-2018-2/)
    con date="hace 6 días". No era una noticia: era la página de una
    FOTO de un evento de 2018, sin fecha propia, que Google fechó por
    la fecha de rastreo. Ningún filtro de fecha podía atraparla, porque
    el dato de fecha que llegaba era falso en origen.

    La evidencia real estaba en otro lado, y es la que se usa aquí:

    1. AÑO ANTIGUO en el título o en la ruta de la URL, sin ningún año
       reciente que lo acompañe. "…-guatemala-2018-2" delata el archivo.
       Se exige la ausencia de año reciente para no castigar titulares
       legítimos como "Comparativa de pensiones 2018-2026" ni
       "…analizar el PPEF 2027".

    2. TÍTULO CON FORMA DE NOMBRE DE ARCHIVO: sin espacios y con
       guiones, como el de la foto. Un titular de prensa real siempre
       lleva espacios. Esto atrapa adjuntos, galerías y PDFs sueltos
       aunque no mencionen ningún año.

    Solo mira el título y la URL, nunca el snippet: en el cuerpo de una
    noticia actual es normal citar años pasados ("desde 2018…"), y
    mirarlo ahí produciría falsos positivos constantes.
    """
    titulo = (item.get("title") or "").strip()
    link = item.get("link") or ""
    anio_actual = datetime.now(timezone.utc).year

    # Regla 2: título con forma de nombre de archivo.
    if titulo and " " not in titulo and titulo.count("-") >= 2:
        return True

    # Regla 1: año antiguo sin año reciente que lo contextualice.
    # Se toma la ruta de la URL sin el dominio: un dominio puede
    # contener cifras que no son años (ej. crc891.com).
    ruta = re.sub(r"^https?://[^/]+", "", link)
    texto = f"{titulo} {ruta}"
    anio_antiguo = _anio_antiguo_en(texto, anio_actual - 2)
    if anio_antiguo is None:
        return False
    hay_anio_reciente = re.search(
        rf"(?<!\d)({anio_actual}|{anio_actual - 1})(?!\d)", texto
    )
    return not hay_anio_reciente


# Fragmentos de URL propios de páginas de LISTADO, no de artículos:
# etiquetas, secciones, archivos, autores, resultados de búsqueda.
_RUTAS_DE_INDICE = (
    "/tag/", "/tags/", "/etiqueta/", "/etiquetas/",
    "/categoria/", "/categorias/", "/category/",
    "/seccion/", "/secciones/", "/section/",
    "/vertodos/", "/archivo/", "/archives/",
    "/autor/", "/author/", "/buscar/", "/search",
)


def _es_pagina_indice(item: Dict) -> bool:
    """
    True si el resultado es una página de listado (etiqueta, sección,
    archivo, búsqueda) en vez de una noticia.

    CASOS CONFIRMADOS (29-sep-2026, Nicaragua): el reporte incluyó dos
    entradas tituladas "Vienicsa" y "Económicas", que no eran notas
    sino la página de la etiqueta "vienicsa" de La Prensa
    (laprensani.com/tag/vienicsa) y el listado de la sección Económicas
    de El 19 Digital (.../articulos/vertodos/economicas?page=...).

    Aparecen sobre todo por la vía de organic_results: cuando la
    consulta es muy restrictiva, Google devuelve resultados web en vez
    de noticias, y ahí caben las páginas índice de los propios medios
    curados. El código ya preveía el caso en un comentario, pero no lo
    detectaba.

    Dos señales, cualquiera basta:

    1. La RUTA de la URL es de listado (ver _RUTAS_DE_INDICE), o lleva
       un parámetro de paginación (?page=, &page=).
    2. El TÍTULO tiene una o dos palabras Y la URL no parece la de un
       artículo. Las dos condiciones juntas, nunca una sola: un
       titular corto pero real existe ("Aumentan pensiones",
       "Retraite: réforme"), y descartarlo en duro por contar palabras
       perdería noticias buenas. La corroboración es que el último
       tramo de la URL no lleve guiones: los CMS generan los enlaces de
       artículo a partir del titular, así que casi siempre quedan
       como /aumentan-pensiones, mientras que una sección es
       /economicas a secas.

    Es un descarte DURO: una página de listado no es una noticia, y eso
    no es un juicio dudoso que convenga delegar en el verificador. Por
    eso las reglas son estrechas a propósito — de hecho, los dos casos
    confirmados de Nicaragua los atrapa ya la regla 1 sola.
    """
    link = (item.get("link") or "").lower()
    ruta = re.sub(r"^https?://[^/]+", "", link)

    if any(marca in ruta for marca in _RUTAS_DE_INDICE):
        return True
    if re.search(r"[?&]page=", ruta):
        return True

    titulo = (item.get("title") or "").strip()
    if titulo and len(titulo.split()) <= 2:
        tramos = [t for t in ruta.split("?")[0].split("/") if t]
        ultimo = tramos[-1] if tramos else ""
        parece_articulo = "-" in ultimo or "_" in ultimo
        if not parece_articulo:
            return True

    return False


def _dentro_del_rango(item: Dict, dias_maximos: int) -> bool:
    """
    Filtro de respaldo en Python: True si la noticia está dentro del
    rango de antigüedad permitido.

    Orden de confianza de las fuentes de fecha, de mayor a menor:

    1. La fecha incrustada en la URL, si existe. Es la que puso el
       propio medio al publicar y no depende del criterio de Google.
    2. El campo de fecha de SerpAPI (absoluto o relativo).
    3. Las señales de archivo antiguo (_parece_archivo_antiguo), que
       actúan cuando las dos anteriores no bastan o mienten.

    Si no se puede determinar la fecha por ningún medio, la noticia se
    deja pasar, para no descartar de más por un formato inesperado —
    pero la revisión de archivo antiguo se aplica igual.
    """
    limite = datetime.now(timezone.utc) - timedelta(days=dias_maximos)

    # 1. La URL manda sobre lo que diga Google.
    fecha_url = _fecha_desde_url(item.get("link", ""))
    if fecha_url is not None:
        return fecha_url >= limite

    # 3. Sin fecha en la URL, las señales de archivo pesan: una página
    #    de 2018 que Google fecha como de esta semana se descarta aquí.
    if _parece_archivo_antiguo(item):
        return False

    # 2. Fecha reportada por SerpAPI.
    fecha = _parsear_fecha_serpapi(item)
    if fecha is None:
        return True
    return fecha >= limite


def _es_error_de_tiempo_agotado(error: Optional[str]) -> bool:
    """
    True si el error de SerpAPI fue un tiempo de espera agotado.

    Importa distinguirlo porque, a diferencia de un fallo de red
    cualquiera, este NO se arregla repitiendo la misma consulta: las
    consultas largas con el operador site: en la pestaña de Noticias
    son justamente las que se quedan colgadas (incidencia de SerpAPI
    del 20-sep-2026, y el caso de México del 30-sep). Lo que sí ayuda
    es volver a preguntar con una consulta más corta.
    """
    if not error:
        return False
    texto = error.lower()
    return "timed out" in texto or "timeout" in texto


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
        "q": query,
        "gl": _codigo_pais(pais),
        "hl": idioma_busqueda,
        "tbs": rango_tiempo,
        "tbm": "nws",
        "api_key": api_key,
    }

    # Reintento ante fallos transitorios de red. Confirmado en producción:
    # República Dominicana falló con "Read timed out (read timeout=20)" y se
    # resolvió con un simple clic en "Regenerar". Con 10 países por
    # ejecución, ese tipo de tropiezo pasajero aparece cada tanto y dejaba
    # al país entero sin noticias hasta que alguien lo reintentara a mano.
    # Dos intentos con una pausa corta lo absorben solos; si el segundo
    # también falla, el error es real y se reporta como antes.
    data = None
    ultimo_error_red = None
    for intento in range(2):
        try:
            resp = requests.get(SERPAPI_ENDPOINT, params=params, timeout=25)
            resp.raise_for_status()
            data = resp.json()
            break
        except requests.exceptions.RequestException as e:
            ultimo_error_red = e
            if intento == 0:
                time.sleep(2)

    if data is None:
        return {"aceptadas": [], "descartadas_marginales": [],
                "error": f"Error de conexión con SerpAPI: {ultimo_error_red}"}

    if "error" in data:
        mensaje = data["error"]
        # "Google hasn't returned any results" NO es un error técnico —
        # es simplemente que no hay resultados para esa query esta semana.
        # Se trata como lista vacía para que el sistema continúe a la
        # capa de respaldo (anclas de texto) en vez de detenerse aquí.
        if "hasn't returned any results" in mensaje or "no results" in mensaje.lower():
            return {"aceptadas": [], "descartadas_marginales": [], "error": None}
        return {"aceptadas": [], "descartadas_marginales": [], "error": mensaje}

    noticias_crudas = data.get("news_results", [])

    # Respaldo con resultados web (organic_results).
    #
    # Cuando la consulta es muy restrictiva —como la de la capa 1, que
    # limita a 4-6 medios con site:— Google a veces decide que no hay
    # suficientes resultados en su pestaña de Noticias y devuelve
    # resultados web en su lugar: "news_results_state": "Fully empty"
    # y un bloque "organic_results". Confirmado el 21-sep-2026 con la
    # consulta real de Costa Rica: 0 news_results y 10 organic_results,
    # todos de los medios curados y sobre el tema (Fodesaf, JUPEMA,
    # huelga de la CCSS). Como el código solo leía news_results, esa
    # cosecha se descartaba entera y la capa 1 quedaba en cero.
    #
    # Solo se usan si no hubo news_results, y solo los que traen fecha:
    # un resultado web sin fecha suele ser una página permanente
    # (secciones, índices) y no una noticia publicada esta semana.
    #
    # IMPORTANTE: estos resultados NUNCA se aceptan directamente, entran
    # siempre como "descartadas marginales" para que el verificador de
    # Groq los revise uno por uno. Google mismo indicó que no son
    # noticias, así que son evidencia de segunda: en la prueba real
    # venían mezclados cuatro casos de mención tangencial (una nota de
    # farándula que cita "seguridad social" al pasar, el calendario del
    # aguinaldo, un análisis electoral que menciona el Índice de
    # Desarrollo Social, y una página índice de sección). Los filtros de
    # palabras clave no distinguen eso; el verificador sí, porque su
    # prompt rechaza explícitamente las menciones tangenciales y la
    # farándula. Aceptarlos sin verificar llenaría el cupo con ruido y,
    # de paso, impediría que el verificador llegara a actuar.
    es_respaldo_web = False
    if not noticias_crudas:
        noticias_crudas = [
            item for item in data.get("organic_results", [])
            if item.get("date")
        ]
        es_respaldo_web = bool(noticias_crudas)

    # Filtros DUROS, sin clasificar — estas noticias jamás llegan ni
    # siquiera a descartadas_marginales, porque el verificador LLM no
    # debe poder "rescatarlas":
    #  - fecha fuera de rango (no tiene sentido rescatar algo viejo);
    #  - dominio curado de OTRO país (certeza total del país real: si
    #    diariolibre.com está curado para República Dominicana, una
    #    noticia suya nunca pertenece al reporte de Haití).
    #  - publicada en un dominio nacional de otro país sin nombrar ni
    #    una vez al país buscado (ver _es_de_otro_pais_con_certeza): el
    #    verificador LLM cae en las mismas trampas de topónimo que los
    #    filtros de texto, así que este caso no puede quedar a su juicio.
    #  - página de listado en vez de noticia (ver _es_pagina_indice).
    noticias_crudas = [
        item for item in noticias_crudas
        if _dentro_del_rango(item, dias_maximos_antiguedad)
        and not _es_pagina_indice(item)
        and not _dominio_curado_de_otro_pais(item, pais)
        and not _es_de_otro_pais_con_certeza(item, pais)
    ]

    def _convertir(item: Dict, motivo: Optional[str] = None) -> Dict:
        snippet = reparar_mojibake(item.get("snippet", ""))
        convertida = {
            "pais": pais,
            # El título se repara aquí, en la puerta de entrada, para
            # que todo lo de aguas abajo (editor, resumen, documento)
            # trabaje ya con el titular completo y bien codificado.
            "titulo": limpiar_titulo(item.get("title", "Sin título"),
                                     item.get("link", ""), snippet),
            "fuente": _extraer_fuente(item),
            "fecha": item.get("date", "Fecha no disponible"),
            "snippet": snippet,
            "link": item.get("link", ""),
        }
        # El motivo por el que una noticia quedó marginal determina
        # cuánto conviene confiar en ella si luego hay que rescatarla
        # (ver PRIORIDAD_MOTIVO_MARGINAL y summarizer). No es solo para
        # diagnóstico: cambia el orden en que el verificador las revisa.
        if motivo:
            convertida["_motivo_marginal"] = motivo
        return convertida

    aceptadas = []
    descartadas_marginales = []
    for item in noticias_crudas:
        # Prueba de pertenencia al país: o bien el medio que publica está
        # curado para este país (prueba por dominio), o bien el texto
        # nombra al país explícitamente (prueba por contenido). Si no se
        # cumple ninguna, no hay evidencia de que la noticia sea del país
        # y se manda al verificador en vez de aceptarla.
        #
        # Confirmado el 21-sep-2026: en el reporte de El Salvador se coló
        # "Centro de Asistencia Social de Benito Juárez mantiene bajo
        # resguardo a 32 menores migrantes", publicada por un medio de
        # Quintana Roo (México) en un dominio .com. No la atrapaba ningún
        # filtro: el TLD es genérico, el medio no está en las listas
        # curadas, no menciona "México" ni "mexicano", y "Quintana Roo"
        # no figura entre las subdivisiones de riesgo. Pero tampoco
        # menciona "El Salvador" ni "salvadoreño" por ningún lado, que es
        # justo lo que esta regla exige.
        de_medio_curado = _es_dominio_curado_del_pais(item, pais)

        sin_evidencia_de_pais = (
            not de_medio_curado
            and not _menciona_el_pais(item, pais)
        )

        # Los medios curados se aceptan con el filtro temático normal
        # (título o snippet). Para los demás se exige la señal fuerte:
        # el tema en el TÍTULO. Sin esa exigencia entraban noticias de
        # otro asunto que solo rozaban el tema en el snippet — ver
        # _tema_en_el_titulo. No aceptarlas no las pierde: pasan al
        # verificador, que decide con criterio en vez de por palabra.
        tema_demasiado_debil = not de_medio_curado and not _tema_en_el_titulo(item)

        # El ORDEN importa: el primer motivo que se cumple es el que
        # queda registrado, y de él depende la prioridad con que el
        # verificador revisará la noticia si hace falta rescatarla.
        # Los motivos de país van antes que los de tema, porque el
        # verificador juzga bien el país y ha demostrado ser demasiado
        # generoso con el tema (ver PRIORIDAD_MOTIVO_MARGINAL).
        if not _es_relevante_al_tema(item):
            motivo = "tema_ausente"
        elif _menciona_otro_pais(item, pais):
            motivo = "menciona_otro_pais"
        elif _dominio_de_otro_pais(item, pais):
            motivo = "dominio_de_otro_pais"
        elif _menciona_subdivision_de_riesgo(item, pais):
            motivo = "subdivision_de_otro_pais"
        elif _menciona_senal_de_otro_pais(item, pais):
            motivo = "senal_de_otro_pais"
        elif sin_evidencia_de_pais:
            motivo = "sin_evidencia_de_pais"
        elif _es_evento_ceremonial(item):
            motivo = "evento_ceremonial"
        elif tema_demasiado_debil:
            motivo = "tema_solo_en_extracto"
        elif es_respaldo_web:
            # Resultado web, no noticia: Google mismo dijo que no es
            # prensa, así que lo revisa siempre el verificador.
            motivo = "resultado_web"
        else:
            motivo = None

        if motivo:
            descartadas_marginales.append(_convertir(item, motivo=motivo))
        else:
            aceptadas.append(_convertir(item))

    # Deduplicar por link y por similitud de título DENTRO de la misma
    # búsqueda: Google News frecuentemente devuelve dos artículos del
    # mismo evento (mismo medio, días consecutivos) con links distintos.
    aceptadas = deduplicar_noticias(aceptadas)

    return {
        "aceptadas": aceptadas[:max_resultados],
        "descartadas_marginales": descartadas_marginales[:max_resultados],
        "error": None,
    }


def _buscar_prensa_pais(
    pais: str,
    api_key: str,
    terminos: Optional[List[str]] = None,
    max_resultados: int = 10,
    rango_tiempo: str = "qdr:w",  # qdr:w = última semana (filtro de SerpAPI)
    dias_maximos_antiguedad: int = DIAS_MAXIMOS_ANTIGUEDAD,
    n_noticias_necesarias: int = 5,
) -> Dict:
    """
    Busca noticias recientes de PRENSA para un país usando SerpAPI, con
    una estrategia en capas. El punto de entrada público es
    buscar_noticias_pais.

    Estrategia:

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
        """
        Aplica el fallback de 1 semana -> 2 semanas para una query dada.

        Se amplía la ventana solo cuando la capa no trajo NINGUNA
        noticia aceptada. Ampliar también cuando el país se queda corto
        se probó y se descartó: dispararía una búsqueda extra en casi
        todos los países y duplicaría el consumo de SerpAPI, que es el
        recurso más escaso del proyecto.
        """
        resultado = _buscar_una_vez(pais, api_key, query, rango_tiempo, max_resultados, dias_maximos_antiguedad)
        if resultado["error"] is not None:
            return resultado
        if resultado["aceptadas"] or rango_tiempo != "qdr:w":
            return resultado

        resultado_2sem = _buscar_una_vez(pais, api_key, query, "qdr:w2", max_resultados, dias_maximos_antiguedad=14)
        if resultado_2sem["error"] is not None:
            # La ampliación falló, pero lo de una semana sigue sirviendo.
            return resultado

        # Se COMBINAN las dos cosechas, no se sustituye una por otra.
        # Antes se devolvía solo la de dos semanas y se tiraban las
        # aceptadas de una semana. Hoy eso es inocuo, porque solo se
        # llega aquí con cero aceptadas y por tanto no hay nada que
        # perder — pero era una bomba de relojería: en cuanto alguien
        # ampliara el disparador (por ejemplo a "el país se quedó
        # corto"), el código habría empezado a descartar noticias en
        # silencio. Combinar cuesta lo mismo y quita el riesgo.
        return {
            "aceptadas": deduplicar_noticias(
                resultado["aceptadas"] + resultado_2sem["aceptadas"]
            ),
            "descartadas_marginales": (
                resultado["descartadas_marginales"]
                + resultado_2sem["descartadas_marginales"]
            ),
            "error": None,
        }

    # Capa 1: query con site: (estrategia principal)
    query_site = construir_query_site(pais, terminos)
    resultado = _buscar_con_fallback_fecha(query_site)

    # Si se agotó el tiempo de espera, se reintenta UNA vez con una
    # consulta más corta, no con la misma. Repetir una consulta que
    # acaba de quedarse colgada rara vez funciona: lo que se cuelga son
    # las consultas largas con el operador site: en la pestaña de
    # Noticias. Confirmado el 30-sep-2026 con México, cuya consulta
    # mide 327 caracteres. Se recorta por los dos lados —dos términos
    # temáticos y cuatro medios— porque el grueso de la longitud son
    # los dominios, no los términos. La versión corta cubre menos
    # medios, pero cubrir menos es mejor que no cubrir nada, y la capa
    # 2 sigue actuando después.
    if _es_error_de_tiempo_agotado(resultado["error"]):
        resultado = _buscar_con_fallback_fecha(
            construir_query_site(pais, terminos, max_terminos=2, max_sitios=4)
        )

    # Si la capa 1 falló, NO se abandona el país: se intenta igual la
    # capa 2, cuya consulta es mucho más simple (sin el operador
    # "site:"). Motivo confirmado en producción el 20-sep-2026: SerpAPI
    # tuvo una incidencia abierta ("requests timing out while using
    # tbm=nws with advanced parameters" / "searches with advanced
    # operators time out intermittently") que hacía fallar justamente
    # las consultas con site:, mientras las simples seguían
    # respondiendo. Con el comportamiento anterior —abandonar el país
    # ante cualquier error de la capa 1— los 10 países quedaban vacíos
    # aunque la capa 2 hubiera funcionado. El error de la capa 1 se
    # recuerda por si la capa 2 también falla.
    error_capa_1 = resultado["error"]

    if error_capa_1 is None and len(resultado["aceptadas"]) >= n_noticias_necesarias:
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
        # La capa 2 también falló. Si la capa 1 había funcionado, se
        # devuelve lo suyo en vez de perderlo todo; si ambas fallaron,
        # entonces sí es un error real y se reporta.
        if error_capa_1 is not None:
            return {"aceptadas": [], "descartadas_marginales": [], "error": error_capa_1}
        return resultado

    # Combinar aceptadas de ambas capas, deduplicando tanto por link
    # exacto como por similitud de título (el mismo evento puede llegar
    # por ambas búsquedas como artículos distintos con links distintos).
    aceptadas_combinadas = deduplicar_noticias(
        resultado["aceptadas"] + resultado_anclas["aceptadas"]
    )

    descartadas_combinadas = resultado["descartadas_marginales"] + resultado_anclas["descartadas_marginales"]

    return {
        "aceptadas": aceptadas_combinadas[:max_resultados],
        "descartadas_marginales": descartadas_combinadas[:max_resultados],
        "error": None,
    }


def buscar_noticias_pais(
    pais: str,
    api_key: str,
    terminos: Optional[List[str]] = None,
    max_resultados: int = 10,
    rango_tiempo: str = "qdr:w",
    dias_maximos_antiguedad: int = DIAS_MAXIMOS_ANTIGUEDAD,
    n_noticias_necesarias: int = 5,
) -> Dict:
    """
    Punto de entrada del Agente 1: la estrategia en capas sobre la
    prensa nacional (ver _buscar_prensa_pais).
    """
    return _buscar_prensa_pais(
        pais=pais,
        api_key=api_key,
        terminos=terminos,
        max_resultados=max_resultados,
        rango_tiempo=rango_tiempo,
        dias_maximos_antiguedad=dias_maximos_antiguedad,
        n_noticias_necesarias=n_noticias_necesarias,
    )


# ---------------------------------------------------------------------------
# REPARACIÓN DEL TÍTULO
# ---------------------------------------------------------------------------

def reparar_mojibake(texto: str) -> str:
    """
    Repara el texto que llegó en UTF-8 pero fue leído como Latin-1.

    CASO CONFIRMADO (29-sep-2026, México): el reporte publicó "Sigue
    Coahuila sumando establecimientos a la cruzada por la inclusiÃ³n".
    Esa "Ã³" son los dos bytes de la "ó" interpretados de uno en uno.
    Viene así desde la fuente, no lo produce esta app, pero queda
    igualmente mal en un documento institucional.

    Solo se toca el texto si la conversión de vuelta funciona Y deja un
    resultado con menos secuencias raras: si el texto estaba bien, esta
    función lo devuelve intacto.
    """
    if not texto or "Ã" not in texto and "Â" not in texto:
        return texto
    try:
        reparado = texto.encode("latin-1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return texto
    if reparado.count("Ã") + reparado.count("Â") < texto.count("Ã") + texto.count("Â"):
        return reparado
    return texto


_PALABRAS_TITULO_DESDE_URL = re.compile(r"[a-z0-9áéíóúñü]+", re.IGNORECASE)


def _palabras_del_slug(link: str) -> List[str]:
    """Palabras del último tramo de la URL, que suele ser el titular."""
    ruta = re.sub(r"^https?://[^/]+", "", (link or "").lower()).split("?")[0]
    tramos = [t for t in ruta.split("/") if t]
    if not tramos:
        return []
    # Muchos medios cuelgan el identificador de la nota en un tramo
    # aparte, después del slug (".../a-agosto-de-2026/858497"). Si el
    # último tramo es solo un número, el titular está en el anterior.
    slug = tramos[-1]
    if re.fullmatch(r"\d+", slug) and len(tramos) > 1:
        slug = tramos[-2]
    # Quitar extensión y los identificadores numéricos del final, que
    # los CMS añaden al slug ("...-20260928-0086.html", "...-893510").
    slug = re.sub(r"\.(html?|php|aspx?)$", "", slug)
    palabras = [p for p in slug.split("-") if p]
    # Quitar los identificadores que los CMS pegan al final del slug
    # ("...-893510", "...-20260928-0086"), pero NO un año, que suele
    # formar parte del titular ("...-a-agosto-de-2026"). Se reconoce un
    # año por estar en un rango razonable y tener cuatro cifras.
    def _es_anio(token: str) -> bool:
        return len(token) == 4 and token.isdigit() and 1900 <= int(token) <= 2100

    while palabras and palabras[-1].isdigit() and not _es_anio(palabras[-1]):
        palabras.pop()
    return palabras


def _restaurar_acentos(palabra: str, snippet: str) -> str:
    """
    Si en el extracto aparece la misma palabra pero acentuada, usa esa.

    El slug de una URL viene sin tildes, así que el trozo de titular
    que se recupera de ahí saldría como "dias" o "modificacion". El
    extracto de la misma noticia suele traer esas palabras bien
    escritas, y es una fuente fiable: no se inventa nada, se copia de
    lo que el propio medio publicó.
    """
    for candidata in _PALABRAS_TITULO_DESDE_URL.findall(snippet or ""):
        if candidata.lower() != palabra and _quitar_tildes(candidata.lower()) == palabra:
            return candidata.lower()
    return palabra


def completar_titulo_truncado(titulo: str, link: str, snippet: str = "") -> str:
    """
    Reconstruye un titular que Google cortó con puntos suspensivos.

    CASO CONFIRMADO (29-sep-2026, El Salvador): las cuatro noticias del
    país salieron con títulos como "Piden a la OIT observar proceso de
    modificación ...". Google trunca los titulares largos en su pestaña
    de Noticias.

    La pieza que faltaba estaba a la vista: **el titular completo está
    en la URL**, porque los gestores de contenido generan el enlace a
    partir de él. De
    ".../piden-a-la-oit-observar-proceso-de-modificacion-de-jornada-laboral"
    se recupera el final que Google se comió.

    Se conserva el trozo original —que viene bien escrito, con tildes y
    mayúsculas— y solo se añade lo que falta, tomado del slug y con las
    tildes restauradas desde el extracto cuando aparecen allí. Si no se
    puede reconstruir con confianza, se devuelve el título tal cual: es
    preferible un titular cortado a uno inventado.
    """
    if not titulo:
        return titulo
    limpio = titulo.rstrip()
    if not limpio.endswith(("...", "…", ".. .")):
        return titulo
    prefijo = limpio.rstrip(". …").rstrip()
    if not prefijo:
        return titulo

    palabras_slug = _palabras_del_slug(link)
    if len(palabras_slug) < 3:
        return titulo

    # Alinear: buscar dónde termina el prefijo dentro del slug.
    palabras_prefijo = [
        _quitar_tildes(p.lower())
        for p in _PALABRAS_TITULO_DESDE_URL.findall(prefijo)
    ]
    if not palabras_prefijo:
        return titulo

    # La última palabra del prefijo debe aparecer en el slug, y el
    # solapamiento tiene que ser alto: si no, el slug no corresponde al
    # titular (páginas con enlaces genéricos) y no se toca nada.
    comunes = sum(1 for p in palabras_prefijo if p in palabras_slug)
    if comunes < max(2, int(len(palabras_prefijo) * 0.6)):
        return titulo

    ultima = palabras_prefijo[-1]
    if ultima not in palabras_slug:
        return titulo
    corte = len(palabras_slug) - 1 - palabras_slug[::-1].index(ultima)
    cola = palabras_slug[corte + 1:]
    if not cola:
        return titulo

    cola_legible = " ".join(_restaurar_acentos(p, snippet) for p in cola)
    return f"{prefijo} {cola_legible}"


def limpiar_titulo(titulo: str, link: str, snippet: str = "") -> str:
    """Repara la codificación y completa el titular si venía cortado."""
    return completar_titulo_truncado(reparar_mojibake(titulo), link, snippet)


def _extraer_fuente(item: Dict) -> str:
    """
    Nombre del medio. SerpAPI a veces lo anida en 'source': {'name':...}.

    Los resultados WEB (organic_results), que es lo que llega cuando
    Google contesta con resultados web en vez de noticias, con
    frecuencia no traen 'source' y salían en el reporte como "Fuente
    desconocida". Si falta, se deduce del dominio del enlace.
    """
    source = item.get("source")
    if isinstance(source, dict) and source.get("name"):
        return source["name"]
    if isinstance(source, str) and source.strip():
        return source

    link = item.get("link") or ""
    dominio = urlparse(link).netloc.lower()
    if dominio.startswith("www."):
        dominio = dominio[4:]
    return dominio or "Fuente desconocida"


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
    "veracruz": "México",         # confirmado: coló en reporte de Honduras (24-jun-2026)
    "valladolid": "España",       # confirmado: coló en reporte de El Salvador (17-jul-2026)
    "castilla y león": "España",  # región de Valladolid, mismo caso confirmado
    # Regiones/ciudades españolas grandes, agregadas preventivamente tras el
    # caso confirmado de Valladolid: España no tiene demónimo utilizable
    # ("español" = idioma) ni TLD frecuente en Google News (.com abundan),
    # así que las subdivisiones son su señal de detección principal.
    "cataluña": "España",
    "andalucía": "España",
    "galicia": "España",
    "país vasco": "España",
    "comunidad de madrid": "España",
    "castilla-la mancha": "España",
    "extremadura": "España",

    # ---------------------------------------------------------------
    # Marcadores de los topónimos que se llaman EXACTAMENTE igual que un
    # país del proyecto (29-sep-2026).
    # ---------------------------------------------------------------
    # Estos no se pueden enmascarar como los de TOPONIMOS_HOMONIMOS: el
    # lugar se llama literalmente "El Salvador" o "Costa Rica", así que
    # borrar esa cadena rompería también las menciones legítimas. Lo que
    # sí es inequívoco es el territorio que los rodea, y eso es lo que
    # se registra aquí. Verificado con fuentes.
    "diego de almagro": "Chile",   # comuna del pueblo minero "El Salvador", Atacama
    "codelco": "Chile",            # opera la División Salvador
    "atacama": "Chile",
    "guantánamo": "Cuba",          # municipio "El Salvador", Guantánamo
    "guantanamo": "Cuba",
    "mayarí": "Cuba",              # localidad "Guatemala", Holguín
    "holguín": "Cuba",
    "zacatecas": "México",         # municipio "El Salvador", Zacatecas
    "culiacán": "México",          # sindicatura "Costa Rica", Culiacán
    "culiacan": "México",
    "sinaloa": "México",
    "pereira": "Colombia",         # comuna "Cuba", Pereira
    "risaralda": "Colombia",
    "el tambo": "Colombia",        # corregimiento "Honduras", Cauca
    "cauca": "Colombia",
    "arauquita": "Colombia",       # corregimiento "Panamá de Arauca"
    "mato grosso": "Brasil",       # municipio "Costa Rica", Mato Grosso do Sul
    "goiás": "Brasil",             # municipio "Panamá", Goiás
    "misamis oriental": "Filipinas",   # "El Salvador City"
    "cagayán de oro": "Filipinas",
    "pampanga": "Filipinas",       # municipio "Mexico", Pampanga
}

# Señales textuales que delatan el país real de una noticia aunque el
# texto nunca lo nombre explícitamente: monedas, prefijos monetarios,
# formatos locales. Confirmado con el caso "RD$15.8 millones" (pesos
# dominicanos) que coló en el reporte de Haití (17-jul-2026) — el texto
# jamás decía "dominicano", pero "RD$" solo puede ser República
# Dominicana. Mapeo señal -> país real. Las señales se buscan como
# subcadena en minúsculas (no word-boundary, porque símbolos como "$"
# no funcionan con \b).
SENALES_TEXTUALES_PAIS = {
    "rd$": "República Dominicana",   # pesos dominicanos
    "euros": "España",                # única economía en euros que genera ruido aquí
    "€": "España",
}


def _menciona_senal_de_otro_pais(item: Dict, pais_buscado: str) -> bool:
    """
    True si el título o snippet contiene una señal textual (moneda,
    formato local) de un país DISTINTO al buscado. Complementa a
    _menciona_otro_pais para noticias que nunca nombran su país porque
    es obvio para sus lectores locales (ej. "RD$15.8 millones").
    """
    texto = f"{item.get('title', '')} {item.get('snippet', '')}".lower()
    for senal, pais_real in SENALES_TEXTUALES_PAIS.items():
        if pais_real == pais_buscado:
            continue
        if senal in texto:
            return True
    return False


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


def _palabras_significativas(titulo: str) -> set:
    """Conjunto de palabras normalizadas (sin tildes, minúsculas, >3
    letras) de un título, para comparar similitud entre noticias."""
    import unicodedata
    sin_tildes = unicodedata.normalize("NFKD", titulo or "")
    sin_tildes = "".join(c for c in sin_tildes if not unicodedata.combining(c))
    palabras = re.findall(r"[a-záéíóúñü]+", sin_tildes.lower())
    return {p for p in palabras if len(p) > 3}


def titulos_similares(titulo_a: str, titulo_b: str, umbral: float = 0.6) -> bool:
    """
    True si dos títulos describen con alta probabilidad el mismo evento,
    usando el coeficiente de solapamiento (intersección / tamaño del
    conjunto menor) sobre palabras significativas. Se usa el coeficiente
    de solapamiento y no Jaccard porque dos titulares del mismo evento
    suelen compartir el núcleo ("derechos laborales buzos misquitos")
    pero uno puede ser mucho más largo que el otro, lo que hunde el
    Jaccard sin que dejen de ser la misma noticia.

    Caso confirmado (17-jul-2026, Honduras): "Gobierno instala mesa de
    seguimiento a derechos laborales para buzos misquitos" y "Pretenden
    garantizar derechos laborales de buzos misquitos" — links distintos,
    mismo evento, publicados por el mismo medio con un día de
    diferencia. La deduplicación por link no los atrapa.
    """
    a = _palabras_significativas(titulo_a)
    b = _palabras_significativas(titulo_b)
    if not a or not b:
        return False
    solapamiento = len(a & b) / min(len(a), len(b))
    return solapamiento >= umbral


def deduplicar_noticias(noticias: List[Dict]) -> List[Dict]:
    """
    Elimina duplicados de una lista de noticias, en dos niveles:
    por link exacto y por similitud de título (mismo evento cubierto en
    artículos distintos). Conserva la primera aparición de cada una —
    como las listas vienen ordenadas por relevancia/recencia de Google,
    la primera suele ser la mejor versión.
    """
    resultado: List[Dict] = []
    links_vistos: set = set()
    for noticia in noticias:
        link = noticia.get("link", "")
        if link and link in links_vistos:
            continue
        if any(titulos_similares(noticia.get("titulo") or noticia.get("title", ""),
                                 previa.get("titulo") or previa.get("title", ""))
               for previa in resultado):
            continue
        resultado.append(noticia)
        if link:
            links_vistos.add(link)
    return resultado


# Mapa dominio -> país, derivado AUTOMÁTICAMENTE de SITIOS_PAIS. Si un
# dominio está curado como medio de prensa del país X, una noticia suya
# jamás puede pertenecer al reporte del país Y — es la señal de país más
# confiable que existe (más que el texto y más que el TLD). Confirmado
# con el caso diariolibre.com (curado para República Dominicana) que
# coló en el reporte de Haití (17-jul-2026) por la capa de anclas de
# texto. Al derivarse de SITIOS_PAIS, este filtro no requiere ningún
# mantenimiento propio: cada medio agregado a la lista de un país queda
# automáticamente vetado para los otros nueve.
_DOMINIO_CURADO_A_PAIS = {
    dominio: pais
    for pais, dominios in SITIOS_PAIS.items()
    for dominio in dominios
}


def _es_dominio_curado_del_pais(item: Dict, pais_buscado: str) -> bool:
    """True si el link pertenece a un medio curado DEL país buscado."""
    link = item.get("link", "")
    if not link:
        return False
    netloc = urlparse(link).netloc.lower()
    if netloc.startswith("www."):
        netloc = netloc[4:]
    for dominio in SITIOS_PAIS.get(pais_buscado, []):
        if netloc == dominio or netloc.endswith("." + dominio):
            return True
    return False


# Variantes adicionales del nombre de un país que aparecen en la prensa
# y no se derivan del nombre en español ni de los demónimos.
_NOMBRES_ALTERNOS_PAIS = {
    "Haití": ["haïti", "haiti"],            # grafía francesa y sin tilde
    "República Dominicana": ["rd", "quisqueya"],
    "México": ["cdmx", "mexico"],
    "Panamá": ["panama"],
}


# ---------------------------------------------------------------------------
# TOPÓNIMOS HOMÓNIMOS: lugares de OTROS países cuyo nombre CONTIENE el
# nombre de un país del proyecto.
# ---------------------------------------------------------------------------
# Problema de fondo, confirmado el 29-sep-2026: en el reporte de El
# Salvador entró "Emprendedoras de Ate y VES logran incentivos por
# S/ 65,000" (Agencia Andina, andina.pe), una nota de PERÚ. El texto
# hablaba de "Villa El Salvador", que es un distrito de Lima de unos
# 400.000 habitantes. El filtro _menciona_el_pais buscaba "el salvador"
# como palabra completa y lo encontraba —dentro del nombre de otro
# lugar—, así que la nota pasaba la prueba de país.
#
# Es un fallo de clase, no un caso aislado: "Nuevo México" es un estado
# de Estados Unidos, "Panama City" está en Florida, hay una comuna
# llamada Cuba en Pereira (Colombia) y un corregimiento llamado Honduras
# en el Cauca (Colombia). Por eso no se corrige añadiendo "Villa El
# Salvador" a una lista de exclusión, sino ENMASCARANDO el topónimo
# antes de buscar el nombre del país: donde el texto diga "Villa El
# Salvador" ya no queda ningún "El Salvador" que encontrar.
#
# El enmascarado es superior a excluir la noticia entera porque no
# pierde las menciones legítimas: una nota que hable de "Villa El
# Salvador" Y de "El Salvador" conserva la segunda mención, que sí
# cuenta como evidencia.
#
# Solo entran aquí topónimos en los que el nombre del país aparece
# dentro de una expresión MÁS LARGA e inequívoca. Los casos en que el
# topónimo se llama exactamente igual que el país (el municipio El
# Salvador de Guantánamo, en Cuba; la sindicatura Costa Rica de
# Culiacán, en México) no se pueden enmascarar sin romper las menciones
# reales: esos se detectan por sus marcadores geográficos, en
# SUBDIVISIONES_DE_RIESGO_CONFIRMADAS.
#
# Verificado con fuentes el 29-sep-2026. Mapeo: topónimo -> país real.
TOPONIMOS_HOMONIMOS = {
    # El Salvador
    "villa el salvador": "Perú",          # distrito de Lima (~400.000 hab.) — CASO CONFIRMADO
    "el salvador city": "Filipinas",      # Misamis Oriental
    # México
    "nuevo méxico": "Estados Unidos",
    "nuevo mexico": "Estados Unidos",
    "new mexico": "Estados Unidos",
    # Panamá
    "panama city": "Estados Unidos",      # Florida (la capital real es "Ciudad de Panamá")
    "panamá de arauca": "Colombia",       # corregimiento de Arauquita
    # Cuba
    "cuba street": "Nueva Zelanda",       # calle célebre de Wellington
    "barrio cuba": "Colombia",            # comuna 19 de Pereira
    "comuna cuba": "Colombia",
}

# Se enmascaran primero los más largos, para que un topónimo contenido
# en otro no se coma al mayor.
_TOPONIMOS_ORDENADOS = sorted(TOPONIMOS_HOMONIMOS, key=len, reverse=True)

# Marcador sin ningún nombre de país dentro, para no crear coincidencias
# nuevas al sustituir.
_MARCA_TOPONIMO = " toponimohomonimo "


def _enmascarar_toponimos(texto_lower: str):
    """
    Sustituye en el texto los topónimos homónimos por un marcador neutro.

    Devuelve (texto_enmascarado, países_delatados), donde
    países_delatados son los países REALES a los que pertenecen los
    topónimos encontrados. Ese segundo valor importa tanto como el
    primero: "Villa El Salvador" no solo deja de ser evidencia de El
    Salvador, además es evidencia positiva de que la noticia es de Perú.
    """
    delatados = set()
    for toponimo in _TOPONIMOS_ORDENADOS:
        patron = r"\b" + re.escape(toponimo) + r"\b"
        if re.search(patron, texto_lower):
            delatados.add(TOPONIMOS_HOMONIMOS[toponimo])
            texto_lower = re.sub(patron, _MARCA_TOPONIMO, texto_lower)
    return texto_lower, delatados


def _texto_de_pais(item: Dict):
    """Texto normalizado y enmascarado que usan todos los filtros de país."""
    crudo = f"{item.get('title', '')} {item.get('snippet', '')}".lower()
    return _enmascarar_toponimos(crudo)


def _menciona_el_pais(item: Dict, pais_buscado: str) -> bool:
    """
    True si el título o snippet nombra explícitamente al país buscado,
    por su nombre, su demónimo o alguna variante habitual en prensa.

    Se busca sobre el texto CON LOS TOPÓNIMOS HOMÓNIMOS ENMASCARADOS
    (ver TOPONIMOS_HOMONIMOS): el nombre de un país dentro del nombre de
    otro lugar no prueba nada sobre el origen de la noticia.
    """
    texto, _ = _texto_de_pais(item)
    candidatos = (
        [pais_buscado.lower()]
        + [d.lower() for d in DEMONIMOS_PAIS.get(pais_buscado, [])]
        + _NOMBRES_ALTERNOS_PAIS.get(pais_buscado, [])
    )
    return any(
        re.search(r"\b" + re.escape(c) + r"\b", texto)
        for c in candidatos
    )


# Actos festivos, ceremoniales o deportivos. Cuando uno de estos es el
# asunto del titular, la institución de protección social suele ser
# solo la SEDE o la anfitriona del acto, no el tema de la noticia.
#
# CASO CONFIRMADO (29-sep-2026, México): "Celebra IMSS Veracruz Norte
# Fiestas Patrias 2026 en Centro de Seguridad Social Xalapa". Pasó
# todos los filtros con holgura, porque "seguridad social" e "IMSS"
# están literalmente en el titular. Y lo están: es el nombre del lugar
# y el de la institución que organiza la fiesta. La noticia trata de
# una celebración patria.
#
# Se buscan solo en el TÍTULO: en el cuerpo de una nota legítima es
# normal mencionar de pasada un aniversario o un acto. Y NO se
# descarta en duro, solo se manda al verificador: hay actos
# ceremoniales que sí son noticia del tema (la firma de un convenio en
# un acto público, por ejemplo), y esa distinción necesita criterio.
EVENTOS_CEREMONIALES = [
    "fiestas patrias", "mes de la independencia", "desfile", "desfiles",
    "verbena", "kermés", "kermes", "posada", "posadas",
    "festival", "feria patronal", "carnaval",
    "misa", "romería", "romeria",
    "concurso de belleza", "reina del", "certamen",
    "torneo", "campeonato", "maratón", "maraton", "carrera atlética",
    "gala", "coctel", "cóctel",
]


def _es_evento_ceremonial(item: Dict) -> bool:
    """
    True si el TÍTULO indica que la noticia cubre un acto festivo,
    ceremonial o deportivo. Ver EVENTOS_CEREMONIALES.
    """
    titulo = (item.get("title") or "").lower()
    return any(
        re.search(r"\b" + re.escape(evento) + r"\b", titulo)
        for evento in EVENTOS_CEREMONIALES
    )


# Cuánto merece confiarse en una noticia marginal cuando hay que
# rescatarla para completar el cupo. Número más bajo = se revisa antes.
#
# La razón de que exista este orden: el 29-sep-2026 el reporte de
# Honduras incluyó "Instituciones que persiguen el crimen priorizan
# desalojos frente a otros delitos", una nota de seguridad y justicia
# sin ninguna palabra del tema. Había quedado marginal por
# "tema_ausente", el verificador la revisó para llenar el quinto hueco
# y dijo que sí.
#
# El verificador juzga bien el PAÍS —esa pregunta es objetiva— pero ha
# demostrado ser demasiado generoso con el TEMA. Así que las dudosas
# por país se le ofrecen primero, y las que no tienen ni una palabra
# del tema quedan al final de la cola: solo se miran si de verdad no
# hay nada mejor.
PRIORIDAD_MOTIVO_MARGINAL = {
    "sin_evidencia_de_pais": 1,
    "tema_solo_en_extracto": 2,
    "subdivision_de_otro_pais": 3,
    "senal_de_otro_pais": 4,
    "dominio_de_otro_pais": 5,
    "menciona_otro_pais": 6,
    "resultado_web": 7,
    "evento_ceremonial": 8,
    "tema_ausente": 9,   # el último recurso
}


def ordenar_marginales(marginales: List[Dict]) -> List[Dict]:
    """
    Ordena las descartadas marginales de más a menos rescatables, según
    el motivo por el que fueron apartadas (ver PRIORIDAD_MOTIVO_MARGINAL).
    Mantiene el orden relativo original dentro de cada motivo.
    """
    return sorted(
        marginales,
        key=lambda n: PRIORIDAD_MOTIVO_MARGINAL.get(
            n.get("_motivo_marginal", ""), 99
        ),
    )


def _es_de_otro_pais_con_certeza(item: Dict, pais_buscado: str) -> bool:
    """
    Descarte DURO: la noticia se publicó en un dominio nacional de otro
    país Y su texto no nombra al país buscado ni una sola vez.

    Por qué hace falta, y por qué no bastaba marcarla como marginal.
    La nota peruana que entró en El Salvador el 29-sep-2026 SÍ estaba
    marcada como marginal: su TLD es .pe y _dominio_de_otro_pais la
    detectó. Llegó al reporte porque El Salvador se quedó corto de
    noticias, el verificador de Groq revisó las marginales, leyó "Villa
    El Salvador" en el título y respondió que sí era relevante.

    Es decir: el verificador cae en la misma trampa del topónimo que
    los filtros de texto, y por diseño puede rescatar cualquier
    marginal. Así que la defensa no puede estar solo ahí. Cuando el
    dominio nacional dice un país y el texto no nombra el buscado
    NINGUNA vez —ya descontados los topónimos homónimos—, no es un caso
    dudoso que convenga que un modelo juzgue: es una certeza.

    No se descarta en duro por TLD a secas, porque sería demasiado:
    la prensa mexicana cubre Centroamérica y una nota de un medio .mx
    sobre el IGSS de Guatemala es legítima. Esa sí nombra a Guatemala,
    así que sobrevive como marginal y el verificador puede rescatarla.
    """
    if _es_dominio_curado_del_pais(item, pais_buscado):
        return False  # medio curado del propio país: certeza en contra
    if not _dominio_de_otro_pais(item, pais_buscado):
        return False
    return not _menciona_el_pais(item, pais_buscado)


def _dominio_curado_de_otro_pais(item: Dict, pais_buscado: str) -> bool:
    """
    True si el link de la noticia pertenece a un dominio que está en
    SITIOS_PAIS de OTRO país. Certeza total: es un descarte duro (la
    noticia ni siquiera pasa a descartadas_marginales, porque el
    verificador LLM no debe poder "rescatarla" — sabemos con seguridad
    de qué país es el medio).

    Hace match también sobre subdominios (ej. "diario.elmundo.sv"
    calza con el dominio curado "elmundo.sv").
    """
    link = item.get("link", "")
    if not link:
        return False

    netloc = urlparse(link).netloc.lower()
    if netloc.startswith("www."):
        netloc = netloc[4:]

    for dominio, pais_del_dominio in _DOMINIO_CURADO_A_PAIS.items():
        if netloc == dominio or netloc.endswith("." + dominio):
            return pais_del_dominio != pais_buscado
    return False


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
