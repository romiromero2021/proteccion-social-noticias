"""
MEMORIA ENTRE CORRIDAS (memoria.py)
===================================
Lo único del sistema que sobrevive al día.

POR QUÉ EXISTE
--------------
Hasta ahora el sistema no recordaba nada de una consulta a la
siguiente. `cache.py` guarda el resultado del día y se purga a los tres
días; `deduplicar_noticias` compara solo dentro de una misma cosecha.
Consecuencia confirmada en el reporte del 9-nov-2026: la nota de
Vanguardia.cu sobre el salario mínimo cubano —publicada el 17 de julio
de 2026— apareció en el reporte del 23-oct, en el del 31-oct, en el del
1-nov y otra vez en el del 9-nov. Cada semana el buscador la devuelve
con una fecha relativa más fresca, cada semana la verificación no logra
contrastarla contra la página del medio, y cada semana entra como si
fuera nueva.

No es un fallo de la verificación: es que **nadie recordaba haberla
publicado ya**. Un sistema que no recuerda no puede notar que se repite.

QUÉ GUARDA
----------
Una tabla `noticias_publicadas`, con clave el enlace normalizado:
  - pais, titulo
  - primera_vez / ultima_vez (fechas ISO)
  - veces (cuántos reportes la han llevado)
  - veces_verificada (en cuántos se pudo contrastar la fecha)

Y una tabla `noticias_vetadas` para los vetos manuales: cuando una
persona comprueba que una noticia concreta está mal fechada o no
corresponde, se anota aquí con su motivo y no vuelve a publicarse.
Es la única parte del sistema donde un juicio humano queda grabado, y
por eso lleva siempre motivo y fecha.

LAS DOS REGLAS
--------------
1. REPETICIÓN. Un enlace publicado en los últimos DIAS_SIN_REPETIR días
   no se vuelve a publicar. Una noticia no se vuelve nueva porque el
   buscador le cambie la fecha.

2. REINCIDENTE SIN VERIFICAR. Un enlace que ya salió
   VECES_PARA_SOSPECHAR veces o más y que NUNCA pudo verificarse contra
   la página del medio deja de publicarse. Es exactamente el perfil de
   la nota de julio: reaparece siempre y nunca se puede comprobar. Una
   noticia legítima que se republique rara vez cumple las dos
   condiciones a la vez.

Ninguna de las dos borra nada: las dos mandan la noticia al panel de
descartadas con su motivo escrito, como cualquier otra decisión.

POR QUÉ SQLITE Y NO EL MISMO ARCHIVO DEL CACHÉ
----------------------------------------------
Son dos cosas con vidas distintas. El caché es desechable: existe para
no pagar dos veces la misma búsqueda el mismo día, y se puede perder
sin consecuencias. Esta memoria es lo contrario: su valor está
precisamente en ser vieja. Si se pierde, el sistema vuelve a repetir
las noticias de julio. Van en archivos distintos para que la limpieza
rutinaria de uno no se lleve el otro por delante.

AVISO DE DESPLIEGUE
-------------------
En Streamlit Cloud el archivo vive mientras el contenedor esté vivo; un
redespliegue lo borra. Eso degrada bien —se vuelve a poblar y en una o
dos semanas protege otra vez— pero conviene saberlo: la protección de
la regla 2 tarda VECES_PARA_SOSPECHAR corridas en volver a activarse.
Los vetos manuales, en cambio, viven en VETOS_FIJOS, dentro del código,
precisamente para que ningún redespliegue se los lleve.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.parse import urlparse, urlunparse

from cache import ZONA_HORARIA

DB_PATH = Path(__file__).parent / "memoria_noticias.db"

# Una noticia publicada no se repite dentro de esta ventana.
# Treinta días cubre con holgura el caso real (la misma nota en cuatro
# reportes a lo largo de tres semanas) sin impedir que un tema
# legítimo vuelva más adelante con una nota distinta.
DIAS_SIN_REPETIR = 30

# A partir de esta cantidad de apariciones, una noticia que nunca se
# pudo verificar se considera sospechosa y deja de publicarse.
VECES_PARA_SOSPECHAR = 3

# Cuánto se conserva la memoria. Más que la ventana de repetición,
# para que la cuenta de "veces" tenga sentido.
DIAS_A_CONSERVAR = 120


# ---------------------------------------------------------------------------
# VETOS FIJOS — juicios humanos, en el código y no en la base de datos
# ---------------------------------------------------------------------------
# Van aquí y no en la tabla porque un redespliegue de Streamlit Cloud
# borra el archivo .db y estos no deben perderse nunca: son
# comprobaciones que alguien hizo a mano, abriendo el artículo.
#
# Formato: enlace normalizado -> (motivo, quién y cuándo lo comprobó)
VETOS_FIJOS: Dict[str, Tuple[str, str]] = {
    "vanguardia.cu/de-cuba/37891-actualizan-salario-minimo-e-incrementan-escala-salarial-del-sector-presupuestado": (
        "el artículo es del 17 de julio de 2026; el buscador lo reporta "
        "como reciente en cada corrida y la página no se deja verificar",
        "comprobado a mano el 9-nov-2026",
    ),
}


def normalizar_enlace(link: str) -> str:
    """
    Forma canónica de un enlace, para que el mismo artículo cuente como
    uno solo aunque cambie el esquema, el www, los parámetros de
    seguimiento o la barra final.

    Confirmado en producción: la nota de Vanguardia.cu llegó unas veces
    como http:// y otras como https://, y eso bastaba para que
    cualquier comparación por enlace exacto fallara.
    """
    if not link:
        return ""
    try:
        partes = urlparse(link.strip())
    except ValueError:
        return link.strip().lower()

    host = (partes.netloc or "").lower()
    if host.startswith("www."):
        host = host[4:]
    camino = (partes.path or "").rstrip("/")
    # Se descartan consulta y fragmento: los parámetros de seguimiento
    # (utm_*, fbclid) no cambian el artículo.
    return urlunparse(("", host, camino, "", "", "")).lstrip("/")


def _ahora() -> datetime:
    return datetime.now(ZONA_HORARIA)


def _hoy() -> str:
    return _ahora().strftime("%Y-%m-%d")


def _conectar() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def inicializar_db() -> None:
    """Crea las tablas si no existen. Llamar al arrancar la app."""
    with _conectar() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS noticias_publicadas (
                enlace TEXT PRIMARY KEY,
                pais TEXT NOT NULL,
                titulo TEXT NOT NULL,
                primera_vez TEXT NOT NULL,
                ultima_vez TEXT NOT NULL,
                veces INTEGER NOT NULL DEFAULT 1,
                veces_verificada INTEGER NOT NULL DEFAULT 0
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS noticias_vetadas (
                enlace TEXT PRIMARY KEY,
                motivo TEXT NOT NULL,
                anotado_en TEXT NOT NULL
            )
        """)
        conn.commit()


