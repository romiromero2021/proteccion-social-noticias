"""
AGENTE 2 — Sintetizador y generador de reporte (summarizer.py)
================================================================
Responsabilidad única: recibir las noticias crudas del Agente 1,
seleccionar las 3 más relevantes por país, generar un resumen breve
de cada una usando Gemini, y producir un documento Word (.docx)
con el reporte final.
"""

import io
from datetime import datetime
from typing import List, Dict

from google import genai
from docx import Document
from docx.shared import Pt, RGBColor, Inches
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.style import WD_STYLE_TYPE
from docx.oxml.ns import qn

# ---------------------------------------------------------------------------
# 1. CONFIGURACIÓN DE GEMINI
# ---------------------------------------------------------------------------

MODELO_GEMINI = "gemini-2.5-flash-lite"  # rápido, económico, ideal para resúmenes cortos


def resumir_noticia(titulo: str, snippet: str, pais: str, gemini_api_key: str) -> str:
    """
    Genera un resumen breve (2-3 frases) de una noticia usando Gemini.
    Si Gemini falla por cualquier razón, hace fallback al snippet original
    para que la app nunca se caiga por completo.
    """
    cliente = genai.Client(api_key=gemini_api_key)

    prompt = (
        "Eres un analista de políticas públicas. Redacta un resumen breve "
        "(máximo 3 frases, en español neutro, tono informativo y objetivo) "
        "de la siguiente noticia sobre programas de protección social en "
        f"{pais}. No inventes datos que no estén en el texto fuente.\n\n"
        f"Título: {titulo}\n"
        f"Extracto original: {snippet}\n\n"
        "Resumen:"
    )

    try:
        respuesta = cliente.models.generate_content(
            model=MODELO_GEMINI,
            contents=prompt,
        )
        texto = (respuesta.text or "").strip()
        return texto if texto else snippet
    except Exception:
        # Fallback seguro: si Gemini falla (rate limit, red, etc.)
        # usamos el snippet crudo para no romper el flujo.
        return snippet or "Resumen no disponible."


def seleccionar_top_n(noticias: List[Dict], n: int = 3) -> List[Dict]:
    """
    Selecciona las n noticias más relevantes de una lista.
    Criterio simple: las primeras n en el orden devuelto por SerpAPI,
    que ya viene ordenado por relevancia/recencia de Google News.
    Se descartan entradas con error o sin título.
    """
    validas = [
        noticia for noticia in noticias
        if "error" not in noticia and noticia.get("titulo")
    ]
    return validas[:n]


def procesar_pais(
    pais: str,
    noticias_crudas: List[Dict],
    gemini_api_key: str,
    n_noticias: int = 3,
) -> Dict:
    """
    Para un país: selecciona top-N noticias y genera resumen de cada una.

    Returns
    -------
    {"pais": str, "noticias": [{"titulo", "fuente", "fecha", "link", "resumen"}],
     "sin_resultados": bool}
    """
    top = seleccionar_top_n(noticias_crudas, n_noticias)

    if not top:
        return {"pais": pais, "noticias": [], "sin_resultados": True}

    procesadas = []
    for noticia in top:
        resumen = resumir_noticia(
            titulo=noticia["titulo"],
            snippet=noticia.get("snippet", ""),
            pais=pais,
            gemini_api_key=gemini_api_key,
        )
        procesadas.append({
            "titulo": noticia["titulo"],
            "fuente": noticia.get("fuente", "Fuente desconocida"),
            "fecha": noticia.get("fecha", ""),
            "link": noticia.get("link", ""),
            "resumen": resumen,
        })

    return {"pais": pais, "noticias": procesadas, "sin_resultados": False}


def procesar_todos_los_paises(
    noticias_por_pais: Dict[str, List[Dict]],
    gemini_api_key: str,
    n_noticias: int = 3,
    progress_callback=None,
) -> List[Dict]:
    """
    Orquesta el procesamiento (selección + resumen) para todos los países.
    progress_callback: callback(pais_actual, indice, total) opcional.
    """
    resultado = []
    paises = list(noticias_por_pais.keys())

    for i, pais in enumerate(paises):
        if progress_callback:
            progress_callback(pais, i + 1, len(paises))

        resultado.append(
            procesar_pais(pais, noticias_por_pais[pais], gemini_api_key, n_noticias)
        )

    return resultado


# ---------------------------------------------------------------------------
# 2. GENERACIÓN DEL DOCUMENTO WORD
# ---------------------------------------------------------------------------

COLOR_TITULO = RGBColor(0x1F, 0x3A, 0x5F)   # azul oscuro institucional
COLOR_PAIS = RGBColor(0x2E, 0x75, 0xB6)     # azul medio
COLOR_GRIS = RGBColor(0x59, 0x59, 0x59)     # gris para metadatos


