"""
VERIFICACIÓN DE ENLACES Y FECHAS — se ejecuta sobre las noticias que YA
fueron seleccionadas para publicarse, nunca sobre toda la cosecha.

POR QUÉ EXISTE
--------------
Dos averías confirmadas en los reportes del 31-oct y 1-nov-2026, las
dos con el mismo origen: el sistema se fiaba de lo que le decía el
buscador y nada lo contrastaba contra el artículo.

1. ENLACES REDIRECTORES. Google empezó a devolver parte de los
   resultados envueltos en "https://www.google.com/goto?url=CAES…", un
   token cifrado que no contiene la URL del medio. El 23-oct fueron 0
   de 44; el 31-oct, 23 de 38; el 1-nov, 20 de 37. El documento Word
   que circula por correo quedaba con enlaces opacos, caducables y que
   no dicen de qué medio son. scraper.url_real_sin_red() recupera
   algunos sin red; los demás solo se resuelven pidiendo la página.

2. FECHAS FALSAS EN ORIGEN. La misma nota de Vanguardia.cu sobre el
   salario mínimo cubano salió como "Hace 6 días" el 23-oct, "Hace 2
   días" el 31-oct y "hace 13 horas" el 1-nov. El artículo es del 17 de
   julio de 2026: no es que la fecha se desvíe, es que rejuvenece en
   cada corrida. Otra nota (GatoEncerrado) repitió "hace 3 días" en dos
   reportes consecutivos. Un tercer caso (Guananoticias) avanzó
   correctamente de 3 a 4 días, que es el control que demuestra que el
   campo a veces sí funciona.

   Ningún filtro de fecha podía atrapar esto, porque el dato que
   llegaba era falso antes de entrar. La única defensa es leer la
   fecha que publica el propio medio en su página.

CRITERIO DE DISEÑO
------------------
Esto añade peticiones de red a un sistema que funciona, así que:

  - se aplica SOLO a las noticias ya seleccionadas (como mucho cinco
    por país), no a las decenas de candidatas;
  - cada petición tiene un tiempo máximo corto y se hacen en paralelo;
  - ante CUALQUIER fallo —red, tiempo agotado, HTML raro, fecha
    ilegible— la noticia se deja exactamente como estaba. Verificar no
    puede ser una nueva forma de perder noticias;
  - solo se descarta cuando la página del medio dice una fecha REAL y
    esa fecha está fuera del rango. Es el único caso en que sabemos
    más que el buscador.
"""

from __future__ import annotations

import json
import os
import re
import unicodedata
from html import unescape
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

import requests

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover
    ZoneInfo = None

from scraper import es_enlace_redirector

# Huso horario de cada país, para escribir la fecha como la ve quien
# lee el periódico allí.
#
# CASO CONFIRMADO (1-nov-2026): Diario de Cuba publicó una nota el
# 31-oct por la noche, hora de La Habana. Su metadato viene en hora
# universal, donde eso ya es 1 de noviembre, y el reporte decía
# "1 nov 2026" mientras el artículo decía 31 de octubre. La fecha que
# importa es la del medio, en su hora.
_HUSOS_PAIS = {
    "Costa Rica": "America/Costa_Rica",
    "Cuba": "America/Havana",
    "El Salvador": "America/El_Salvador",
    "Guatemala": "America/Guatemala",
    "Haití": "America/Port-au-Prince",
    "Honduras": "America/Tegucigalpa",
    "México": "America/Mexico_City",
    "Nicaragua": "America/Managua",
    "Panamá": "America/Panama",
    "República Dominicana": "America/Santo_Domingo",
}


def _huso_de(pais: Optional[str]):
    """Huso horario del país, o None si no se conoce."""
    nombre = _HUSOS_PAIS.get(pais or "")
    if not nombre or ZoneInfo is None:
        return None
    try:
        return ZoneInfo(nombre)
    except Exception:
        return None

# Se puede apagar sin tocar el código (PS_VERIFICAR_FECHAS=0).
VERIFICACION_ACTIVA = os.environ.get("PS_VERIFICAR_FECHAS", "1") != "0"

