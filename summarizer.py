"""
AGENTE 2 — Sintetizador y generador de reporte (summarizer.py)
================================================================
Responsabilidad única: recibir las noticias crudas del Agente 1
(separadas en "aceptadas" y "descartadas_marginales"), completar el
cupo de noticias por país (usando un agente verificador con Groq
sobre las descartadas marginales si hace falta), generar un resumen
breve de cada una usando Groq (Llama 3.3 70B), y producir un
documento Word (.docx) con el reporte final.
"""

import io
import time
from datetime import datetime
from cache import ZONA_HORARIA
from scraper import deduplicar_noticias, titulos_similares
from typing import List, Dict

import groq
from groq import Groq
from docx import Document
from docx.shared import Pt, RGBColor, Inches
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.style import WD_STYLE_TYPE
from docx.oxml.ns import qn

# ---------------------------------------------------------------------------
# 1. CONFIGURACIÓN DE GROQ — modelos y cadena de respaldo ante deprecaciones
# ---------------------------------------------------------------------------
# Groq retira modelos periódicamente (avisa por correo y los apaga en una
# fecha fija). El 16-ago-2026 apagó "llama-3.3-70b-versatile", que era el
# modelo único de esta app: a partir de esa fecha TODAS las llamadas al
# Agente 2 (verificación y resúmenes) empezaron a fallar en silencio, y la
# app quedó mostrando solo el texto original de cada noticia.
#
# Para que una próxima deprecación no vuelva a tumbar la app, ya no se usa
# un modelo único sino una LISTA en orden de preferencia. Si el primero
# responde "modelo no encontrado/retirado", el sistema pasa automáticamente
# al siguiente y sigue trabajando (ver _llamar_groq_con_reintentos). El
# modelo que funciona se recuerda durante la ejecución, así que el fallback
# se paga una sola vez y no en cada una de las ~50 llamadas del reporte.
#
# La lista mezcla familias distintas a propósito: si Groq retira toda una
# familia de golpe, la otra sigue en pie.
#
# MANTENIMIENTO: cuando llegue un correo de deprecación de Groq, basta con
# agregar el modelo nuevo al inicio de esta lista. Tabla oficial de retiros:
# https://console.groq.com/docs/deprecations
MODELOS_GROQ = [
    "openai/gpt-oss-120b",   # reemplazo recomendado por Groq para llama-3.3-70b (ago-2026)
    "openai/gpt-oss-20b",    # hermano menor: más rápido y barato, misma familia
    "qwen/qwen3.8-27b",      # último recurso, otra familia (sucesor de qwen3.6-27b, retirado 14-sep-2026)
]

# Índice del modelo que está funcionando ahora mismo. Arranca en 0 (el
# preferido) y solo avanza si Groq confirma que ese modelo ya no existe.
_indice_modelo_activo = 0

# Fragmentos que aparecen en el mensaje de error de Groq cuando un modelo
# fue retirado o no existe. Se detectan por texto porque Groq los reporta
# como un 404/400 genérico, sin un código de error propio distinguible.
_SENALES_MODELO_RETIRADO = (
    "model_not_found",
    "does not exist",
    "no longer supported",
    "decommissioned",
    "has been deprecated",
    "model_decommissioned",
)

MAX_REINTENTOS = 3
ESPERA_BASE_SEGUNDOS = 2  # backoff exponencial: 2s, 4s, 8s
# Ritmo entre llamadas consecutivas a Groq. El factor que manda NO es el
# límite de peticiones por minuto (30 RPM) sino el de TOKENS por minuto:
# openai/gpt-oss-120b tiene 8,000 TPM en el plan gratuito, menos que los
# 12,000 del modelo anterior. Cada resumen consume ~440 tokens (entrada +
# salida), así que el techo real es ~18 llamadas/minuto ≈ 3.3 s entre
# llamadas. Con el valor anterior (1.3 s) la app pedía ~20,500 tokens/min
# y chocaba de lleno contra el límite: los reintentos con espera lo
# absorbían, pero el reporte tardaba de forma impredecible y algunos
# resúmenes terminaban cayendo al texto original.
# Con 3.5 s, un reporte completo (50 llamadas) toma ~3 minutos de forma
# estable. Si algún día se sube a un plan de pago, este valor puede bajar.
ESPERA_ENTRE_LLAMADAS_SEGUNDOS = 3.5