def _configurar_estilos(doc: Document):
    """Define fuente Arial por defecto y tamaños consistentes."""
    estilo_normal = doc.styles["Normal"]
    estilo_normal.font.name = "Arial"
    estilo_normal.font.size = Pt(11)
    # Asegurar fuente también para texto de Asia oriental (consistencia en Word)
    rpr = estilo_normal.element.get_or_add_rPr()
    rfonts = rpr.find(qn("w:rFonts"))
    if rfonts is None:
        rfonts = rpr.makeelement(qn("w:rFonts"), {})
        rpr.append(rfonts)
    rfonts.set(qn("w:eastAsia"), "Arial")


def _agregar_portada(doc: Document, fecha_str: str):
    titulo = doc.add_paragraph()
    titulo.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = titulo.add_run("Resumen de Noticias\nProgramas de Protección Social en Centroamérica y el Caribe")
    run.font.size = Pt(22)
    run.font.bold = True
    run.font.color.rgb = COLOR_TITULO

    subtitulo = doc.add_paragraph()
    subtitulo.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run2 = subtitulo.add_run(f"Reporte generado el {fecha_str}")
    run2.font.size = Pt(12)
    run2.font.italic = True
    run2.font.color.rgb = COLOR_GRIS

    nota = doc.add_paragraph()
    nota.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run3 = nota.add_run(
        "Países incluidos: Costa Rica, Cuba, El Salvador, Guatemala, Haití, "
        "Honduras, México, Nicaragua, Panamá y República Dominicana."
    )
    run3.font.size = Pt(10)
    run3.font.color.rgb = COLOR_GRIS

    doc.add_paragraph()  # espacio


def _agregar_pais(doc: Document, datos_pais: Dict):
    pais = datos_pais["pais"]

    encabezado = doc.add_heading(level=1)
    run = encabezado.add_run(pais)
    run.font.color.rgb = COLOR_PAIS
    run.font.name = "Arial"

    if datos_pais["sin_resultados"]:
        p = doc.add_paragraph()
        run_vacio = p.add_run(
            "No se encontraron noticias relevantes sobre programas de "
            "protección social en las últimas 24 horas para este país."
        )
        run_vacio.font.italic = True
        run_vacio.font.color.rgb = COLOR_GRIS
        doc.add_paragraph()
        return

    for idx, noticia in enumerate(datos_pais["noticias"], start=1):
        sub = doc.add_heading(level=2)
        sub_run = sub.add_run(f"{idx}. {noticia['titulo']}")
        sub_run.font.size = Pt(13)
        sub_run.font.name = "Arial"
        sub_run.font.color.rgb = COLOR_TITULO

        meta = doc.add_paragraph()
        meta_run = meta.add_run(f"Fuente: {noticia['fuente']}  |  Fecha: {noticia['fecha']}")
        meta_run.font.size = Pt(9)
        meta_run.font.italic = True
        meta_run.font.color.rgb = COLOR_GRIS

        resumen = doc.add_paragraph()
        resumen.add_run(noticia["resumen"]).font.size = Pt(11)

        if noticia.get("link"):
            link_p = doc.add_paragraph()
            link_run = link_p.add_run(f"Enlace: {noticia['link']}")
            link_run.font.size = Pt(9)
            link_run.font.color.rgb = RGBColor(0x10, 0x6E, 0xBE)

        doc.add_paragraph()  # espacio entre noticias

    # línea divisoria simple entre países (borde inferior de un párrafo)
    divisor = doc.add_paragraph()
    pPr = divisor._p.get_or_add_pPr()
    pBdr = pPr.makeelement(qn("w:pBdr"), {})
    bottom = pPr.makeelement(qn("w:bottom"), {
        qn("w:val"): "single", qn("w:sz"): "6", qn("w:space"): "1", qn("w:color"): "2E75B6"
    })
    pBdr.append(bottom)
    pPr.append(pBdr)


def generar_documento_word(reportes_por_pais: List[Dict]) -> io.BytesIO:
    """
    Genera el .docx final en memoria (BytesIO) — ideal para servirlo
    directamente como descarga desde Streamlit sin tocar el disco.
    """
    doc = Document()
    _configurar_estilos(doc)

    MESES_ES = {
        1: "enero", 2: "febrero", 3: "marzo", 4: "abril", 5: "mayo", 6: "junio",
        7: "julio", 8: "agosto", 9: "septiembre", 10: "octubre", 11: "noviembre", 12: "diciembre",
    }
    ahora = datetime.now()
    fecha_str = f"{ahora.day} de {MESES_ES[ahora.month]} de {ahora.year}, {ahora.strftime('%H:%M')}"

    _agregar_portada(doc, fecha_str)

    for datos_pais in reportes_por_pais:
        _agregar_pais(doc, datos_pais)

    buffer = io.BytesIO()
    doc.save(buffer)
    buffer.seek(0)
    return buffer