def _fila(enlace_norm: str) -> Optional[sqlite3.Row]:
    with _conectar() as conn:
        return conn.execute(
            "SELECT * FROM noticias_publicadas WHERE enlace = ?",
            (enlace_norm,),
        ).fetchone()


def motivo_para_no_publicar(noticia: Dict, hoy: Optional[str] = None) -> str:
    """
    Devuelve el motivo por el que esta noticia NO debe publicarse según
    la memoria, o "" si no hay ninguno.

    Función pura respecto de la noticia: toda la decisión sale de la
    base de datos y de VETOS_FIJOS, así que se puede probar sin red
    (ver evals/test_memoria_y_alcance.py).
    """
    enlace = normalizar_enlace(noticia.get("link", ""))
    if not enlace:
        return ""

    veto = VETOS_FIJOS.get(enlace)
    if veto:
        motivo, comprobacion = veto
        return f"vetada a mano: {motivo} ({comprobacion})"

    try:
        with _conectar() as conn:
            fila_veto = conn.execute(
                "SELECT motivo, anotado_en FROM noticias_vetadas WHERE enlace = ?",
                (enlace,),
            ).fetchone()
            fila = conn.execute(
                "SELECT * FROM noticias_publicadas WHERE enlace = ?",
                (enlace,),
            ).fetchone()
    except sqlite3.Error:
        # La memoria nunca puede costar una noticia: si la base de
        # datos falla, se publica como si no existiera.
        return ""

    if fila_veto is not None:
        return f"vetada a mano: {fila_veto['motivo']} ({fila_veto['anotado_en']})"

    if fila is None:
        return ""

    hoy = hoy or _hoy()
    try:
        dias = (datetime.strptime(hoy, "%Y-%m-%d")
                - datetime.strptime(fila["ultima_vez"], "%Y-%m-%d")).days
    except ValueError:
        return ""

    # Regla 2 antes que la regla 1: es la más grave y su motivo dice más.
    if fila["veces"] >= VECES_PARA_SOSPECHAR and fila["veces_verificada"] == 0:
        return (
            f"reincidente sin verificar: ya salió en {fila['veces']} reportes "
            f"y nunca se pudo contrastar su fecha con el medio"
        )

    # MISMO DÍA NO ES REPETICIÓN. Regenerar un país con el botón de la
    # interfaz vuelve a pasar por aquí minutos después de haber
    # publicado, y sin esta condición la memoria bloquearía justo lo
    # que se acaba de elegir: el reporte se llenaría con las noticias
    # peores y la regeneración parecería estropear el boletín.
    # Publicar hoy y regenerar hoy son el mismo reporte.
    if 0 < dias < DIAS_SIN_REPETIR:
        return (
            f"ya se publicó el {fila['ultima_vez']} "
            f"(hace {dias} días; van {fila['veces']} reportes)"
        )

    return ""