def modelo_en_uso() -> str:
    """Nombre del modelo de Groq que la app está usando en este momento."""
    return MODELOS_GROQ[_indice_modelo_activo]


def _es_error_de_modelo_retirado(excepcion: Exception) -> bool:
    """True si el error indica que el modelo pedido ya no existe en Groq."""
    mensaje = str(excepcion).lower()
    return any(senal in mensaje for senal in _SENALES_MODELO_RETIRADO)

# Frases típicas de una "meta-explicación" (el modelo explica que no puede
# resumir en vez de resumir). Si el resumen generado contiene alguna de
# estas, se descarta y se usa el título como respaldo. Es una red de
# seguridad adicional al prompt — los LLMs no son 100% deterministas.
_PATRONES_META_EXPLICACION = (
    "no hay información disponible",
    "no hay suficiente información",
    "no hay información suficiente",
    "no proporciona suficiente información",
    "información insuficiente",
    "no se proporciona",
    "no es posible ofrecer un resumen",
    "no es posible generar un resumen",
    "no cuento con suficiente información",
    "no se cuenta con suficiente información",
    "no dispongo de suficiente información",
    "el extracto no contiene",
    "el extracto original no proporciona",
    "no se incluye información adicional",
    "sin más contexto no es posible",
    "no se puede redactar un resumen",
)


def _es_meta_explicacion(texto: str) -> bool:
    """Detecta si el texto generado es una explicación de por qué no se
    puede resumir, en vez de un resumen real."""
    texto_normalizado = texto.lower()
    return any(patron in texto_normalizado for patron in _PATRONES_META_EXPLICACION)


def _llamar_groq_con_reintentos(
    groq_api_key: str,
    prompt: str,
    temperature: float,
    max_completion_tokens: int,
):
    """
    Única puerta de salida hacia Groq para todo el módulo. Resuelve dos
    problemas distintos que antes cada función manejaba por su cuenta (o
    no manejaba):

    1. ERRORES TRANSITORIOS (rate limit 429, 5xx, caídas de conexión):
       se reintenta el mismo modelo con backoff exponencial. Es el modo de
       fallo más frecuente cuando el volumen crece (~50 llamadas por
       reporte contra un límite de 30 por minuto).

    2. MODELO RETIRADO: si Groq responde que el modelo ya no existe, no
       tiene sentido reintentarlo — se avanza al siguiente de MODELOS_GROQ
       y se recuerda ese cambio para el resto de la ejecución, de modo que
       las llamadas siguientes vayan directo al modelo que sí funciona.

    Returns
    -------
    (texto, error): texto es la respuesta de Groq (str) si alguna llamada
    tuvo éxito, o None si fallaron todas; error es None en éxito, o un str
    describiendo el último fallo.
    """
    global _indice_modelo_activo

    ultimo_error = None

    # Se recorren los modelos disponibles desde el activo en adelante.
    while _indice_modelo_activo < len(MODELOS_GROQ):
        modelo = MODELOS_GROQ[_indice_modelo_activo]
        # Solo se cambia de modelo cuando Groq CONFIRMA que el actual ya
        # no existe. Un rate limit o una caída pasajera no son motivo:
        # son problemas de la cuenta o del servicio, no del modelo, y el
        # siguiente de la lista chocaría contra exactamente lo mismo.
        modelo_retirado = False

        for intento in range(1, MAX_REINTENTOS + 1):
            try:
                cliente = Groq(api_key=groq_api_key)
                respuesta = cliente.chat.completions.create(
                    model=modelo,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=temperature,
                    max_completion_tokens=max_completion_tokens,
                )
                texto = (respuesta.choices[0].message.content or "").strip()
                if texto:
                    return texto, None
                ultimo_error = f"Groq ({modelo}) devolvió una respuesta vacía."
                return None, ultimo_error

            except groq.RateLimitError as e:
                ultimo_error = f"Intento {intento} [{modelo}]: RateLimitError (429) - {e}"
                if intento < MAX_REINTENTOS:
                    time.sleep(ESPERA_BASE_SEGUNDOS * (2 ** (intento - 1)))
                    continue

            except groq.APIStatusError as e:
                ultimo_error = f"Intento {intento} [{modelo}]: APIStatusError {e.status_code} - {e}"
                if _es_error_de_modelo_retirado(e):
                    modelo_retirado = True
                    break  # modelo muerto: no reintentar, probar el siguiente
                # 5xx son transitorios; otros 4xx (key inválida, etc.) no
                # se arreglan reintentando ni cambiando de modelo.
                if e.status_code >= 500 and intento < MAX_REINTENTOS:
                    time.sleep(ESPERA_BASE_SEGUNDOS * (2 ** (intento - 1)))
                    continue
                return None, ultimo_error

            except groq.APIConnectionError as e:
                ultimo_error = f"Intento {intento} [{modelo}]: APIConnectionError - {e}"
                if intento < MAX_REINTENTOS:
                    time.sleep(ESPERA_BASE_SEGUNDOS * (2 ** (intento - 1)))
                    continue

            except Exception as e:
                ultimo_error = f"Intento {intento} [{modelo}]: {type(e).__name__} - {e}"
                if _es_error_de_modelo_retirado(e):
                    modelo_retirado = True
                    break  # modelo muerto: probar el siguiente
                if intento < MAX_REINTENTOS:
                    time.sleep(ESPERA_BASE_SEGUNDOS * (2 ** (intento - 1)))
                    continue

        # Fallo transitorio (rate limit, caída de red) tras agotar los
        # reintentos: se devuelve el error SIN cambiar de modelo, porque
        # el problema no es el modelo. La llamada siguiente volverá a
        # empezar por el mismo, que es lo correcto.
        if not modelo_retirado:
            return None, ultimo_error

        # Modelo confirmado como retirado: se avanza al siguiente de la
        # cadena (y se recuerda para las llamadas posteriores). Si no
        # queda ninguno, se agota aquí.
        if _indice_modelo_activo + 1 < len(MODELOS_GROQ):
            _indice_modelo_activo += 1
            continue
        break

    return None, ultimo_error


