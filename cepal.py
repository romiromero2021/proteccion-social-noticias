"""
FUENTE DIRECTA: CEPAL / ReDeSoc
===============================

Red de Desarrollo Social de América Latina y el Caribe (ReDeSoc), de la
División de Desarrollo Social de la CEPAL. Publica un boletín continuo
de noticias de desarrollo social de la región, ya curado por la propia
División, con feeds RSS temáticos abiertos.

POR QUÉ EXISTE ESTE MÓDULO
--------------------------
Hasta ahora "CEPAL" aparecía en el proyecto en dos lugares, y ninguno
de los dos podía traer contenido de la CEPAL:

  1. Como término de búsqueda ("CEPAL protección social" en
     TERMINOS_TEMATICOS). Pero en la capa 1 la query va restringida con
     site: a los medios curados de cada país, y cepal.org no está —ni
     puede estar— en la lista de ningún país, porque es un organismo
     regional, no prensa nacional. El término solo alargaba la consulta.

  2. Como palabra clave de relevancia ("cepal" en
     PALABRAS_CLAVE_RELEVANCIA). Eso hace que una noticia de prensa que
     MENCIONE a la CEPAL pase el filtro temático, que es otra cosa
     distinta a traer lo que publica la CEPAL.

Además, aunque cepal.org estuviera en alguna lista, la búsqueda usa la
pestaña de Noticias de Google (tbm=nws), que indexa medios de prensa.
Las páginas institucionales de la CEPAL no son prensa y muchas no
llevan fecha de publicación, así que quedarían fuera por partida doble.

La solución no es otra palabra clave: es tratar a ReDeSoc como la
fuente que es y leerla directamente por RSS. Esto además no consume
cuota de SerpAPI.

Feeds disponibles (verificados el 29-sep-2026 en
https://dds.cepal.org/redesoc/noticias):
  - general .............. /rss/redesoc-rss.php
  - protección social .... /rss/redesoc-proteccionsocial.php
  - infancia ............. /rss/redesoc-infancia.php
  - juventud ............. /rss/redesoc-juventud.php
  - gasto social ......... /rss/redesoc-gastosocial.php
  - discapacidad ......... /rss/redesoc-discapacidad.php
  - seguridad alimentaria  /rss/redesoc-san.php

PRINCIPIO DE DISEÑO: este módulo NUNCA debe poder tumbar un reporte.
Si el feed no responde, cambia de formato o desaparece, todas las
funciones devuelven listas vacías y la app sigue exactamente como
antes, con la prensa nacional. Por eso todo va envuelto en try/except
y no se propaga ninguna excepción hacia afuera.

Prueba rápida del módulo, sin tocar la app:

    python3 cepal.py
"""

import re
import time
import unicodedata
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Dict, List, Optional

# Nombre de la sección regional en el reporte. Se usa como si fuera un
# "país" más, para que el resto de la app (pestañas, caché, documento
# Word) la trate sin cambios estructurales.
SECCION_CEPAL = "CEPAL (regional)"

# Feeds que se consultan, en orden. Se usa el temático de protección
# social como principal y el general como complemento: el temático es
# más preciso, pero el general recoge notas de desarrollo social que no
# están etiquetadas como protección social.
FEEDS_REDESOC = [
    "https://dds.cepal.org/redesoc/rss/redesoc-proteccionsocial.php",
    "https://dds.cepal.org/redesoc/rss/redesoc-rss.php",
]

# Página de referencia para citar la fuente en el reporte.
URL_REDESOC = "https://dds.cepal.org/redesoc/noticias"

TIMEOUT_SEGUNDOS = 15
MAX_ITEMS_POR_FEED = 60

# Caché en memoria del proceso: el feed se descarga UNA vez por
# ejecución, no una vez por país. Con 10 países eso es 1 descarga en
# lugar de 10. Se revalida pasada media hora por si la app queda
# abierta mucho tiempo.
_cache_items: Optional[List[Dict]] = None
_cache_momento: float = 0.0
_CACHE_VIGENCIA_SEGUNDOS = 1800


# ---------------------------------------------------------------------------
# Utilidades de texto
# ---------------------------------------------------------------------------