def filtrar_ya_publicadas(
    noticias: List[Dict], hoy: Optional[str] = None
) -> Tuple[List[Dict], List[Dict]]:
    """
    Separa las noticias en (publicables, repetidas).

    Las repetidas vuelven con la forma del panel de descartadas —
    titulo, fuente, link, nota, razon— para que aparezcan ahí con su
    motivo, igual que cualquier otra decisión del sistema.
    """
    publicables, repetidas = [], []
    for noticia in noticias:
        motivo = motivo_para_no_publicar(noticia, hoy=hoy)
        if motivo:
            repetidas.append({
                "titulo": noticia.get("titulo", ""),
                "fuente": noticia.get("fuente", ""),
                "link": noticia.get("link", ""),
                "nota": noticia.get("nota"),
                "razon": motivo,
            })
        else:
            publicables.append(noticia)
    return publicables, repetidas


def registrar_publicadas(
    noticias: List[Dict], pais: str, hoy: Optional[str] = None
) -> None:
    """
    Anota en la memoria las noticias que acaban de publicarse.

    Se llama DESPUÉS de la selección definitiva, no antes: solo cuenta
    lo que de verdad llegó al reporte. Si falla, no se interrumpe nada
    —la memoria es una mejora, no un requisito— pero conviene que el
    fallo no pase del todo inadvertido, así que se propaga el error de
    programación y se tragan solo los de base de datos.
    """
    if not noticias:
        return
    hoy = hoy or _hoy()
    try:
        with _conectar() as conn:
            for noticia in noticias:
                enlace = normalizar_enlace(noticia.get("link", ""))
                if not enlace:
                    continue
                verificada = 1 if noticia.get("fecha_verificada") else 0
                # La cuenta de "veces" cuenta REPORTES DISTINTOS, no
                # escrituras: si se regenera un país tres veces en una
                # tarde, sigue siendo una aparición. Sin esto, dos
                # regeneraciones bastarían para que una noticia
                # legítima pareciera reincidente y dejara de salir.
                conn.execute("""
                    INSERT INTO noticias_publicadas
                        (enlace, pais, titulo, primera_vez, ultima_vez,
                         veces, veces_verificada)
                    VALUES (?, ?, ?, ?, ?, 1, ?)
                    ON CONFLICT(enlace) DO UPDATE SET
                        ultima_vez = excluded.ultima_vez,
                        titulo = excluded.titulo,
                        veces = noticias_publicadas.veces
                                + (CASE WHEN noticias_publicadas.ultima_vez = excluded.ultima_vez
                                        THEN 0 ELSE 1 END),
                        veces_verificada = noticias_publicadas.veces_verificada
                                + (CASE WHEN noticias_publicadas.ultima_vez = excluded.ultima_vez
                                             OR excluded.veces_verificada = 0
                                        THEN 0 ELSE 1 END)
                """, (enlace, pais, noticia.get("titulo", ""), hoy, hoy, verificada))
            conn.commit()
    except sqlite3.Error:
        return


def vetar(enlace: str, motivo: str) -> None:
    """
    Anota un veto manual. Para la persona que comprueba una noticia y
    descubre que está mal: a partir de aquí no vuelve a publicarse, y
    el motivo queda escrito.
    """
    enlace_norm = normalizar_enlace(enlace)
    if not enlace_norm:
        return
    with _conectar() as conn:
        conn.execute("""
            INSERT INTO noticias_vetadas (enlace, motivo, anotado_en)
            VALUES (?, ?, ?)
            ON CONFLICT(enlace) DO UPDATE SET
                motivo = excluded.motivo,
                anotado_en = excluded.anotado_en
        """, (enlace_norm, motivo, _hoy()))
        conn.commit()


def quitar_veto(enlace: str) -> bool:
    """Deshace un veto manual. Devuelve True si había algo que quitar."""
    enlace_norm = normalizar_enlace(enlace)
    with _conectar() as conn:
        cur = conn.execute(
            "DELETE FROM noticias_vetadas WHERE enlace = ?", (enlace_norm,))
        conn.commit()
        return cur.rowcount > 0


def historial(enlace: str) -> Optional[Dict]:
    """Lo que la memoria sabe de un enlace. Para diagnosticar."""
    fila = _fila(normalizar_enlace(enlace))
    return dict(fila) if fila is not None else None


def reincidentes(minimo: int = VECES_PARA_SOSPECHAR) -> List[Dict]:
    """
    Noticias que han salido varias veces sin poder verificarse nunca.
    Es la lista que conviene revisar a mano de vez en cuando: cada
    entrada es, o bien un medio que no se deja verificar, o bien una
    noticia mal fechada que el sistema ya dejó de publicar.
    """
    with _conectar() as conn:
        filas = conn.execute("""
            SELECT * FROM noticias_publicadas
            WHERE veces >= ? AND veces_verificada = 0
            ORDER BY veces DESC, ultima_vez DESC
        """, (minimo,)).fetchall()
    return [dict(f) for f in filas]


def limpiar_memoria_antigua(dias_a_conservar: int = DIAS_A_CONSERVAR) -> int:
    """Borra lo más viejo que N días. Los vetos nunca se borran."""
    limite = (_ahora() - timedelta(days=dias_a_conservar)).strftime("%Y-%m-%d")
    with _conectar() as conn:
        cur = conn.execute(
            "DELETE FROM noticias_publicadas WHERE ultima_vez < ?", (limite,))
        conn.commit()
        return cur.rowcount