def verificar_relevancia_llm(titulo: str, snippet: str, pais: str, groq_api_key: str) -> bool:
    """
    Agente verificador (Capa 3 de la estrategia híbrida) — usa Groq
    para confirmar si una noticia candidata es genuinamente relevante
    al tema en el país buscado, atrapando casos ambiguos que ningún
    filtro de texto (palabras clave, TLD, demónimos) puede anticipar
    de forma exhaustiva.

    Diseñado para usarse SOLO cuando, tras la búsqueda con site: y los
    filtros de texto, quedan menos candidatas que las necesarias — no
    se llama para cada noticia de cada país, para mantener bajo el
    consumo de cuota de Groq (ver _completar_con_verificacion_llm).

    POLÍTICA ANTE FALLO (fail-closed): si Groq falla incluso tras los
    reintentos y el cambio de modelo, la noticia NO se rescata. Toda
    candidata que llega aquí ya fue descartada por un filtro
    determinista por un motivo concreto (menciona otro país, no calza
    con el tema...); rescatarla sin verificación real invierte la carga
    de la prueba. Y es justo cuando Groq está caído o saturado —como
    pasó tras la deprecación del modelo en agosto— cuando un fail-open
    dejaría entrar ruido de forma sistemática, en el peor momento
    posible. Perder una noticia dudosa cuesta menos que publicar una
    incorrecta.

    Returns
    -------
    True solo si Groq confirma la relevancia explícitamente; False si la
    niega o si el verificador no pudo ejecutarse.
    """
    prompt = (
        f"Eres un verificador estricto de relevancia temática para {pais}.\n\n"
        f"Título: {titulo}\n"
        f"Extracto: {snippet}\n\n"
        f"Pregunta: ¿Esta noticia trata genuinamente sobre programas, "
        f"políticas o instituciones PÚBLICAS de protección social, "
        f"seguridad social, asistencia social o desarrollo social "
        f"DE {pais}?\n\n"
        f"Responde NO si se cumple cualquiera de estos casos:\n"
        f"- La noticia es de otro país o sobre otro país (aunque el "
        f"evento ocurra físicamente en {pais}).\n"
        f"- Es caridad puntual, donaciones o colectas de entidades "
        f"privadas (empresas, clubes, fundaciones, iglesias), no un "
        f"programa o política pública de protección social.\n"
        f"- La ayuda está dirigida principalmente a población de otro "
        f"país (ej. migrantes o familias de otra nacionalidad).\n"
        f"- Es sobre loterías, sorteos, deportes, farándula o política "
        f"general sin relación directa con estos programas.\n"
        f"- Solo menciona una institución de protección social de "
        f"forma tangencial, sin que sea el tema central.\n\n"
        f"Responde ÚNICAMENTE con una palabra: SI o NO."
    )

    texto, _error = _llamar_groq_con_reintentos(
        groq_api_key, prompt, temperature=0, max_completion_tokens=10
    )
    if texto is None:
        return False  # fail-closed: sin verificación real no hay rescate (ver docstring)

    texto = texto.upper()
    # Coincidencia estricta: solo cuenta como "relevante" si la
    # primera palabra de la respuesta ES "SI"/"SÍ" (ignorando
    # puntuación final como "SI." o "SÍ,") — no basta con que la
    # respuesta comience con la letra "S" (ej. "Sin información
    # suficiente" empieza con S pero significa lo contrario).
    primera_palabra = texto.split()[0].strip(".,;:!¡¿?") if texto.split() else ""
    return primera_palabra in ("SI", "SÍ")