def _sin_acentos(texto: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFD", texto)
        if unicodedata.category(c) != "Mn"
    )


def _normalizar(texto: str) -> str:
    return _sin_acentos((texto or "").lower())


def _limpiar_html(texto: str) -> str:
    """Quita etiquetas y normaliza espacios de una descripción RSS."""
    sin_tags = re.sub(r"<[^>]+>", " ", texto or "")
    sin_entidades = (
        sin_tags.replace("&nbsp;", " ")
        .replace("&amp;", "&")
        .replace("&quot;", '"')
        .replace("&#39;", "'")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
    )
    return re.sub(r"\s+", " ", sin_entidades).strip()


# ---------------------------------------------------------------------------
# Descarga y parseo del feed
# ---------------------------------------------------------------------------

def _descargar(url: str) -> Optional[bytes]:
    try:
        peticion = urllib.request.Request(
            url,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (compatible; MonitorProteccionSocial/1.0; "
                    "CEPAL Unidad de Desarrollo Social)"
                ),
                "Accept": "application/rss+xml, application/xml, text/xml, */*",
            },
        )
        with urllib.request.urlopen(peticion, timeout=TIMEOUT_SEGUNDOS) as respuesta:
            return respuesta.read()
    except Exception:
        # Silencio deliberado: la ausencia del feed no es un error del
        # reporte, solo significa que esa fuente no aportó nada hoy.
        return None


def _parsear_fecha_rss(texto: str) -> Optional[datetime]:
    """
    Acepta los dos formatos que aparecen en la práctica: RFC 822
    (RSS 2.0, "Wed, 23 Sep 2026 10:00:00 -0300") e ISO 8601 (Atom).
    Devuelve siempre UTC, o None si no se pudo interpretar.
    """
    if not texto:
        return None
    texto = texto.strip()
    try:
        fecha = parsedate_to_datetime(texto)
        if fecha is not None:
            if fecha.tzinfo is None:
                fecha = fecha.replace(tzinfo=timezone.utc)
            return fecha.astimezone(timezone.utc)
    except Exception:
        pass
    match = re.match(r"(\d{4})-(\d{2})-(\d{2})", texto)
    if match:
        anio, mes, dia = (int(g) for g in match.groups())
        try:
            return datetime(anio, mes, dia, 23, 59, 59, tzinfo=timezone.utc)
        except ValueError:
            return None
    return None


def _texto_de(elemento, *nombres: str) -> str:
    """
    Devuelve el texto del primer subelemento que coincida con alguno de
    los nombres dados, ignorando el namespace XML (Atom los usa, RSS no).
    """
    for hijo in elemento.iter():
        etiqueta = hijo.tag.split("}")[-1].lower()
        if etiqueta in nombres:
            if hijo.text and hijo.text.strip():
                return hijo.text.strip()
            # Atom pone el enlace en un atributo, no en el texto.
            href = hijo.attrib.get("href")
            if href:
                return href.strip()
    return ""


def _parsear_feed(contenido: bytes) -> List[Dict]:
    """
    Convierte el XML del feed en la MISMA forma de diccionario que usa
    el resto del proyecto para una noticia, para que aguas abajo nada
    tenga que saber de dónde vino.
    """
    try:
        raiz = ET.fromstring(contenido)
    except ET.ParseError:
        return []

    entradas = [
        elemento for elemento in raiz.iter()
        if elemento.tag.split("}")[-1].lower() in ("item", "entry")
    ]

    items: List[Dict] = []
    for entrada in entradas[:MAX_ITEMS_POR_FEED]:
        titulo = _limpiar_html(_texto_de(entrada, "title"))
        enlace = _texto_de(entrada, "link", "guid")
        if not titulo or not enlace.startswith("http"):
            continue
        descripcion = _limpiar_html(
            _texto_de(entrada, "description", "summary", "content")
        )
        fecha = _parsear_fecha_rss(
            _texto_de(entrada, "pubdate", "published", "updated", "date")
        )
        items.append({
            "titulo": titulo,
            "link": enlace,
            "snippet": descripcion[:600],
            "fecha_dt": fecha,
            "fuente": "CEPAL – ReDeSoc",
        })
    return items