TIEMPO_MAXIMO_SEGUNDOS = 12
# Un reintento absorbe los sitios lentos sin alargar mucho la corrida:
# las peticiones van en paralelo.
REINTENTOS = 2
TRABAJADORES = 8
# Tamaño máximo de HTML que se lee: las etiquetas de fecha viven en la
# cabecera, así que no hace falta descargar el artículo entero.
BYTES_MAXIMOS = 400_000

# Margen de tolerancia antes de contradecir al buscador. Un desfase de
# uno o dos días suele ser zona horaria o la diferencia entre la hora
# de publicación y la de indexado; no es una mentira.
DIAS_DE_TOLERANCIA = 2

_ENCABEZADOS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; ResumenProteccionSocial/1.0; "
        "+monitoreo de prensa institucional)"
    ),
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "es,fr;q=0.8,en;q=0.6",
}

_MESES_ES = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5,
    "junio": 6, "julio": 7, "agosto": 8, "septiembre": 9, "setiembre": 9,
    "octubre": 10, "noviembre": 11, "diciembre": 12,
    # Francés, por Haití.
    "janvier": 1, "fevrier": 2, "mars": 3, "avril": 4, "mai": 5,
    "juin": 6, "juillet": 7, "aout": 8, "septembre": 9, "octobre": 10,
    "novembre": 11, "decembre": 12,
}


# ---------------------------------------------------------------------------
# LECTURA DE LA FECHA EN LA PÁGINA DEL MEDIO
# ---------------------------------------------------------------------------

# Deliberadamente NO se lee "article:modified_time" ni "dateModified":
# una nota de julio reeditada en octubre seguiría siendo de julio, y
# usar la fecha de modificación reproduciría el mismo error que
# estamos corrigiendo.
_PATRONES_FECHA = (
    re.compile(r'"datePublished"\s*:\s*"([^"]+)"', re.IGNORECASE),
    re.compile(
        r'<meta[^>]+(?:property|name)=["\']article:published_time["\']'
        r'[^>]+content=["\']([^"\']+)["\']', re.IGNORECASE),
    re.compile(
        r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+'
        r'(?:property|name)=["\']article:published_time["\']', re.IGNORECASE),
    re.compile(
        r'<meta[^>]+itemprop=["\']datePublished["\']'
        r'[^>]+content=["\']([^"\']+)["\']', re.IGNORECASE),
    re.compile(
        r'<meta[^>]+(?:property|name)=["\'](?:pubdate|publishdate|'
        r'date|dc\.date|dc\.date\.issued|sailthru\.date)["\']'
        r'[^>]+content=["\']([^"\']+)["\']', re.IGNORECASE),
    re.compile(r'<time[^>]+datetime=["\']([^"\']+)["\']', re.IGNORECASE),
)

_ISO = re.compile(
    r"(\d{4})-(\d{2})-(\d{2})"
    r"(?:[T ](\d{2}):(\d{2})(?::(\d{2}))?)?"
    r"\s*(Z|[+-]\d{2}:?\d{2})?"
)

# Fechas escritas en el cuerpo de la página. Hacen falta varias formas
# porque los gestores de contenido viejos no publican metadatos.
#
# CASO CONFIRMADO (1-nov-2026): vanguardia.cu —la nota de julio que
# salía como "hace 13 horas"— corre sobre un gestor cuyas URLs tienen
# la forma /de-cuba/37891-titulo, típica de Joomla, que suele escribir
# "Publicado: Viernes, 17 Julio 2026 10:30", SIN la preposición "de".
# La primera versión de este patrón exigía "17 de julio de 2026" y por
# eso no reconocía nada en esa página.
_FECHA_EN_LETRA_ES = re.compile(
    r"(\d{1,2})\s+(?:de\s+)?([a-záéíóúàèêûüçñ]{3,10})\.?\s+(?:de\s+|del\s+)?(\d{4})",
    re.IGNORECASE)

