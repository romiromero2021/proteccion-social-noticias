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
from scraper import (deduplicar_noticias, es_de_medio_curado, ordenar_marginales,
                     titulos_similares, DIAS_MAXIMOS_ANTIGUEDAD)
from verificacion import verificar_noticias
import memoria
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

# ---------------------------------------------------------------------------
# SELLO DE VERSIÓN DEL CÓDIGO
# ---------------------------------------------------------------------------
# POR QUÉ EXISTE (10-nov-2026). Tres veces en dos días hubo que deducir,
# a partir del contenido de un reporte, si la versión desplegada en
# Streamlit era la nueva o la vieja: si las fechas haitianas fallaban
# porque el lector de fechas está mal o porque todavía no se había
# subido. Deducirlo lleva veinte minutos, da respuestas contradictorias
# —en el reporte del 10-nov por la tarde, una señal decía "código
# nuevo" y otra "código viejo"— y el diagnóstico de una avería real
# queda esperando mientras tanto.
#
# La huella se CALCULA del contenido de los archivos, no se escribe a
# mano: una versión que hay que acordarse de subir de número es una
# versión que miente el día que uno se olvida. Cada módulo lleva su
# propia marca, así que una subida incompleta no solo se detecta: dice
# cuál archivo quedó atrás.
#
# Se normalizan los finales de línea antes de medir, porque GitHub y
# Streamlit pueden reescribirlos y eso no es un cambio de código.
MODULOS_CON_SELLO = ("app.py", "scraper.py", "summarizer.py",
                     "verificacion.py", "memoria.py")


def _huella_de_archivo(nombre: str) -> str:
    """Marca corta de un módulo. Nunca lanza: sin sello se sigue."""
    import hashlib
    import os
    ruta = os.path.join(os.path.dirname(os.path.abspath(__file__)), nombre)
    try:
        with open(ruta, "r", encoding="utf-8") as f:
            texto = f.read()
    except OSError:
        return "ausente"
    normalizado = "\n".join(linea.rstrip() for linea in texto.splitlines())
    return hashlib.sha256(normalizado.encode("utf-8")).hexdigest()[:4]


def huellas_de_modulos() -> Dict[str, str]:
    return {nombre: _huella_de_archivo(nombre) for nombre in MODULOS_CON_SELLO}


def sello_de_version() -> str:
    """
    Una línea legible: la huella del conjunto y la de cada módulo.

    Para saber si una subida llegó, se compara esta línea con la del
    reporte anterior. Si el conjunto cambió, cambió algo; si además se
    ve cuál módulo cambió, se sabe qué llegó y qué no.
    """
    import hashlib
    porpartes = huellas_de_modulos()
    conjunto = hashlib.sha256(
        "".join(f"{k}:{v}" for k, v in sorted(porpartes.items())).encode()
    ).hexdigest()[:6]
    detalle = " ".join(f"{k.replace('.py', '')} {v}"
                       for k, v in porpartes.items())
    return f"código {conjunto} · {detalle}"

# Tope de candidatas que se mandan a puntuar por país, para acotar el
# tamaño del mensaje.
MAX_CANDIDATAS_A_PUNTUAR = 14

_PATRON_PUNTUACION = re.compile(r"^\s*(\d+)\s*\|\s*([0-3])\s*\|\s*(.*)$")


def puntuar_candidatas(
    candidatas: List[Dict], pais: str, groq_api_key: str
) -> Dict[int, Dict]:
    """
    Puntúa TODAS las candidatas de un país, en tandas de
    MAX_CANDIDATAS_A_PUNTUAR.

    Devuelve {indice: {"nota": int, "razon": str}} con los índices de la
    lista recibida. Si una llamada falla, las candidatas de esa tanda
    se quedan sin nota y procesar_pais las registra como tales.

    POR QUÉ EN TANDAS (9-nov-2026). Antes se mandaba `candidatas[:14]`
    y punto: de la decimoquinta en adelante, nadie las puntuaba nunca.
    No desaparecían —procesar_pais las anota como "el editor no la
    puntuó"— pero en la práctica quedaban fuera del boletín sin que
    ningún juicio las hubiera mirado, y el corte caía justo donde
    menos conviene: `ordenar_marginales` pone al final de la cola los
    motivos menos rescatables, así que el tope recortaba por el lado
    correcto… mientras hubiera menos de 14. Pasado ese número, el
    recorte empieza a comerse candidatas legítimas en silencio.
    Una segunda llamada cuesta unos segundos; perder una noticia
    buena, una semana.
    """
    if not candidatas:
        return {}

    notas: Dict[int, Dict] = {}
    for inicio in range(0, len(candidatas), MAX_CANDIDATAS_A_PUNTUAR):
        lote = candidatas[inicio:inicio + MAX_CANDIDATAS_A_PUNTUAR]
        if inicio:
            # Mismo ritmo que el resto de llamadas: el límite de Groq
            # es de fichas por minuto y esta es la llamada más grande.
            time.sleep(ESPERA_ENTRE_LLAMADAS_SEGUNDOS)
        for i, info in _puntuar_lote(lote, pais, groq_api_key).items():
            notas[inicio + i] = info
    return notas