def obtener_items_redesoc(dias_maximos: int = 10, forzar: bool = False) -> List[Dict]:
    """
    Devuelve las noticias recientes de ReDeSoc, deduplicadas por enlace
    y ordenadas de más nueva a más vieja. Lista vacía si el feed no
    respondió o no trajo nada dentro del rango — nunca lanza excepción.
    """
    global _cache_items, _cache_momento

    if (
        not forzar
        and _cache_items is not None
        and (time.time() - _cache_momento) < _CACHE_VIGENCIA_SEGUNDOS
    ):
        items = _cache_items
    else:
        items = []
        for url in FEEDS_REDESOC:
            contenido = _descargar(url)
            if contenido:
                items.extend(_parsear_feed(contenido))
        _cache_items = items
        _cache_momento = time.time()

    limite = datetime.now(timezone.utc) - timedelta(days=dias_maximos)
    vistos = set()
    recientes = []
    for item in items:
        # Sin fecha se deja pasar: el feed solo publica material actual,
        # y descartar por un formato inesperado costaría más de lo que
        # ahorra. El filtro de fecha del scraper lo revisa después.
        if item["fecha_dt"] is not None and item["fecha_dt"] < limite:
            continue
        if item["link"] in vistos:
            continue
        vistos.add(item["link"])
        recientes.append(item)

    recientes.sort(
        key=lambda i: i["fecha_dt"] or datetime.now(timezone.utc),
        reverse=True,
    )
    return recientes


# ---------------------------------------------------------------------------
# Asignación de país
# ---------------------------------------------------------------------------

def _menciona(texto_normalizado: str, termino: str) -> bool:
    return re.search(
        r"\b" + re.escape(_normalizar(termino)) + r"\b", texto_normalizado
    ) is not None


def item_es_del_pais(item: Dict, pais: str, demonimos: Dict[str, List[str]]) -> bool:
    """
    True si la noticia de ReDeSoc corresponde a ese país. Se mira el
    título y la descripción: ReDeSoc suele encabezar sus notas con el
    país ("República Dominicana: SIUBEN fortalece…"), así que el título
    basta en la mayoría de los casos.
    """
    texto = _normalizar(f"{item.get('titulo','')} {item.get('snippet','')}")
    if _menciona(texto, pais):
        return True
    # Grafías alternas que el nombre oficial no cubre.
    alternos = {
        "Haití": ["haiti", "haitienne", "haitien"],
        "República Dominicana": ["dominicana", "dominicano"],
        "México": ["mexico"],
        "Panamá": ["panama"],
    }
    for alterno in alternos.get(pais, []):
        if _menciona(texto, alterno):
            return True
    return any(_menciona(texto, d) for d in demonimos.get(pais, []))


def formatear_para_reporte(item: Dict) -> Dict:
    """Convierte un item de ReDeSoc a la forma de noticia del proyecto."""
    if item["fecha_dt"] is not None:
        fecha_texto = item["fecha_dt"].strftime("%d/%m/%Y")
    else:
        fecha_texto = "Fecha no disponible"
    return {
        "titulo": item["titulo"],
        "fuente": item["fuente"],
        "fecha": fecha_texto,
        "snippet": item["snippet"],
        "link": item["link"],
    }


# ---------------------------------------------------------------------------
# Prueba manual del módulo
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print(f"Consultando ReDeSoc ({len(FEEDS_REDESOC)} feeds)…\n")
    items = obtener_items_redesoc(dias_maximos=21)
    if not items:
        print("Sin resultados. Posibles causas:")
        print("  - Sin acceso a dds.cepal.org desde esta máquina.")
        print("  - Las URLs de los feeds cambiaron: verifícalas en")
        print(f"    {URL_REDESOC}")
        raise SystemExit(1)

    print(f"{len(items)} noticias recientes:\n")
    for item in items[:25]:
        fecha = item["fecha_dt"].strftime("%Y-%m-%d") if item["fecha_dt"] else "s/f"
        print(f"  [{fecha}] {item['titulo'][:95]}")
    print(f"\nFuente: {URL_REDESOC}")
