"""
AGENTE 2 — Sintetizador y generador de reporte (summarizer.py)
================================================================
Responsabilidad única: recibir las noticias crudas del Agente 1
(separadas en "aceptadas" y "descartadas_marginales"), completar el
cupo de noticias por país (usando un agente verificador con Groq
sobre las descartadas marginales si hace falta), generar un resumen
breve de cada una usando Groq (ver MODELOS_GROQ), y producir un
documento Word (.docx) con el reporte final.
"""

import io
import re
import time
from datetime import datetime
from cache import ZONA_HORARIA
from scraper import deduplicar_noticias, ordenar_marginales, titulos_similares
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


# Dirección alternativa de la API de Groq. Normalmente vacía: se usa
# la oficial (api.groq.com).
#
# PARA QUÉ SIRVE (caso real del 29-sep-2026): Groq tiene delante un
# Cloudflare que BLOQUEA las peticiones que salen de rangos de IP de
# centros de datos y VPN. Como Streamlit Cloud es un centro de datos,
# un buen día la app empezó a recibir:
#
#     403 - {'error': {'message': 'Access denied. Please check your
#            network settings.'}}
#
# El rechazo ocurre en el borde, ANTES de comprobar la clave, así que
# no es un problema de credenciales ni de cuota, y cambiar de modelo no
# ayuda: ninguna petición llega al modelo. Groq tampoco lo trata como
# incidencia —para ellos la política de seguridad está funcionando—,
# así que no aparece en su página de estado ni se "arregla" solo.
#
# La salida práctica es enrutar por una pasarela que Groq sí acepte,
# como Cloudflare AI Gateway. Se hace SIN TOCAR EL CÓDIGO: basta añadir
# en los secrets de Streamlit
#
#     GROQ_BASE_URL = "https://gateway.ai.cloudflare.com/v1/<cuenta>/<pasarela>/groq"
#
# El README explica el procedimiento completo.
_BASE_URL_GROQ = ""


def configurar_base_url(base_url: str) -> None:
    """Fija la dirección alternativa de la API (ver _BASE_URL_GROQ)."""
    global _BASE_URL_GROQ
    _BASE_URL_GROQ = (base_url or "").strip()


def _opciones_cliente() -> Dict:
    return {"base_url": _BASE_URL_GROQ} if _BASE_URL_GROQ else {}


# Señales de que la petición fue rechazada por la RED, no por la clave,
# la cuota ni el modelo. Sirven para que el aviso de la app diga la
# verdad en vez de mandar a revisar cosas que están bien.
_SENALES_BLOQUEO_DE_RED = (
    "access denied",
    "check your network",
    "403",
    "forbidden",
)