def resumir_noticia(titulo: str, snippet: str, pais: str, groq_api_key: str) -> Dict:
    """
    Genera un resumen breve (2-3 frases) de una noticia usando el modelo
    de Groq que esté activo (ver MODELOS_GROQ), a través de
    _llamar_groq_con_reintentos: backoff exponencial ante rate limit,
    5xx y fallos de conexión, y cambio automático de modelo si el actual
    fue retirado. Si aun así falla todo, retorna el snippet original
    como respaldo seguro.

    Returns
    -------
    {"resumen": str, "error_detalle": str | None}
    El error_detalle queda registrado (no se le muestra al usuario final
    en la UI por defecto, pero permite diagnosticar fallas reales en vez
    de ocultarlas silenciosamente).
    """
    prompt = (
        "Eres un analista de políticas públicas. Redacta un resumen breve "
        "(máximo 3 frases, en español neutro, tono informativo y objetivo) "
        "de la siguiente noticia sobre programas de protección social en "
        f"{pais}.\n\n"
        f"Título: {titulo}\n"
        f"Extracto original: {snippet}\n\n"
        "Instrucciones importantes:\n"
        "- No inventes datos, cifras ni detalles que no estén en el título o el extracto.\n"
        "- Si el extracto es breve o vago, igual redacta un resumen útil basándote en "
        "lo que el título y el extracto sí permiten afirmar (por ejemplo, el tema "
        "general, la institución involucrada, o la acción mencionada).\n"
        "- NUNCA respondas explicando que no hay suficiente información, que el "
        "extracto es insuficiente, o frases similares sobre la falta de datos. "
        "En su lugar, redacta como resumen una versión breve y natural del propio "
        "título, en tono informativo.\n"
        "- Responde ÚNICAMENTE con el resumen final, sin introducciones como "
        "'Resumen:' ni comentarios sobre tu propio proceso.\n\n"
        "Resumen:"
    )

    texto, error = _llamar_groq_con_reintentos(
        groq_api_key, prompt, temperature=0.3, max_completion_tokens=200
    )

    if texto is not None:
        if _es_meta_explicacion(texto):
            # El modelo, a pesar de la instrucción, respondió explicando
            # que no tiene suficiente información en vez de resumir.
            # Red de seguridad: usamos el título como resumen, en vez
            # de mostrarle al usuario ese tipo de respuesta.
            return {"resumen": titulo, "error_detalle": None}
        return {"resumen": texto, "error_detalle": None}

    # Fallaron todos los modelos e intentos: respaldo con el snippet.
    return {
        "resumen": snippet or "Resumen no disponible.",
        "error_detalle": error,
    }


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
    # Red de seguridad final contra duplicados (por link y por similitud
    # de título) — scraper.py ya deduplica, pero esta capa garantiza que
    # el reporte final nunca muestre el mismo evento dos veces, venga de
    # donde venga (caché de versiones anteriores incluido).
    return deduplicar_noticias(validas)[:n]


