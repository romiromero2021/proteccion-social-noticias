"""
CACHÉ (cache.py)
==================
Capa de persistencia compartida entre los dos agentes.

Objetivo: si varios usuarios abren la app el mismo día, no se repiten
búsquedas en SerpAPI ni llamadas a Gemini para un país ya consultado
hoy. También habilita la regeneración "país por país" sin perder los
resultados ya cacheados de los otros países.

Almacena, por (pais, fecha):
  - noticias_crudas   -> salida cruda del Agente 1 (lista de dicts)
  - reporte_procesado -> salida ya resumida del Agente 2 (dict)
  - actualizado_en    -> timestamp de la última escritura

Usa SQLite (archivo local .db) — suficiente para este volumen de datos
(10 países/día) y no requiere infraestructura externa. En Streamlit
Cloud el archivo persiste mientras el contenedor de la app esté vivo;
si la app se reinicia (redeploy, inactividad prolongada), el caché se
pierde y simplemente se vuelve a poblar con las próximas búsquedas.
"""

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

DB_PATH = Path(__file__).parent / "cache_noticias.db"


def _conectar() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def inicializar_db():
    """Crea la tabla de caché si no existe. Llamar al inicio de la app."""
    with _conectar() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS cache_pais_dia (
                pais TEXT NOT NULL,
                fecha TEXT NOT NULL,
                noticias_crudas TEXT NOT NULL,
                reporte_procesado TEXT NOT NULL,
                actualizado_en TEXT NOT NULL,
                PRIMARY KEY (pais, fecha)
            )
        """)
        conn.commit()


def _fecha_hoy() -> str:
    """Fecha del día en formato YYYY-MM-DD, usada como parte de la clave."""
    return datetime.now().strftime("%Y-%m-%d")


def obtener_cache_pais(pais: str, fecha: Optional[str] = None) -> Optional[Dict]:
    """
    Devuelve el registro cacheado de un país para una fecha (hoy por defecto),
    o None si no existe caché para esa combinación.

    Returns
    -------
    {"noticias_crudas": [...], "reporte_procesado": {...}, "actualizado_en": str} | None
    """
    fecha = fecha or _fecha_hoy()
    with _conectar() as conn:
        fila = conn.execute(
            "SELECT * FROM cache_pais_dia WHERE pais = ? AND fecha = ?",
            (pais, fecha),
        ).fetchone()

    if fila is None:
        return None

    return {
        "noticias_crudas": json.loads(fila["noticias_crudas"]),
        "reporte_procesado": json.loads(fila["reporte_procesado"]),
        "actualizado_en": fila["actualizado_en"],
    }


def guardar_cache_pais(
    pais: str,
    noticias_crudas: List[Dict],
    reporte_procesado: Dict,
    fecha: Optional[str] = None,
):
    """Inserta o actualiza (upsert) el caché de un país para el día de hoy."""
    fecha = fecha or _fecha_hoy()
    ahora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    with _conectar() as conn:
        conn.execute("""
            INSERT INTO cache_pais_dia (pais, fecha, noticias_crudas, reporte_procesado, actualizado_en)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(pais, fecha) DO UPDATE SET
                noticias_crudas = excluded.noticias_crudas,
                reporte_procesado = excluded.reporte_procesado,
                actualizado_en = excluded.actualizado_en
        """, (
            pais,
            fecha,
            json.dumps(noticias_crudas, ensure_ascii=False),
            json.dumps(reporte_procesado, ensure_ascii=False),
            ahora,
        ))
        conn.commit()


def obtener_cache_multiples(paises: List[str], fecha: Optional[str] = None) -> Dict[str, Optional[Dict]]:
    """Versión batch de obtener_cache_pais para varios países a la vez."""
    return {pais: obtener_cache_pais(pais, fecha) for pais in paises}


def limpiar_cache_antiguo(dias_a_conservar: int = 3):
    """
    Borra entradas de caché más antiguas que N días, para que la base de
    datos no crezca indefinidamente. Llamar ocasionalmente (ej. al inicio
    de la app), no es crítico que corra siempre.
    """
    from datetime import timedelta
    fecha_limite = (datetime.now() - timedelta(days=dias_a_conservar)).strftime("%Y-%m-%d")
    with _conectar() as conn:
        conn.execute("DELETE FROM cache_pais_dia WHERE fecha < ?", (fecha_limite,))
        conn.commit()