def es_error_de_bloqueo_de_red(detalle: str) -> bool:
    """True si el texto del error apunta a un bloqueo de red de Groq."""
    texto = (detalle or "").lower()
    if "access denied" in texto or "check your network" in texto:
        return True
    return "403" in texto and ("forbidden" in texto or "denied" in texto)


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
                cliente = Groq(api_key=groq_api_key, **_opciones_cliente())

                # Los modelos gpt-oss son de RAZONAMIENTO: antes de
                # responder generan tokens de pensamiento interno que
                # consumen el mismo presupuesto que la respuesta. Con
                # "low" se reduce ese gasto al mínimo, que es lo que
                # conviene aquí: resumir un texto dado y responder SI/NO
                # no requieren deliberación extensa, y cada token de
                # razonamiento come cuota del límite de 8,000 por minuto.
                # Solo se envía a los modelos que lo soportan.
                extra = {}
                if modelo.startswith("openai/gpt-oss"):
                    extra["reasoning_effort"] = "low"

                respuesta = cliente.chat.completions.create(
                    model=modelo,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=temperature,
                    max_completion_tokens=max_completion_tokens,
                    **extra,
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


# ---------------------------------------------------------------------------
# EDITOR: puntuación por lotes de las candidatas
# ---------------------------------------------------------------------------
# Sustituye al verificador que rescataba noticias de una en una.
#
# POR QUÉ SE CAMBIÓ (29-sep-2026). Durante semanas el sistema decidía
# qué entraba con listas de palabras clave y solo llamaba al modelo al
# final, para rescatar dudosas cuando faltaba cupo. Estaba al revés:
#   - Las reglas de texto se usaban para lo que peor se les da —juzgar
#     si una noticia TRATA del tema— y acumulaban excepciones sin fin
#     (loterías, fiestas patrias, desalojos, aniversarios...). Esa lista
#     nunca iba a estar completa.
#   - El modelo, que es justo lo que sabe distinguir que "Centro de
#     Seguridad Social" puede ser el nombre de un salón de fiestas,
#     quedaba de último recurso y con presión por llenar un hueco. En
#     esa situación dijo que sí tres veces a cosas que no debía.
#
# Ahora los filtros de texto deciden el PAÍS —objetivo, barato y
# fiable— y el modelo puntúa el TEMA y el valor noticioso de TODAS las
# candidatas, no solo de las dudosas.
#
# EL LOTE ES LO QUE LO HACE VIABLE: puntuar una por una serían ~120
# llamadas por reporte y siete minutos. Metiendo todas las candidatas
# de un país en un solo mensaje son 10 llamadas: menos de dos minutos,
# por debajo del verificador anterior en sus peores casos. Y el modelo
# las ve JUNTAS Y EN COMPETENCIA ("de estas ocho, ¿cuáles son las
# mejores?") en vez de una a una con un hueco que llenar, que era la
# situación que lo volvía complaciente.

# Nota mínima para que una noticia se publique.
NOTA_MINIMA_PARA_PUBLICAR = 2

# Tope de candidatas que se mandan a puntuar por país, para acotar el
# tamaño del mensaje.
MAX_CANDIDATAS_A_PUNTUAR = 14

_PATRON_PUNTUACION = re.compile(r"^\s*(\d+)\s*\|\s*([0-3])\s*\|\s*(.*)$")


def puntuar_candidatas(
    candidatas: List[Dict], pais: str, groq_api_key: str
) -> Dict[int, Dict]:
    """
    Puntúa en UNA sola llamada todas las candidatas de un país.

    Devuelve {indice: {"nota": int, "razon": str}} con los índices de la
    lista recibida. Si la llamada falla, devuelve {} — el que llama
    decide qué hacer con eso (ver procesar_pais: se publica lo que
    aprobaron los filtros, para no quedarse sin reporte).
    """
    if not candidatas:
        return {}

    lineas = []
    for i, n in enumerate(candidatas[:MAX_CANDIDATAS_A_PUNTUAR], start=1):
        titulo = (n.get("titulo") or "")[:180]
        fuente = (n.get("fuente") or "")[:60]
        extracto = (n.get("snippet") or "")[:280]
        lineas.append(f"{i}. TÍTULO: {titulo}\n   FUENTE: {fuente}\n   EXTRACTO: {extracto}")

    prompt = (
        f"Eres el editor de un boletín de monitoreo sobre programas de "
        f"protección social en {pais}, dirigido a analistas de política "
        f"pública.\n\n"
        f"Puntúa CADA noticia de 0 a 3 según sirva para ese boletín:\n\n"
        f"3 = Central. Trata de una política, programa o institución "
        f"PÚBLICA de protección social de {pais}: pensiones, seguridad "
        f"social, asistencia social, transferencias monetarias, "
        f"desarrollo social, y también política laboral y salarial "
        f"(jornada, salario mínimo, derechos laborales, formalización). "
        f"Es un hecho noticioso real.\n"
        f"2 = Relevante. Trata del tema y del país, aunque de forma más "
        f"lateral o indirecta.\n"
        f"1 = Tangencial. Solo menciona el tema o la institución de "
        f"pasada; el asunto central es otro.\n"
        f"0 = No corresponde. Es de otro país; o es un acto festivo, "
        f"ceremonial o deportivo donde la institución solo pone la sede; "
        f"o es delincuencia, justicia penal o seguridad pública "
        f"(\"seguridad pública\" NO es \"seguridad social\"); o es "
        f"lotería o sorteo; o es caridad privada; o es publicidad; o no "
        f"es una noticia sino una página de índice o de archivo.\n\n"
        f"POLÍTICA LABORAL Y SALARIAL — SÍ ENTRA. Cuenta como parte del "
        f"tema, con el mismo rango de notas que el resto: jornada de "
        f"trabajo, salario mínimo y ajustes salariales, negociación "
        f"colectiva, derechos laborales, formalización del empleo, "
        f"condiciones de trabajo y las decisiones de los ministerios de "
        f"trabajo. No hace falta que la noticia mencione las "
        f"cotizaciones ni las pensiones para valer: una reforma de la "
        f"jornada laboral o un aumento del salario mínimo en {pais} son "
        f"noticia de este boletín por sí mismos.\n\n"
        f"EDUCACIÓN Y SALUD — el límite. La educación y la sanidad son "
        f"sectores sociales, pero NO son protección social por sí "
        f"mismas: el presupuesto educativo, la calidad de la enseñanza, "
        f"la rentrée escolar o las reivindicaciones sindicales sobre la "
        f"escuela pública van con 1. Sí entran, en cambio, los "
        f"programas de protección social que se entregan A TRAVÉS de la "
        f"escuela o del sistema de salud: comedores y cantinas "
        f"escolares, becas, transferencias condicionadas a la "
        f"asistencia escolar, cobertura sanitaria del seguro social.\n\n"
        f"Ojo con dos trampas:\n"
        f"- Que el nombre del país aparezca dentro del nombre de otro "
        f"lugar no lo hace de {pais} (\"Villa El Salvador\" es un "
        f"distrito de Lima).\n"
        f"- Que un acto ocurra en un edificio llamado \"Centro de "
        f"Seguridad Social\" no convierte el acto en noticia de "
        f"protección social.\n\n"
        f"REPETICIONES. Si varias noticias cubren EL MISMO hecho —el "
        f"mismo anuncio, el mismo foro, la misma reforma— quédate con "
        f"la más completa y puntúa las demás con 1, poniendo como "
        f"razón \"repite la noticia N\". Aunque sean artículos "
        f"distintos y de días distintos, al lector no le sirve leer "
        f"cinco versiones del mismo hecho: prefiere variedad de temas "
        f"dentro del país.\n\n"
        f"Sé exigente: es mejor un boletín corto y bueno que uno largo "
        f"con relleno. No hay ningún cupo que llenar.\n\n"
        f"Responde SOLO con una línea por noticia, sin nada más, en este "
        f"formato exacto:\n"
        f"numero|nota|razon breve (menos de 12 palabras)\n\n"
        f"NOTICIAS:\n\n" + "\n\n".join(lineas)
    )

    texto, _error = _llamar_groq_con_reintentos(
        groq_api_key, prompt, temperature=0, max_completion_tokens=1200
    )
    if texto is None:
        return {}

    notas = {}
    for linea in texto.splitlines():
        m = _PATRON_PUNTUACION.match(linea.strip())
        if not m:
            continue
        indice = int(m.group(1)) - 1
        if 0 <= indice < len(candidatas):
            notas[indice] = {
                "nota": int(m.group(2)),
                "razon": m.group(3).strip()[:120],
            }
    return notas


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
        groq_api_key, prompt, temperature=0.3, max_completion_tokens=800
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
    """Deduplica y recorta a n. Se conserva porque el caché antiguo y
    algún script auxiliar la usan."""
    return deduplicar_noticias(noticias)[:n]


def procesar_pais(
    pais: str,
    resultado_busqueda: Dict,
    groq_api_key: str,
    n_noticias: int = 5,
    progress_callback=None,
) -> Dict:
    """
    Para un país: puntúa las candidatas, se queda con las que superan
    el umbral y genera un resumen de cada una.

    EL CUPO ES UN TECHO, NO UNA META (cambio del 29-sep-2026). Antes
    n_noticias era un objetivo que el sistema se esforzaba en alcanzar,
    y ese esfuerzo era la causa de fondo de casi todo lo que se coló en
    los reportes: los desalojos en Honduras, el artículo sobre IA en
    Costa Rica y los cinco comunicados del IGSS en Guatemala entraron
    todos para llenar un hueco. Ahora, si un país solo tiene dos
    noticias que valgan, se publican dos.

    Eso no es una carencia del reporte: es información. Que un país
    tenga dos y otro cinco dice algo real sobre la cobertura mediática
    de la protección social en cada uno.

    Parameters
    ----------
    resultado_busqueda : el dict devuelto por scraper.buscar_noticias_pais,
                con keys "aceptadas", "descartadas_marginales", "error".
    progress_callback : función opcional progress_callback(etapa, hecho,
                total) que se llama antes de cada paso lento, para que
                la interfaz pueda mostrar avance real.

    Returns
    -------
    {"pais": str, "noticias": [...], "sin_resultados": bool,
     "errores_llm": [...], "descartadas": [...]}
    Cada noticia lleva además "nota" y "razon" del editor, para que la
    decisión sea auditable. "descartadas" son las que no llegaron al
    umbral, con su nota y su razón.
    """
    # Todas las candidatas van al editor: las que pasaron los filtros y
    # las que quedaron dudosas. Los filtros de texto ya decidieron el
    # país (objetivo); el tema lo decide ahora el editor.
    aceptadas = deduplicar_noticias(resultado_busqueda.get("aceptadas", []))
    marginales = ordenar_marginales(resultado_busqueda.get("descartadas_marginales", []))

    vistos = {n.get("link") for n in aceptadas if n.get("link")}
    candidatas = list(aceptadas)
    for n in marginales:
        link = n.get("link")
        if link and link in vistos:
            continue
        if any(titulos_similares(n.get("titulo", ""), o.get("titulo", "")) for o in candidatas):
            continue
        vistos.add(link)
        candidatas.append(n)

    if not candidatas:
        return {"pais": pais, "noticias": [], "sin_resultados": True,
                "errores_llm": [], "descartadas": []}

    if progress_callback:
        progress_callback("puntuando", 0, len(candidatas))
    # La llamada del editor es la más grande del reporte (~2.000 fichas
    # frente a las ~440 de un resumen), así que se espacia igual que las
    # demás para no rebasar el límite de fichas por minuto de Groq.
    time.sleep(ESPERA_ENTRE_LLAMADAS_SEGUNDOS)
    notas = puntuar_candidatas(candidatas, pais, groq_api_key)

    errores_llm = []
    if not notas:
        # El editor no respondió (servicio caído, bloqueo de red...).
        # Se publica lo que aprobaron los filtros en vez de entregar un
        # reporte vacío, y se deja constancia de que nadie lo revisó.
        errores_llm.append(
            "El editor de relevancia no respondió: se publican las noticias "
            "que aprobaron los filtros automáticos, sin revisión del modelo."
        )
        seleccion = [dict(n, nota=None, razon="sin revisar") for n in aceptadas[:n_noticias]]
        descartadas = []
    else:
        puntuadas = []
        for i, n in enumerate(candidatas):
            info = notas.get(i)
            if info is None:
                # Candidata que el editor no puntuó: se trata como
                # dudosa, no se cuela por omisión.
                continue
            puntuadas.append(dict(n, nota=info["nota"], razon=info["razon"]))

        # Orden estable: primero la nota, y a igual nota se respeta el
        # orden en que llegaron (las de medios curados van antes).
        puntuadas.sort(key=lambda n: -n["nota"])
        seleccion = [n for n in puntuadas if n["nota"] >= NOTA_MINIMA_PARA_PUBLICAR][:n_noticias]
        descartadas = [
            {"titulo": n["titulo"], "fuente": n.get("fuente", ""),
             "link": n.get("link", ""), "nota": n["nota"], "razon": n["razon"]}
            for n in puntuadas if n not in seleccion
        ]

    if not seleccion:
        return {"pais": pais, "noticias": [], "sin_resultados": True,
                "errores_llm": errores_llm, "descartadas": descartadas}

    procesadas = []
    for i, noticia in enumerate(seleccion):
        if progress_callback:
            progress_callback("resumiendo", i, len(seleccion))
        # Pausa entre llamadas para no rebasar el límite de tokens por
        # minuto de Groq. Se aplica también antes de la primera, porque
        # la puntuación acaba de hacer una llamada justo antes.
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
            "nota": noticia.get("nota"),
            "razon": noticia.get("razon", ""),
        })

    return {"pais": pais, "noticias": procesadas, "sin_resultados": False,
            "errores_llm": errores_llm, "descartadas": descartadas}


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
        # Tres situaciones distintas, que antes se confundían en un
        # solo mensaje. Desde que el cupo es un techo y no una meta, una
        # sección vacía puede significar que no hubo cobertura O que la
        # hubo pero ninguna noticia superó el umbral de relevancia, y no
        # es lo mismo para quien lee el reporte.
        n_descartadas = len(datos_pais.get("descartadas", []))
        if datos_pais.get("error_busqueda"):
            texto_vacio = (
                f"No se pudo consultar este país por un error técnico: "
                f"{datos_pais['error_busqueda']}"
            )
        elif n_descartadas:
            texto_vacio = (
                f"Se revisaron {n_descartadas} noticia(s) de este país, pero "
                f"ninguna trataba de programas de protección social con "
                f"suficiente centralidad como para incluirla."
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