# Cualquier espacio en blanco que parta la línea. Se incluyen los
# separadores Unicode de línea y párrafo, que un titular copiado de un
# PDF puede traer y que pasan desapercibidos.
_ROMPE_LINEA = re.compile(r"[\r\n  \v\f]+")


def sanear_campo(texto: str, limite: int) -> str:
    """
    Deja un campo de contenido NO CONFIABLE en una sola línea, sin el
    separador del formato de salida, y recortado.

    POR QUÉ (aplicado el 9-nov-2026). El prompt del editor se arma
    pegando título, fuente y extracto, que vienen de la web abierta, y
    le pide al modelo que conteste `numero|nota|razon`. Si un titular
    contiene un salto de línea seguido de algo con esa forma, en el
    prompt queda una línea indistinguible de la respuesta que el
    propio modelo debe producir, y el intérprete la acepta como suya.
    No hace falta engañar al modelo: basta con imitar su letra.

    No intenta detectar intenciones —no se puede mantener una lista de
    todas las maneras de escribir «ignora las instrucciones
    anteriores»—: le quita la FORMA que el texto necesita para hacerse
    pasar por otra cosa. Un titular que diga «ignora las
    instrucciones» sigue diciéndolo, y está bien: es un titular.

    Cubría los cuatro casos marcados `@pytest.mark.hueco_conocido` en
    evals/test_adversarial.py, que estuvieron en rojo a propósito desde
    el 21-oct para que la brecha viviera en el registro y no en la
    cabeza de nadie.
    """
    limpio = _ROMPE_LINEA.sub(" ", texto or "")
    limpio = limpio.replace("|", "/")          # el separador del formato
    limpio = re.sub(r"\s{2,}", " ", limpio).strip()
    return limpio[:limite]