def _completar_con_verificacion_llm(
    aceptadas: List[Dict],
    descartadas_marginales: List[Dict],
    n_necesarias: int,
    pais: str,
    groq_api_key: str,
) -> List[Dict]:
    """
    Agente verificador orquestador (Capa 3 de la estrategia híbrida):
    si "aceptadas" ya tiene al menos n_necesarias, las devuelve tal
    cual, SIN tocar Groq (sin costo extra — caso común, cobertura
    normal). Si faltan, recorre "descartadas_marginales" (las que los
    filtros de texto de scraper.py ya habían descartado) y las pasa
    una por una por verificar_relevancia_llm, añadiendo las que se
    confirmen relevantes hasta completar n_necesarias o agotar las
    candidatas disponibles.

    Deduplica por link contra las ya aceptadas (y entre las propias
    descartadas_marginales): la misma noticia puede aparecer tanto en
    "aceptadas" como en "descartadas_marginales" si las dos capas de
    búsqueda (site: y anclas de texto) la trajeron por separado con
    una clasificación distinta — sin este chequeo, el verificador
    podía "rescatar" una noticia que ya estaba en el reporte, dejando
    el mismo artículo duplicado con dos resúmenes distintos.

    Esto mantiene el costo de Groq bajo en el caso común y solo lo
    activa cuando realmente hace falta completar el cupo de noticias.
    """
    if len(aceptadas) >= n_necesarias:
        return aceptadas[:n_necesarias]

    resultado = list(aceptadas)
    links_ya_incluidos = {n["link"] for n in resultado if n.get("link")}

    candidatas_sin_revisar = 0
    for candidata in descartadas_marginales:
        if len(resultado) >= n_necesarias:
            break

        link = candidata.get("link")
        if link and link in links_ya_incluidos:
            continue  # ya está en el reporte (vino de la otra capa) — no revisar de nuevo

        # Mismo evento con otro link (artículo distinto): tampoco se
        # revisa ni se incluye — evita duplicados y ahorra la llamada
        # a Groq que costaría verificarla.
        if any(titulos_similares(candidata.get("titulo", ""), ya.get("titulo", ""))
               for ya in resultado):
            continue

        if candidatas_sin_revisar > 0:
            time.sleep(ESPERA_ENTRE_LLAMADAS_SEGUNDOS)
        candidatas_sin_revisar += 1

        es_relevante = verificar_relevancia_llm(
            titulo=candidata["titulo"],
            snippet=candidata.get("snippet", ""),
            pais=pais,
            groq_api_key=groq_api_key,
        )
        if es_relevante:
            resultado.append(candidata)
            if link:
                links_ya_incluidos.add(link)

    return resultado