# "2026-11-03" escrito en el cuerpo de la página.
#
# AVERÍA CONFIRMADA (10-nov-2026, Haití). Las tres noticias haitianas
# del reporte salieron con "sin fecha legible" teniendo la fecha a la
# vista en la página. Una de las causas: los dos patrones de texto
# daban por hecho que el día va primero ("3 de noviembre de 2026",
# "03/11/2026"), y Le Nouvelliste la escribe al revés, en forma ISO.
# Un medio que publica su fecha de la manera más inequívoca posible
# era justo el que no se podía leer.
_FECHA_ISO_EN_TEXTO = re.compile(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b")

# "17/07/2026" y "17-07-2026" — día primero, que es como escribe la
# prensa en español. Se exige un año de cuatro cifras para no casar
# con cualquier número suelto.
_FECHA_NUMERICA_ES = re.compile(r"\b(\d{1,2})[/-](\d{1,2})[/-](\d{4})\b")

# Palabras que suelen preceder a la fecha de publicación. Sirven para
# NO quedarse con la primera fecha que aparezca en la página (que
# podría ser la de otra noticia de la barra lateral).
_ANTES_DE_LA_FECHA = re.compile(
    r"(publicad[oa]|fecha de publicaci[oó]n|actualizad[oa]\s+el"
    r"|escrito por|published|posted\s+on"
    # Francés (Haití). "le" va opcional: muchos medios escriben
    # "Publié 4 novembre 2026", sin artículo.
    r"|publi[ée]e?(?:\s+le)?|paru(?:\s+le)?|mis\s+en\s+ligne)",
    re.IGNORECASE)

# Microformato de fecha: <abbr class="published" title="2026-11-05T…">
# o <span class="date" title="…">. Es lo que emite SPIP, el gestor con
# el que está hecho AlterPresse, y no lo cubría ninguno de los
# patrones de metadatos: no es un <meta>, ni un <time datetime>, ni
# JSON-LD. Dos noticias haitianas del reporte del 10-nov salieron "sin
# fecha legible" por esto.
_PATRONES_MICROFORMATO = (
    re.compile(
        r'class=["\'][^"\']*\b(?:published|date[a-z-]*)\b[^"\']*["\']'
        r'[^>]*title=["\']([^"\']+)["\']', re.IGNORECASE),
    re.compile(
        r'title=["\']([^"\']+)["\'][^>]*'
        r'class=["\'][^"\']*\b(?:published|date[a-z-]*)\b[^"\']*["\']',
        re.IGNORECASE),
)

_ETIQUETAS = re.compile(r"<[^>]+>")


def _a_texto_plano(html: str) -> str:
    """
    Quita las etiquetas y decodifica las entidades, para que la
    búsqueda de la fecha vea lo mismo que ve una persona.

    Hace falta por dos motivos reales, los dos vistos en las páginas
    haitianas: "Publié&nbsp;le" no casaba con el patrón porque la
    entidad no estaba decodificada, y "Publié <span>le</span> 4
    novembre" tampoco, porque había una etiqueta en medio de la frase.
    """
    plano = _ETIQUETAS.sub(" ", html or "")
    plano = unescape(plano)
    return re.sub(r"[\s ]+", " ", plano)


def _parsear_iso(texto: str) -> Optional[datetime]:
    """
    Interpreta una fecha ISO-8601 CONSERVANDO su huso horario.

    Es importante no convertirla a UTC. Un medio cubano que publica a
    las 20:00 del 31 de octubre escribe "2026-10-31T20:00:00-04:00";
    pasado a UTC eso son las 00:00 del 1 de noviembre, y el reporte
    acababa diciendo "1 nov 2026" mientras el artículo decía 31 de
    octubre. La fecha que debe ver quien lee el boletín es la que
    publicó el medio, en su hora, no la nuestra.

    Para comparar antigüedades da igual: Python compara bien dos
    fechas con huso, cada una con el suyo.
    """
    match = _ISO.search(texto or "")
    if not match:
        return None
    anio, mes, dia, h, m, s, tz = match.groups()

    huso = timezone.utc
    if tz and tz not in ("Z", "z"):
        signo = 1 if tz[0] == "+" else -1
        tz_limpio = tz[1:].replace(":", "")
        try:
            horas, minutos = int(tz_limpio[:2]), int(tz_limpio[2:4] or 0)
            huso = timezone(signo * timedelta(hours=horas, minutes=minutos))
        except ValueError:
            huso = timezone.utc

    try:
        return datetime(int(anio), int(mes), int(dia),
                        int(h or 0), int(m or 0), int(s or 0), tzinfo=huso)
    except ValueError:
        return None


def fecha_publicada_en_html(html: str) -> Optional[datetime]:
    """
    Fecha de publicación declarada por el propio medio en su página.
    Devuelve None si la página no la declara de forma legible.

    Función pura: se puede probar sin red (ver evals/test_fechas_y_enlaces.py).
    """
    if not html:
        return None

    for patron in _PATRONES_FECHA:
        for candidata in patron.findall(html[:BYTES_MAXIMOS]):
            fecha = _parsear_iso(candidata)
            if fecha is not None:
                return fecha

    # Último recurso: JSON-LD con la fecha en otro formato.
    for bloque in re.findall(
            r'<script[^>]+application/ld\+json[^>]*>(.*?)</script>',
            html[:BYTES_MAXIMOS], re.IGNORECASE | re.DOTALL):
        try:
            datos = json.loads(bloque.strip())
        except (ValueError, TypeError):
            continue
        for valor in _valores_de_fecha(datos):
            fecha = _parsear_iso(valor)
            if fecha is not None:
                return fecha

    # Sin metadatos: la fecha escrita en el cuerpo, PERO solo si
    # aparece pegada a una palabra que la presente como fecha de
    # publicación ("Publicado el…", "Fecha de publicación…").
    #
    # AVERÍA CONFIRMADA (1-nov-2026, Nicaragua). Antes, si no había
    # ninguna de esas palabras, se recorría la página entera y se
    # tomaba la primera fecha que apareciera. En una nota de Radio ABC
    # Stereo titulada "Declaran asueto a cuenta de vacaciones el 2 de
    # noviembre" eso dio "2 nov 2026" como fecha de publicación: era
    # la fecha de la que HABLA la noticia, no la de su publicación. El
    # artículo es del 27 de octubre.
    #
    # Ese fallo se vio porque la fecha caía en el futuro. El caso
    # peligroso es el contrario: una noticia que mencione "el 20 de
    # septiembre" habría recibido en silencio una fecha vieja y la
    # habrían descartado por antigua. Una noticia buena perdida, por
    # una fecha inventada a partir de su propio texto.
    #
    # Por eso ya no hay búsqueda a página completa. Si el medio no
    # dice claramente cuándo publicó, la respuesta correcta es "no se
    # pudo verificar", no una conjetura con aspecto de dato.
    cuerpo = html[:BYTES_MAXIMOS]

    # Microformato antes que el texto corrido: un title="2026-11-05T…"
    # es un dato, no una conjetura.
    for patron in _PATRONES_MICROFORMATO:
        for match in patron.finditer(cuerpo):
            fecha = _parsear_iso(match.group(1)) or _fecha_en_texto(match.group(1))
            if fecha is not None:
                return fecha

    # El texto, ya sin etiquetas ni entidades, para que "Publié&nbsp;le"
    # y "Publié <span>le</span>" se lean como lo que son.
    plano = _a_texto_plano(cuerpo)
    for marca in _ANTES_DE_LA_FECHA.finditer(plano):
        cercano = plano[marca.start():marca.start() + 200]
        fecha = _fecha_en_texto(cercano)
        if fecha is not None:
            return fecha
    return None


def _fecha_en_texto(texto: str) -> Optional[datetime]:
    """
    Fecha escrita en lenguaje corriente: "17 de julio de 2026",
    "Viernes, 17 Julio 2026 10:30", "17/07/2026".

    Devuelve el final del día: el dato no trae hora fiable y la duda
    debe jugar a favor de conservar la noticia.
    """
    match = _FECHA_EN_LETRA_ES.search(texto)
    if match:
        dia, mes_txt, anio = match.groups()
        mes = _MESES_ES.get(_sin_tildes(mes_txt.lower()))
        if mes:
            try:
                return datetime(int(anio), mes, int(dia),
                                23, 59, tzinfo=timezone.utc)
            except ValueError:
                pass

    # ISO antes que el formato día-primero: "2026-11-03" es inequívoco
    # y "03/11/2026" no lo sería si el medio escribiera a la inglesa.
    match = _FECHA_ISO_EN_TEXTO.search(texto)
    if match:
        anio, mes, dia = (int(x) for x in match.groups())
        if 1 <= mes <= 12 and 1 <= dia <= 31:
            try:
                return datetime(anio, mes, dia, 23, 59, tzinfo=timezone.utc)
            except ValueError:
                pass

    match = _FECHA_NUMERICA_ES.search(texto)
    if match:
        dia, mes, anio = (int(x) for x in match.groups())
        if 1 <= mes <= 12 and 1 <= dia <= 31:
            try:
                return datetime(anio, mes, dia, 23, 59, tzinfo=timezone.utc)
            except ValueError:
                return None
    return None


def _sin_tildes(texto: str) -> str:
    descompuesto = unicodedata.normalize("NFD", texto)
    return "".join(c for c in descompuesto if unicodedata.category(c) != "Mn")


def _valores_de_fecha(datos) -> List[str]:
    """Recoge todos los 'datePublished' de un JSON-LD anidado."""
    encontrados = []
    if isinstance(datos, dict):
        for clave, valor in datos.items():
            if clave.lower() == "datepublished" and isinstance(valor, str):
                encontrados.append(valor)
            else:
                encontrados.extend(_valores_de_fecha(valor))
    elif isinstance(datos, list):
        for elemento in datos:
            encontrados.extend(_valores_de_fecha(elemento))
    return encontrados


# ---------------------------------------------------------------------------
# UNA PETICIÓN POR NOTICIA: resuelve el redirector Y lee la fecha
# ---------------------------------------------------------------------------

def _consultar_pagina(link: str) -> Tuple[Optional[str], Optional[datetime], str]:
    """
    Pide la página y devuelve (url_final, fecha_publicada, motivo).

    `motivo` explica por qué NO se pudo verificar, para que el fallo
    quede dicho en vez de pasar en silencio:
      ""                  -> se verificó
      "no respondió"      -> red, tiempo agotado o error del servidor
      "sin fecha legible" -> la página respondió pero no declara fecha

    Antes esta función leía el cuerpo con `stream=True` y
    `raw.read()`. Eso obliga a adivinar la codificación y puede
    devolver bytes todavía comprimidos, lo que convierte la página en
    ruido y hace imposible encontrar la fecha. Ahora se usa
    `respuesta.text`, que aplica la codificación declarada por el
    servidor y descomprime solo.
    """
    url_final = html = None
    for intento in range(REINTENTOS):
        try:
            respuesta = requests.get(
                link, timeout=TIEMPO_MAXIMO_SEGUNDOS, allow_redirects=True,
                headers=_ENCABEZADOS,
            )
            respuesta.raise_for_status()
            url_final = respuesta.url
            html = respuesta.text[:BYTES_MAXIMOS]
            break
        except Exception:
            continue
    if html is None:
        return None, None, "no respondió"

    fecha = fecha_publicada_en_html(html)
    return url_final, fecha, "" if fecha else "sin fecha legible"


def verificar_noticias(
    noticias: List[Dict],
    dias_maximos: int,
    activa: Optional[bool] = None,
    pais: Optional[str] = None,
) -> Tuple[List[Dict], List[Dict]]:
    """
    Verifica las noticias seleccionadas contra la página del medio.

    Devuelve (publicables, rechazadas). Las rechazadas llevan el motivo
    escrito para que aparezcan en el panel de descartadas con su causa,
    igual que cualquier otra decisión del sistema.

    A cada noticia verificada se le añaden:
      "link"         — la URL real del medio, si se resolvió el redirector
      "fecha"        — la fecha real en formato "17 jul 2026", si se leyó
      "_fecha_real"  — la misma fecha en ISO, para pruebas y registro
      "_fecha_buscador" — lo que decía el buscador, para poder comparar
      "_fecha_verificada" — True si se pudo contrastar con la página
    """
    if activa is None:
        activa = VERIFICACION_ACTIVA
    if not activa or not noticias:
        return list(noticias), []

    huso = _huso_de(pais)

    with ThreadPoolExecutor(max_workers=TRABAJADORES) as pool:
        resultados = list(pool.map(
            lambda n: _consultar_pagina(n.get("link", "")), noticias))

    limite = datetime.now(timezone.utc) - timedelta(
        days=dias_maximos + DIAS_DE_TOLERANCIA)

    publicables, rechazadas = [], []
    for noticia, (url_final, fecha_real, motivo) in zip(noticias, resultados):
        verificada = dict(noticia)

        if url_final and not es_enlace_redirector(url_final):
            if url_final != verificada.get("link"):
                verificada["_link_redirector"] = verificada.get("link", "")
            verificada["link"] = url_final

        # Una fecha de publicación POSTERIOR a hoy es imposible, y sin
        # embargo llega: el 1-nov-2026 una nota de Radio ABC Stereo
        # (Nicaragua) se verificó como "2 nov 2026". O el medio estampa
        # mal la hora, o lo que se leyó no era la fecha de publicación
        # sino otra cosa de la página. En cualquiera de los dos casos el
        # dato no sirve, y escribirlo sería cambiar una fecha dudosa por
        # otra con aire de comprobada.
        if fecha_real is not None and \
                fecha_real > datetime.now(timezone.utc) + timedelta(days=1):
            verificada["_fecha_verificada"] = False
            verificada["_motivo_sin_verificar"] = "la página declara una fecha futura"
            publicables.append(verificada)
            continue

        if fecha_real is None:
            # No se pudo confirmar: ni la página responde ni declara
            # su fecha de forma legible. La noticia se publica igual
            # —fallar aquí no puede costar noticias— pero queda
            # MARCADA, porque "verificada y correcta" y "no se pudo
            # comprobar" no son lo mismo y el reporte no debe
            # presentarlas igual.
            verificada["_fecha_verificada"] = False
            verificada["_motivo_sin_verificar"] = motivo
            publicables.append(verificada)
            continue

        verificada["_fecha_buscador"] = noticia.get("fecha", "")
        verificada["_fecha_real"] = (
            fecha_real.astimezone(huso) if huso else fecha_real
        ).date().isoformat()

        if fecha_real < limite:
            dias = (datetime.now(timezone.utc) - fecha_real).days
            rechazadas.append({
                "titulo": verificada.get("titulo", ""),
                "fuente": verificada.get("fuente", ""),
                "link": verificada.get("link", ""),
                "nota": verificada.get("nota"),
                "razon": (
                    f"fecha real fuera de rango: el medio la publicó el "
                    f"{_en_letra(fecha_real, huso)} (hace {dias} días) y el "
                    f"buscador la daba como «{noticia.get('fecha', '')}»"
                ),
            })
            continue

        # Dentro de rango: se corrige la fecha que verá quien lea el
        # reporte, que hasta ahora era la del buscador.
        verificada["fecha"] = _en_letra(fecha_real, huso)
        verificada["_fecha_verificada"] = True
        publicables.append(verificada)

    return publicables, rechazadas


_MESES_CORTOS = ("ene", "feb", "mar", "abr", "may", "jun",
                 "jul", "ago", "sep", "oct", "nov", "dic")


def _en_letra(fecha: datetime, huso=None) -> str:
    """
    '17 jul 2026' — fecha absoluta, legible y sin ambigüedad, escrita
    en la hora del país del reporte cuando se conoce.
    """
    if huso is not None:
        fecha = fecha.astimezone(huso)
    return f"{fecha.day} {_MESES_CORTOS[fecha.month - 1]} {fecha.year}"