def _puntuar_lote(
    candidatas: List[Dict], pais: str, groq_api_key: str
) -> Dict[int, Dict]:
    """
    Una sola llamada al editor con las candidatas que recibe. Los
    índices que devuelve son relativos a ESTA lista.
    """
    if not candidatas:
        return {}

    lineas = []
    for i, n in enumerate(candidatas, start=1):
        # Los tres campos son contenido que escribió un desconocido y
        # que acaba DENTRO de las instrucciones al modelo. Ver
        # sanear_campo.
        titulo = sanear_campo(n.get("titulo"), 180)
        fuente = sanear_campo(n.get("fuente"), 60)
        extracto = sanear_campo(n.get("snippet"), 280)
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
        f"es una noticia sino una página de índice o de archivo.\n"
        f"El 0 es para lo que está FUERA del asunto, no para lo que está "
        f"en el borde. Una prestación o un programa público de {pais} con "
        f"presupuesto asignado nunca es 0: si dudas de si el tema entra, "
        f"pon 1 o 2, nunca 0.\n\n"
        f"POLÍTICA LABORAL Y SALARIAL — SÍ ENTRA. Cuenta como parte del "
        f"tema, con el mismo rango de notas que el resto: jornada de "
        f"trabajo, salario mínimo y ajustes salariales, negociación "
        f"colectiva, derechos laborales, formalización del empleo, "
        f"condiciones de trabajo y las decisiones de los ministerios de "
        f"trabajo. No hace falta que la noticia mencione las "
        f"cotizaciones ni las pensiones para valer: una reforma de la "
        f"jornada laboral o un aumento del salario mínimo en {pais} son "
        f"noticia de este boletín por sí mismos.\n\n"
        f"POBLACIÓN SIN SEGURIDAD SOCIAL — el corazón del boletín. Si "
        f"una medida pública se dirige expresamente a quienes NO tienen "
        f"seguridad social —\"población abierta\", \"sin seguridad "
        f"social\", \"no asegurados\", \"régimen no contributivo\", "
        f"trabajo informal, trabajadoras del hogar, campesinos— es "
        f"protección social no contributiva y va con 3, SEA DEL SECTOR "
        f"QUE SEA: medicamentos, tratamientos o consultas financiados "
        f"con fondos públicos para quien no está asegurado cuentan, "
        f"porque lo que se cubre es precisamente el hueco de cobertura. "
        f"Esta regla manda sobre la de educación y salud: lo que decide "
        f"no es el sector del que habla la noticia, sino a quién va "
        f"dirigido el beneficio. Que el anuncio venga acompañado de una "
        f"campaña de comunicación no lo convierte en campaña: si hay un "
        f"monto, un padrón o una prestación concreta, es un programa.\n\n"
        f"EDUCACIÓN Y SALUD — el límite. La educación y la sanidad son "
        f"sectores sociales, pero NO son protección social por sí "
        f"mismas: el presupuesto educativo, la calidad de la enseñanza, "
        f"la rentrée escolar o las reivindicaciones sindicales sobre la "
        f"escuela pública van con 1. Sí entran, en cambio, los "
        f"programas de protección social que se entregan A TRAVÉS de la "
        f"escuela o del sistema de salud: comedores y cantinas "
        f"escolares, becas, transferencias condicionadas a la "
        f"asistencia escolar, cobertura sanitaria del seguro social. "
        f"Este límite solo se aplica a las medidas dirigidas a la "
        f"población en general; si la noticia acota el beneficio a "
        f"quienes no tienen seguridad social, manda la regla "
        f"anterior.\n"
        f"LA PREGUNTA QUE DECIDE no es «¿habla de salud?» sino "
        f"«¿habla de COBERTURA?». Si la noticia trata de a quién le "
        f"toca, qué tiene derecho a recibir, cómo se le garantiza, o "
        f"de si la institución de seguridad social se lo está "
        f"entregando, entonces es protección social y va con 2 o 3 "
        f"aunque la palabra «salud» aparezca en cada frase. Si trata "
        f"de epidemiología o de salud pública general —cuántos casos "
        f"de un virus hay este mes, qué recomienda el ministerio para "
        f"no contagiarse— va con 1.\n"
        f"SÍ entran: una ley que garantiza la protección social y el "
        f"acceso a servicios de salud a un grupo determinado "
        f"(pacientes con enfermedades raras, personas con "
        f"discapacidad, personas mayores); cómo están funcionando los "
        f"centros de la institución de seguridad social después de "
        f"una emergencia; un brote de enfermedad entre los "
        f"trabajadores de un centro de trabajo, que es salud "
        f"ocupacional. NO entra: «circulan varios virus respiratorios "
        f"este mes».\n"
        f"Y si el propio titular dice «protección social», no "
        f"concluyas que le falta enfoque social: eso es exactamente "
        f"lo que el boletín busca.\n\n"
        f"COBERTURA, SUFICIENCIA Y EROSIÓN — también es el tema, y NO "
        f"hace falta que haya un anuncio. Un boletín de monitoreo "
        f"necesita las dos mitades: lo que el Estado ANUNCIA y lo que "
        f"de hecho PASA. Van con 3 los datos sobre cuánto alcanza una "
        f"pensión o un salario, qué parte de la población está "
        f"cubierta, cuántos cotizan, cómo se erosiona el poder "
        f"adquisitivo de las prestaciones, y los informes de "
        f"organismos sobre todo eso. «El salario medio no llega a diez "
        f"dólares» o «la inflación se come la pensión» son noticia de "
        f"este boletín por sí mismas: miden si el sistema cumple su "
        f"función, que es exactamente lo que el analista monitorea. NO "
        f"las bajes de nota por no traer una medida, un programa ni un "
        f"anuncio: «sin política concreta» y «no hay programa» no son "
        f"motivos válidos de descarte para un dato de este tipo.\n"
        f"El límite: la macroeconomía general (PIB, tipo de cambio, "
        f"deuda, bolsa) NO entra por sí sola. Entra cuando la noticia "
        f"la pone en relación con salarios, pensiones, empleo o "
        f"prestaciones.\n"
        f"Y cuenta también lo que el salario ALCANZA A PAGAR: si una "
        f"noticia dice que los salarios no dan para la vivienda, la "
        f"canasta básica, la salud o los servicios, eso es un dato de "
        f"suficiencia y va con 3. Es la misma pregunta que «cuánto "
        f"alcanza una pensión», mirada desde el gasto.\n\n"
        f"ACCESO AL EMPLEO — entra, con el mismo rango que el resto. "
        f"Quién consigue trabajo y quién no es la puerta de entrada a "
        f"la seguridad social contributiva, así que el boletín lo "
        f"sigue: desempleo y sus cifras, desempleo juvenil, el primer "
        f"empleo y las barreras para conseguirlo (que pidan "
        f"experiencia a quien no puede tenerla), desempleo de larga "
        f"duración, informalidad como exclusión de la cobertura, "
        f"migración laboral y programas de empleo temporal. Una "
        f"noticia sobre jóvenes que no logran entrar al mercado "
        f"laboral de {pais} va con 2 o 3, no con 1: describe quién "
        f"queda fuera del sistema.\n"
        f"EL LÍMITE de esta regla: lo que cuenta es quién queda FUERA "
        f"del empleo o de la cobertura, no cualquier asunto del mundo "
        f"del trabajo. NO entran, y van con 1: la dificultad de las "
        f"empresas o de un sector para encontrar personal, los tiempos "
        f"de traslado y el tráfico, el clima laboral o las "
        f"expectativas salariales de quien contrata. Describen las "
        f"condiciones del negocio o la logística de la ciudad, no el "
        f"acceso de las personas a la protección social.\n\n"
        f"SALUD Y CONDICIONES DE TRABAJO — sí entran, con 2 o 3. Los "
        f"riesgos laborales son una de las ramas clásicas de la "
        f"seguridad social, así que el boletín sigue lo que le pasa al "
        f"cuerpo de quien trabaja: enfermedad profesional, accidentes, "
        f"calor extremo, jornada, descanso, acoso laboral, "
        f"inspecciones de condiciones. Si una noticia dice que algo "
        f"está dañando la salud de las personas trabajadoras de "
        f"{pais}, va con 3 aunque hable además de productividad y "
        f"aunque no haya ninguna medida de por medio: describe un "
        f"riesgo al que el sistema debería responder.\n"
        f"La productividad SOLA, como indicador de la economía o de "
        f"una empresa, no entra; la productividad junto a la salud o "
        f"las condiciones de quien trabaja, sí.\n"
        f"Y esta regla NO abre la puerta al traslado al trabajo. El "
        f"tiempo que se pierde en el tráfico ocupa horas de descanso y "
        f"de familia, pero es un problema de transporte y de ciudad, "
        f"no un riesgo del puesto de trabajo ni una rama de la "
        f"seguridad social: «los trabajadores pierden tres horas "
        f"diarias en traslados» va con 1, aquí y en la regla de acceso "
        f"al empleo. Lo que esta regla cubre es lo que el TRABAJO le "
        f"hace al cuerpo —la jornada que se alarga, el turno sin "
        f"descanso, el calor en el sitio de trabajo, la enfermedad que "
        f"se contrae ahí—, no todo lo que desgasta a quien trabaja.\n\n"
        f"CONFLICTO Y EXIGENCIA — es el tema, y NO hace falta que "
        f"nadie anuncie nada. Una huelga, un paro, una marcha, una "
        f"demanda sindical, una denuncia de desfinanciamiento, la "
        f"deuda del Estado con la institución de seguridad social, un "
        f"litigio o una disputa en el legislativo sobre pensiones, "
        f"salud o salarios van con 3 cuando lo que está en disputa es "
        f"la protección social de {pais}.\n"
        f"«Protesta, no anuncia medida», «demanda de servicio, sin "
        f"política concreta», «no es un comunicado oficial» y «no hay "
        f"medida concreta» NO son motivos válidos de descarte aquí, "
        f"igual que no lo son para los datos de cobertura. Lo que "
        f"decide es SOBRE QUÉ se reclama, no si alguien respondió ya. "
        f"Un boletín que solo recoge anuncios describe un sistema "
        f"donde nada se discute, y esa es una imagen falsa de "
        f"justamente lo que la analista monitorea: la presión sobre el "
        f"sistema es la mitad de la historia.\n\n"
        f"COMUNICADOS OFICIALES DEL ESTADO — al menos 2. Un anuncio del "
        f"Congreso, de un ministerio o de la institución de seguridad "
        f"social de {pais} sobre un asunto del boletín vale 2 aunque "
        f"solo exprese una posición o una prioridad y no una decisión ya "
        f"tomada: al analista le sirve saber que el legislativo se está "
        f"moviendo en ese tema. Llega a 3 solo si trae algo concreto —una "
        f"iniciativa identificable, una votación, una cifra, una fecha—. "
        f"Lo que no puede es quedarse en 0 o 1 por ser escueto: lo "
        f"escueto se castiga con la nota 2, no con la exclusión.\n"
        f"Este suelo de 2 vale SOLO para órganos del Estado y SOLO "
        f"cuando el comunicado trata de una medida, una prestación, una "
        f"cifra o una posición de política. El comunicado de un "
        f"sindicato, una cámara empresarial, una ONG o un partido NO "
        f"tiene suelo: se puntúa por lo que diga, como cualquier otra "
        f"noticia. Y la palabra «Comunicado» en el titular no activa "
        f"nada por sí sola.\n"
        f"EL SUELO NO CUBRE LA AUTOPROMOCIÓN. Que la institución "
        f"prometa tratar mejor a la gente —«atención digna para "
        f"nuestros pensionados», «un servicio más ágil, cercano y con "
        f"calidez», «seguimos trabajando por usted»— no es una medida, "
        f"ni una prestación, ni una cifra, ni una posición de política: "
        f"es imagen, y va con 1 aunque la publique el propio "
        f"organismo público en su sitio. Para merecer el 2 el "
        f"comunicado tiene que decir QUÉ cambia: un trámite que se "
        f"elimina, un plazo que se acorta, una ventanilla que abre, un "
        f"monto, una fecha.\n\n"
        f"ACTOS INTERNOS DE UNA ORGANIZACIÓN — van con 1. Una asamblea, "
        f"un congreso ordinario, una toma de posesión, una "
        f"juramentación, un nombramiento, un aniversario, un homenaje o "
        f"una reunión de seguimiento son la vida interna de la "
        f"organización, no una medida de protección social, aunque la "
        f"organización sea un sindicato de trabajadores o la propia "
        f"institución de seguridad social, y aunque en el acto se "
        f"reiteren posiciones. Suben a 2 o 3 solo si la noticia dice que "
        f"de ahí salió algo concreto: un acuerdo con contenido, una "
        f"cifra, una medida que empieza a aplicarse.\n\n"
        f"ALCANCE Y RUTINA — a igualdad de tema, lo nacional vale más "
        f"que lo local, y lo que cambia vale más que lo que sigue "
        f"igual. Una medida, una cifra o un conflicto de alcance "
        f"nacional va con 3. La actividad rutinaria de una oficina en "
        f"un municipio —una feria de empleo, una jornada de "
        f"afiliación, una unidad móvil que visita una localidad, una "
        f"entrega en un barrio— va con 1, por correcta que sea, salvo "
        f"que traiga cifras nacionales o inaugure un programa nuevo. No "
        f"es que la actividad local no importe: es que en un boletín de "
        f"cinco noticias por país ocupa el lugar de algo que afecta a "
        f"todo el país.\n"
        f"Señal clara de rutina: el titular dice que la institución "
        f"CONTINÚA, SIGUE o MANTIENE algo que ya venía haciendo. "
        f"«Puerto Barrios continúa conectando talento con "
        f"oportunidades laborales» y «Ministerio de Trabajo continúa "
        f"con inspecciones nocturnas» son exactamente eso: partes de "
        f"actividad, sin hecho nuevo. Van con 1. En cambio «el "
        f"Ministerio ABRE una línea de inspección» o «el programa "
        f"SUMA 40 000 beneficiarios» sí traen un hecho.\n\n"
        f"Ojo con tres trampas:\n"
        f"- Que el nombre del país aparezca dentro del nombre de otro "
        f"lugar no lo hace de {pais} (\"Villa El Salvador\" es un "
        f"distrito de Lima).\n"
        f"- Que un acto ocurra en un edificio llamado \"Centro de "
        f"Seguridad Social\" no convierte el acto en noticia de "
        f"protección social.\n"
        f"- Si la noticia no dice en ninguna parte que ocurre en "
        f"{pais}, no la des por buena porque el tema encaje: un medio "
        f"internacional cubriendo la reforma de OTRO país produce "
        f"titulares perfectos para este boletín y no corresponden. Sin "
        f"una señal de que es de {pais}, ponle 0.\n"
        f"- Si NO reconoces una institución, no supongas que es "
        f"privada ni una ONG. Muchos organismos públicos de {pais} se "
        f"llaman de formas que pueden no sonarte —fondos, institutos, "
        f"oficinas, caisses— y bajar la nota por esa suposición "
        f"descarta programas estatales reales. Ante la duda sobre "
        f"quién aplica una medida, puntúa por lo que la medida ES, no "
        f"por tu conjetura sobre quién está detrás.\n\n"
        f"REPETICIONES. Si varias noticias cubren EL MISMO hecho —el "
        f"mismo anuncio, el mismo foro, la misma reforma— quédate con "
        f"la más completa y puntúa las demás con 1, poniendo como "
        f"razón \"repite la noticia N\". Aunque sean artículos "
        f"distintos y de días distintos, al lector no le sirve leer "
        f"cinco versiones del mismo hecho: prefiere variedad de temas "
        f"dentro del país.\n"
        f"LA MISMA FUENTE DE DATOS TAMBIÉN ES REPETICIÓN, y es la que "
        f"se escapa. Dos notas que comentan la MISMA encuesta, el "
        f"mismo estudio, el mismo informe o la misma cifra oficial son "
        f"una sola noticia, aunque los titulares no se parezcan en "
        f"nada y aunque cada medio destaque un ángulo distinto. "
        f"Compara las CIFRAS y la fuente del dato, no las palabras del "
        f"titular: «el desempleo aumenta por cuatro factores: 154 736 "
        f"personas» y «el país registra 6,5 % de desempleo, 155 000 "
        f"personas, y una brecha entre hombres y mujeres» son el mismo "
        f"trimestre del mismo instituto de estadística contado dos "
        f"veces. Igual «trabajadores pierden 3 horas y 10 minutos en "
        f"traslados, según estudio regional» y «el país enfrenta el "
        f"mayor tiempo de traslado de la región, según estudio»: un "
        f"solo estudio. Quédate con la más completa y pon 1 a la otra, "
        f"con la razón \"repite la noticia N\".\n\n"
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
        "- **NO DESARROLLES SIGLAS.** Si el material dice «FAES», «INSS», "
        "«CSS» o «MIDES» y no escribe en ninguna parte qué significan, "
        "escribe la sigla tal cual y nada más. Completar el nombre de "
        "memoria parece un servicio al lector y es una invención: el 10 "
        "de noviembre dos noticias haitianas seguidas llamaron al mismo "
        "organismo «Fondo de Asistencia Económica y Social» y «Fondo de "
        "Asistencia de Emergencia y Seguridad», y una de las dos estaba "
        "mal. Una sigla sin desarrollar no le quita nada al resumen; un "
        "nombre inventado le quita la credibilidad al boletín entero.\n"
        "- Tampoco traduzcas al español el nombre propio de una "
        "institución si el material no lo trae traducido: déjalo como "
        "viene.\n"
        "- **El largo lo manda el material, no el máximo.** Si el extracto "
        "trae un solo hecho, una frase es la respuesta correcta. No rellenes "
        "hasta las tres frases.\n"
        "- No repitas la misma idea con otras palabras ni añadas frases de "
        "relleno del tipo \"esto refleja la prioridad del tema en la agenda "
        "pública\" o \"el enfoque se centra en...\": no dicen nada y hacen "
        "parecer informado un resumen que no lo está.\n"
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

    # Rastro de las ramas automáticas que se tomaron en la búsqueda
    # (ver scraper._buscar_prensa_pais). Se arrastra hasta el reporte
    # para que quede constancia de POR QUÉ un país trae lo que trae.
    ramas = list(resultado_busqueda.get("ramas", []))

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
                "errores_llm": [], "descartadas": [], "ramas": ramas}

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
        # La cuarta rama, la única que cambia SI alguien juzgó.
        ramas.append("editor_sin_respuesta_publicado_sin_revisar")
        aprobadas = [dict(n, nota=None, razon="sin revisar") for n in aceptadas]
        puntuadas, sin_puntuar, repetidas = [], [], []
    else:
        puntuadas = []
        sin_puntuar = []
        for i, n in enumerate(candidatas):
            info = notas.get(i)
            if info is None:
                # Candidata que el editor no puntuó: no se cuela por
                # omisión, pero TAMPOCO desaparece en silencio.
                #
                # 21-oct-2026: antes se hacía `continue` y la candidata
                # se esfumaba sin dejar rastro, ni publicada ni
                # descartada. Eso hace imposible diagnosticar: al mirar
                # el panel no se puede distinguir "esta noticia nunca
                # llegó" de "llegó y el editor se saltó su línea", que
                # son dos averías distintas y en capas distintas.
                sin_puntuar.append(
                    {"titulo": n["titulo"], "fuente": n.get("fuente", ""),
                     "link": n.get("link", ""), "nota": None,
                     "razon": "el editor no la puntuó (no se publica por omisión)"}
                )
                continue
            puntuadas.append(dict(n, nota=info["nota"], razon=info["razon"]))

        # Orden: primero la nota, y a igual nota primero el medio
        # curado del país.
        #
        # LA PROCEDENCIA ENTRA EN EL ORDEN (9-nov-2026). Antes el orden
        # era solo por nota, con el desempate implícito del orden de
        # llegada. El reporte del 9-nov mostró el costo cuatro veces en
        # un mismo documento: entró un comunicado sindical de
        # larepublica.net y quedó fuera una marcha por la CCSS; entró
        # una actividad local de guatemala.gob.gt y quedó fuera una
        # nota de agn.gt; entró una nota de vanguardia.cu de julio y
        # quedó fuera una de diariodecuba.com de anteayer. En los tres
        # casos la que entró venía de un medio que NO está en la lista
        # curada y la que quedó fuera venía de uno que sí.
        #
        # La lista curada es el juicio editorial más caro que tiene el
        # sistema —cada dominio se revisó a mano— y hasta hoy solo se
        # usaba para buscar y para descartar. Aquí es donde se decide
        # qué lee la analista, y aquí no contaba nada.
        #
        # Es un desempate, no un veto: una noticia excelente de un
        # medio no curado (3) sigue ganándole a una correcta de un
        # medio curado (2). Lo que ya no pasa es que las dos empaten y
        # gane la de procedencia desconocida por haber llegado antes.
        puntuadas.sort(key=lambda n: (-n["nota"],
                                      0 if es_de_medio_curado(n, pais) else 1))

        # MEMORIA ENTRE CORRIDAS (9-nov-2026). Se aplica ANTES de
        # recortar al cupo, no después: así una noticia repetida no
        # deja un hueco, la sustituye la siguiente mejor. Y antes de
        # verificar, para no gastar peticiones en algo que no se va a
        # publicar. Ver memoria.py.
        aprobadas = [n for n in puntuadas
                     if n["nota"] >= NOTA_MINIMA_PARA_PUBLICAR]
        aprobadas, repetidas = memoria.filtrar_ya_publicadas(aprobadas)

    # VERIFICACIÓN CONTRA LA PÁGINA DEL MEDIO (1-nov-2026).
    #
    # Hasta aquí todo lo que el sistema sabe de la fecha y del enlace se
    # lo dijo el buscador, y los reportes del 31-oct y 1-nov demostraron
    # que puede mentir en las dos cosas: enlaces envueltos en el
    # redirector de Google, y una nota del 17 de julio presentada como
    # "hace 13 horas" en tres reportes seguidos, cada vez más joven.
    #
    # Se verifica SOLO lo que se va a publicar (cinco como mucho por
    # país), en paralelo y con tiempo máximo corto. Ante cualquier fallo
    # la noticia se queda como estaba: verificar no puede convertirse en
    # una forma nueva de perder noticias.
    #
    # LA VERIFICACIÓN YA NO DEJA HUECOS (9-nov-2026). Antes se cortaba
    # al cupo y DESPUÉS se verificaba, así que una noticia tumbada por
    # fecha falsa se llevaba su plaza con ella. Pasó ese mismo día en
    # República Dominicana: cinco seleccionadas, la de Revista Mercado
    # resultó ser del 11 de septiembre —el buscador la daba como «hace
    # 11 horas»— y el país salió con cuatro noticias en vez de cinco,
    # teniendo tres más aprobadas esperando.
    #
    # Es el mismo error de orden que ya se había corregido para la
    # memoria unas horas antes: filtrar después de recortar deja
    # agujeros. Ahora se verifica por tandas y se rellena con las
    # siguientes aprobadas hasta llegar al cupo o agotarlas.
    limite_dias = 14 if "ventana_ampliada_a_2_semanas" in ramas \
        else DIAS_MAXIMOS_ANTIGUEDAD

    pendientes = list(aprobadas)
    seleccion: List[Dict] = []
    fuera_de_fecha: List[Dict] = []
    while pendientes and len(seleccion) < n_noticias:
        tanda = pendientes[:n_noticias - len(seleccion)]
        pendientes = pendientes[len(tanda):]
        verificadas, rechazadas = verificar_noticias(
            tanda, limite_dias, pais=pais)
        seleccion.extend(verificadas)
        fuera_de_fecha.extend(rechazadas)

    # El panel de descartadas se arma AL FINAL, cuando la selección ya
    # es definitiva: así cada noticia aparece una sola vez y con el
    # motivo que de verdad la dejó fuera.
    #
    # Se compara por ENLACE y no por igualdad de diccionarios:
    # verificar_noticias devuelve COPIAS con campos añadidos, así que
    # `n not in seleccion` daba siempre verdadero y la noticia
    # publicada aparecía además en el panel de descartes.
    def _clave(noticia: Dict) -> str:
        return noticia.get("link") or noticia.get("titulo", "")

    ya_resueltas = (
        {_clave(n) for n in seleccion}
        | {_clave(n) for n in fuera_de_fecha}
        | {_clave(n) for n in repetidas}
    )
    descartadas = [
        {"titulo": n["titulo"], "fuente": n.get("fuente", ""),
         "link": n.get("link", ""), "nota": n.get("nota"),
         "razon": n.get("razon", "")}
        for n in puntuadas
        if _clave(n) not in ya_resueltas
    ] + sin_puntuar + repetidas + fuera_de_fecha

    if not seleccion:
        return {"pais": pais, "noticias": [], "sin_resultados": True,
                "errores_llm": errores_llm, "descartadas": descartadas,
                "ramas": ramas}

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
            # False cuando no se pudo contrastar la fecha con la
            # página del medio (sitio caído, lento o sin fecha
            # legible). La interfaz lo señala.
            "fecha_verificada": noticia.get("_fecha_verificada", False),
            "motivo_sin_verificar": noticia.get("_motivo_sin_verificar", ""),
            "link": noticia.get("link", ""),
            "resumen": resultado["resumen"],
            "nota": noticia.get("nota"),
            "razon": noticia.get("razon", ""),
        })

    # Se anota en la memoria lo que de verdad se publicó, con su estado
    # de verificación. Es lo que permite que la próxima corrida sepa
    # que esta noticia ya salió, y cuántas veces salió sin poder
    # comprobarse (ver memoria.py). Va al final, después de resumir:
    # solo cuenta lo que llegó al reporte.
    memoria.registrar_publicadas(procesadas, pais)

    return {"pais": pais, "noticias": procesadas, "sin_resultados": False,
            "errores_llm": errores_llm, "descartadas": descartadas,
            "ramas": ramas}


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
COLOR_AVISO = RGBColor(0xA8, 0x42, 0x2B)    # terracota para advertencias


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


