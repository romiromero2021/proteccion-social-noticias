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
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

import requests

from scraper import es_enlace_redirector

# Se puede apagar sin tocar el código (PS_VERIFICAR_FECHAS=0).
VERIFICACION_ACTIVA = os.environ.get("PS_VERIFICAR_FECHAS", "1") != "0"

TIEMPO_MAXIMO_SEGUNDOS = 8
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
}

_MESES_ES = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5,
    "junio": 6, "julio": 7, "agosto": 8, "septiembre": 9, "setiembre": 9,
    "octubre": 10, "noviembre": 11, "diciembre": 12,
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

_FECHA_EN_LETRA_ES = re.compile(
    r"(\d{1,2})\s+de\s+([a-záéíóú]+)\s+de\s+(\d{4})", re.IGNORECASE)


def _parsear_iso(texto: str) -> Optional[datetime]:
    """Interpreta una fecha ISO-8601 y la devuelve en UTC."""
    match = _ISO.search(texto or "")
    if not match:
        return None
    anio, mes, dia, h, m, s, tz = match.groups()
    try:
        fecha = datetime(
            int(anio), int(mes), int(dia),
            int(h or 0), int(m or 0), int(s or 0), tzinfo=timezone.utc,
        )
    except ValueError:
        return None

    # Desplazamiento horario explícito: se lleva todo a UTC.
    if tz and tz not in ("Z", "z"):
        signo = 1 if tz[0] == "+" else -1
        tz_limpio = tz[1:].replace(":", "")
        try:
            horas, minutos = int(tz_limpio[:2]), int(tz_limpio[2:4] or 0)
        except ValueError:
            return fecha
        fecha -= signo * timedelta(hours=horas, minutes=minutos)
    return fecha


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

    # Fechas escritas en letra, "17 de julio de 2026", en el cuerpo.
    match = _FECHA_EN_LETRA_ES.search(html[:BYTES_MAXIMOS])
    if match:
        dia, mes_txt, anio = match.groups()
        mes = _MESES_ES.get(mes_txt.lower())
        if mes:
            try:
                return datetime(int(anio), mes, int(dia),
                                23, 59, tzinfo=timezone.utc)
            except ValueError:
                return None
    return None


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

def _consultar_pagina(link: str) -> Tuple[Optional[str], Optional[datetime]]:
    """
    Pide la página y devuelve (url_final, fecha_publicada).
    Cualquier fallo devuelve (None, None): el llamador deja la noticia
    como estaba.
    """
    try:
        respuesta = requests.get(
            link, timeout=TIEMPO_MAXIMO_SEGUNDOS, allow_redirects=True,
            headers=_ENCABEZADOS, stream=True,
        )
        respuesta.raise_for_status()
        url_final = respuesta.url
        contenido = respuesta.raw.read(BYTES_MAXIMOS, decode_content=True)
        html = contenido.decode(respuesta.encoding or "utf-8", errors="replace")
    except Exception:
        return None, None
    finally:
        try:
            respuesta.close()
        except Exception:
            pass

    return url_final, fecha_publicada_en_html(html)


def verificar_noticias(
    noticias: List[Dict],
    dias_maximos: int,
    activa: Optional[bool] = None,
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
    """
    if activa is None:
        activa = VERIFICACION_ACTIVA
    if not activa or not noticias:
        return list(noticias), []

    with ThreadPoolExecutor(max_workers=TRABAJADORES) as pool:
        resultados = list(pool.map(
            lambda n: _consultar_pagina(n.get("link", "")), noticias))

    limite = datetime.now(timezone.utc) - timedelta(
        days=dias_maximos + DIAS_DE_TOLERANCIA)

    publicables, rechazadas = [], []
    for noticia, (url_final, fecha_real) in zip(noticias, resultados):
        verificada = dict(noticia)

        if url_final and not es_enlace_redirector(url_final):
            if url_final != verificada.get("link"):
                verificada["_link_redirector"] = verificada.get("link", "")
            verificada["link"] = url_final

        if fecha_real is None:
            publicables.append(verificada)
            continue

        verificada["_fecha_buscador"] = noticia.get("fecha", "")
        verificada["_fecha_real"] = fecha_real.date().isoformat()

        if fecha_real < limite:
            dias = (datetime.now(timezone.utc) - fecha_real).days
            rechazadas.append({
                "titulo": verificada.get("titulo", ""),
                "fuente": verificada.get("fuente", ""),
                "link": verificada.get("link", ""),
                "nota": verificada.get("nota"),
                "razon": (
                    f"fecha real fuera de rango: el medio la publicó el "
                    f"{_en_letra(fecha_real)} (hace {dias} días) y el "
                    f"buscador la daba como «{noticia.get('fecha', '')}»"
                ),
            })
            continue

        # Dentro de rango: se corrige la fecha que verá quien lea el
        # reporte, que hasta ahora era la del buscador.
        verificada["fecha"] = _en_letra(fecha_real)
        publicables.append(verificada)

    return publicables, rechazadas


_MESES_CORTOS = ("ene", "feb", "mar", "abr", "may", "jun",
                 "jul", "ago", "sep", "oct", "nov", "dic")


def _en_letra(fecha: datetime) -> str:
    """'17 jul 2026' — fecha absoluta, legible y sin ambigüedad."""
    return f"{fecha.day} {_MESES_CORTOS[fecha.month - 1]} {fecha.year}"