def procesar_pais(
    pais: str,
    resultado_busqueda: Dict,
    groq_api_key: str,
    n_noticias: int = 5,
) -> Dict:
    """
    Para un país: completa el cupo de noticias (usando el agente
    verificador de Groq si hace falta) y genera resumen de cada una.

    Parameters
    ----------
    resultado_busqueda : el dict devuelto por scraper.buscar_noticias_pais,
                con keys "aceptadas", "descartadas_marginales", "error".

    Returns
    -------
    {"pais": str, "noticias": [{"titulo", "fuente", "fecha", "link", "resumen"}],
     "sin_resultados": bool, "errores_llm": [str, ...]}
    """
    aceptadas = seleccionar_top_n(resultado_busqueda.get("aceptadas", []), n_noticias)
    descartadas = resultado_busqueda.get("descartadas_marginales", [])

    necesito_verificador = len(aceptadas) < n_noticias
    top = _completar_con_verificacion_llm(aceptadas, descartadas, n_noticias, pais, groq_api_key)

    if not top:
        return {"pais": pais, "noticias": [], "sin_resultados": True, "errores_llm": []}

    procesadas = []
    errores_llm = []
    for i, noticia in enumerate(top):
        if i > 0 or necesito_verificador:
            # Pequeña pausa entre llamadas consecutivas para repartir el
            # volumen dentro del límite de 30 solicitudes/minuto de Groq.
            # Se aplica también antes de la primera llamada de este bucle
            # si el verificador ya hizo llamadas justo antes (evita una
            # ráfaga en la transición verificador -> resúmenes).
            time.sleep(ESPERA_ENTRE_LLAMADAS_SEGUNDOS)

        resultado = resumir_noticia(
            titulo=noticia["titulo"],
            snippet=noticia.get("snippet", ""),
            pais=pais,
            groq_api_key=groq_api_key,
        )
        if resultado["error_detalle"]:
            errores_llm.append(f"{noticia['titulo'][:50]}... -> {resultado['error_detalle']}")

        procesadas.append({
            "titulo": noticia["titulo"],
            "fuente": noticia.get("fuente", "Fuente desconocida"),
            "fecha": noticia.get("fecha", ""),
            "link": noticia.get("link", ""),
            "resumen": resultado["resumen"],
        })

    return {"pais": pais, "noticias": procesadas, "sin_resultados": False, "errores_llm": errores_llm}


def procesar_todos_los_paises(
    noticias_por_pais: Dict[str, Dict],
    groq_api_key: str,
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
            procesar_pais(pais, noticias_por_pais[pais], groq_api_key, n_noticias)
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


def _agregar_portada(doc: Document, fecha_str: str, titulo_texto: str, nota_texto: str):
    titulo = doc.add_paragraph()
    titulo.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = titulo.add_run(titulo_texto)
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
    run3 = nota.add_run(nota_texto)
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
        if datos_pais.get("error_busqueda"):
            texto_vacio = (
                f"No se pudo consultar este país por un error técnico: "
                f"{datos_pais['error_busqueda']}"
            )
        else:
            texto_vacio = (
                "No se encontraron noticias relevantes sobre programas de "
                "protección social en la última semana para este país."
            )
        run_vacio = p.add_run(texto_vacio)
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

    Si reportes_por_pais contiene un solo país, el título y la nota de
    portada se adaptan automáticamente para reflejar que es un reporte
    individual, en vez del título genérico de los 10 países.
    """
    doc = Document()
    _configurar_estilos(doc)

    MESES_ES = {
        1: "enero", 2: "febrero", 3: "marzo", 4: "abril", 5: "mayo", 6: "junio",
        7: "julio", 8: "agosto", 9: "septiembre", 10: "octubre", 11: "noviembre", 12: "diciembre",
    }
    ahora = datetime.now(ZONA_HORARIA)
    fecha_str = f"{ahora.day} de {MESES_ES[ahora.month]} de {ahora.year}, {ahora.strftime('%H:%M')}"

    if len(reportes_por_pais) == 0:
        titulo_texto = "Resumen de Noticias\nProgramas de Protección Social"
        nota_texto = "No hay países disponibles para este reporte."
    elif len(reportes_por_pais) == 1:
        pais_unico = reportes_por_pais[0]["pais"]
        titulo_texto = f"Resumen de Noticias\nProgramas de Protección Social en {pais_unico}"
        nota_texto = f"Reporte individual del país: {pais_unico}."
    else:
        titulo_texto = "Resumen de Noticias\nProgramas de Protección Social en Centroamérica y el Caribe"
        nombres = [r["pais"] for r in reportes_por_pais]
        nota_texto = f"Países incluidos: {', '.join(nombres[:-1])} y {nombres[-1]}." if len(nombres) > 1 else f"País incluido: {nombres[0]}."

    _agregar_portada(doc, fecha_str, titulo_texto, nota_texto)

    for datos_pais in reportes_por_pais:
        _agregar_pais(doc, datos_pais)

    buffer = io.BytesIO()
    doc.save(buffer)
    buffer.seek(0)
    return buffer