# Qué decirle a quien LEE el documento sobre cada desvío. No son las
# etiquetas de la interfaz (_ETIQUETA_RAMA en app.py): aquí el lector
# no sabe qué es una "rama", así que cada texto explica la consecuencia
# para la noticia que tiene delante.
#
# No se listan las ramas que no cambian lo que el lector ve.
_ETIQUETA_RAMA_DOC = {
    "ventana_ampliada_a_2_semanas": (
        "la búsqueda de la última semana no devolvió nada, así que se "
        "amplió a dos semanas; puede haber noticias de hasta 14 días."),
    "busqueda_abierta_sin_lista_de_medios": (
        "la lista de medios habituales no alcanzó el cupo, así que se "
        "buscó también fuera de ella."),
    "reintento_con_consulta_corta": (
        "el buscador agotó el tiempo de espera y se reintentó con una "
        "consulta más corta, que cubre menos medios de este país."),
    "editor_sin_respuesta_publicado_sin_revisar": (
        "el revisor automático no respondió: estas noticias pasaron los "
        "filtros pero NADIE juzgó si son pertinentes."),
    "el_buscador_dijo_sin_resultados": (
        "el buscador respondió «sin resultados» en alguna consulta, lo "
        "que puede significar que no había nada o que falló."),
}


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

    # EL DESVÍO SE DICE DENTRO DEL DOCUMENTO (10-nov-2026).
    #
    # Las ramas se registraban desde el 1 de noviembre y se mostraban
    # en la aplicación, pero NO en el Word — que es el archivo que
    # circula. El 10 de noviembre el reporte de Honduras llevó una
    # noticia del 29 de octubre, doce días atrás, con un límite
    # declarado de diez. No era un error: la búsqueda no había
    # encontrado nada y el sistema amplió la ventana a catorce días
    # él solo. Pero quien leyó el documento no tenía forma de saberlo,
    # y la pregunta razonable fue "¿esto no está fuera de rango?".
    #
    # Es el mismo principio que el aviso de fecha sin verificar: una
    # salvedad que vive solo en la pantalla no existe para quien
    # recibe el archivo.
    avisos = [_ETIQUETA_RAMA_DOC[r] for r in datos_pais.get("ramas", [])
              if r in _ETIQUETA_RAMA_DOC]
    if avisos:
        p_rama = doc.add_paragraph()
        rama_run = p_rama.add_run("Nota sobre esta búsqueda: " + " ".join(avisos))
        rama_run.font.size = Pt(9)
        rama_run.font.italic = True
        rama_run.font.color.rgb = COLOR_AVISO

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

        # El aviso de fecha sin contrastar va DENTRO del documento, no
        # solo en la pantalla. El Word es el archivo que circula por
        # correo, y quien lo recibe no ve la aplicación: si el aviso
        # vive solo en la interfaz, para el lector del boletín no
        # existe. Vale para este aviso y para cualquier otro.
        if not noticia.get("fecha_verificada", False):
            motivo = noticia.get("motivo_sin_verificar", "")
            aviso_run = meta.add_run(
                "  ·  fecha sin verificar contra el medio"
                + (f" ({motivo})" if motivo else "")
            )
            aviso_run.font.size = Pt(9)
            aviso_run.font.italic = True
            aviso_run.font.color.rgb = COLOR_AVISO

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
        nombres = [r["pais"] for r in reportes_por_pais]
        # México no es Centroamérica ni Caribe: si está en la selección, se
        # nombra aparte. Si no está, mencionarlo sería inexacto.
        region = ("México, Centroamérica y el Caribe" if "México" in nombres
                  else "Centroamérica y el Caribe")
        titulo_texto = f"Resumen de Noticias\nProgramas de Protección Social en {region}"
        nota_texto = f"Países incluidos: {', '.join(nombres[:-1])} y {nombres[-1]}." if len(nombres) > 1 else f"País incluido: {nombres[0]}."

    _agregar_portada(doc, fecha_str, titulo_texto, nota_texto)

    for datos_pais in reportes_por_pais:
        _agregar_pais(doc, datos_pais)

    # Sello de versión, al final y en letra chica: no estorba a quien
    # lee el boletín y contesta en un segundo la pregunta "¿esta
    # consulta usó el código que subí?". Ver sello_de_version().
    pie = doc.add_paragraph()
    pie.alignment = WD_ALIGN_PARAGRAPH.CENTER
    marca = pie.add_run(sello_de_version())
    marca.font.size = Pt(7)
    marca.font.color.rgb = COLOR_GRIS

    buffer = io.BytesIO()
    doc.save(buffer)
    buffer.seek(0)
    return buffer
