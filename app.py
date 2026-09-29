"""
APP PRINCIPAL — Streamlit (app.py)
====================================
Orquesta los dos agentes, con caché diario y regeneración por país:

  Agente 1 (scraper.py)     -> recolecta noticias crudas vía SerpAPI
  Agente 2 (summarizer.py)  -> resume con Groq (Llama 3.3 70B) y genera el .docx
  cache.py                  -> evita repetir búsquedas el mismo día

Para correr localmente:
    streamlit run app.py

Para desplegar en Streamlit Cloud:
    1. Sube este repo a GitHub (incluye app.py, scraper.py, summarizer.py,
       cache.py, requirements.txt). NO subas tus API keys.
    2. En share.streamlit.io conecta el repo.
    3. En "Settings -> Secrets" pega:
           SERPAPI_KEY = "tu_key_de_serpapi"
           GROQ_API_KEY = "tu_key_de_groq"
"""

import re
import streamlit as st
import unicodedata
from datetime import datetime
from cache import _ahora

from scraper import buscar_noticias_pais, PAISES, TERMINOS_TEMATICOS
from summarizer import (procesar_pais, generar_documento_word, modelo_en_uso,
                        configurar_base_url, es_error_de_bloqueo_de_red)
import cache


def _normalizar_nombre_archivo(texto: str) -> str:
    """Quita tildes/diacríticos y reemplaza espacios por guion bajo,
    para nombres de archivo compatibles con cualquier sistema."""
    sin_tildes = unicodedata.normalize("NFKD", texto)
    sin_tildes = "".join(c for c in sin_tildes if not unicodedata.combining(c))
    # Cualquier cosa que no sea letra o número pasa a guion bajo. Antes
    # solo se sustituían los espacios, así que paréntesis y otros
    # signos del nombre acababan dentro del archivo — legales, pero
    # molestos al compartirlo.
    limpio = re.sub(r"[^a-z0-9]+", "_", sin_tildes.lower())
    return limpio.strip("_")


# ---------------------------------------------------------------------------
# CONFIGURACIÓN DE PÁGINA E INICIALIZACIÓN
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="Noticias: Protección Social en Centroamérica y el Caribe",
    page_icon="📰",
    layout="wide",
)

cache.inicializar_db()
cache.limpiar_cache_antiguo(dias_a_conservar=3)

# ---------------------------------------------------------------------------
# ESTADO DE SESIÓN (se inicializa temprano para que el sidebar pueda usarlo)
# ---------------------------------------------------------------------------

if "reportes" not in st.session_state:
    # dict {pais: reporte} — se va llenando a medida que se procesan países
    st.session_state.reportes = {}

st.title("📰 Resumen Diario de Noticias")
st.subheader("Programas de Protección Social en Centroamérica y el Caribe")

st.markdown(
    "Esta aplicación combina dos agentes automatizados:\n"
    "1. **Agente recolector** — busca noticias recientes (última semana) vía SerpAPI.\n"
    "2. **Agente sintetizador** — selecciona las noticias más relevantes por país, "
    "las resume con Groq y genera un documento Word descargable.\n\n"
    "🗄️ Los resultados de cada país se **cachean por el día** — si tú u otro "
    "usuario ya consultaron un país hoy, no se vuelve a gastar cuota de "
    "SerpAPI/Groq para ese país a menos que pidas regenerarlo explícitamente."
)

# ---------------------------------------------------------------------------
# CARGA DE API KEYS
# ---------------------------------------------------------------------------

def obtener_api_key(nombre_secret: str, label: str) -> str:
    """
    Devuelve la API key desde los Secrets de Streamlit si está
    configurada; si no, pide escribirla en el panel lateral.

    El acceso a st.secrets va dentro de un try porque, cuando NO existe
    ningún archivo de secrets (típico al clonar el repo por primera vez
    o al correrlo en local sin configurar nada), Streamlit no devuelve
    un diccionario vacío: lanza StreamlitSecretNotFoundError y tumba la
    app entera con un traceback rojo, en vez de mostrar el aviso amable
    de "ingresa tus claves". Con el try, ese caso degrada al campo de
    texto del panel lateral, que es el comportamiento esperado.
    """
    try:
        if nombre_secret in st.secrets:
            return st.secrets[nombre_secret]
    except Exception:
        pass  # sin archivo de secrets: se pide la clave por pantalla
    return st.sidebar.text_input(label, type="password", key=nombre_secret)


with st.sidebar:
    st.header("⚙️ Configuración")
    serpapi_key = obtener_api_key("SERPAPI_KEY", "SerpAPI Key")
    groq_key = obtener_api_key("GROQ_API_KEY", "Groq API Key")

    # Pasarela alternativa hacia Groq. Secret OPCIONAL: si no está, se
    # usa la API oficial y todo funciona como siempre. Existe porque el
    # Cloudflare de Groq bloquea las IP de centros de datos —Streamlit
    # Cloud entre ellos— con un 403 antes de mirar la clave. Ver
    # summarizer._BASE_URL_GROQ y el README.
    try:
        _base_url_groq = st.secrets.get("GROQ_BASE_URL", "")
    except Exception:
        _base_url_groq = ""
    configurar_base_url(_base_url_groq)
    if _base_url_groq:
        st.caption("🔀 Groq se está consultando a través de una pasarela alternativa.")

    st.divider()
    n_noticias = st.slider("Noticias por país", min_value=1, max_value=5, value=5)

    st.divider()
    if st.button("🗑️ Borrar caché de hoy", use_container_width=True):
        cantidad = cache.borrar_cache_de_hoy()
        st.session_state.reportes = {}  # también limpiar lo que se ve en pantalla
        st.success(f"Caché de hoy borrado ({cantidad} país(es)). Vuelve a buscar para regenerar todo.")
    st.caption(
        "Usa esto si acabas de actualizar el código de la app y quieres "
        "que la próxima búsqueda ignore resultados guardados con la "
        "lógica anterior (ej. cambios en cantidad de noticias o modelo)."
    )

    st.divider()
    st.caption(f"Países cubiertos ({len(PAISES)}):")
    st.caption(", ".join(PAISES))
    st.caption(f"Términos de búsqueda: *{', '.join(TERMINOS_TEMATICOS)}*")
    st.caption(f"Modelo de IA en uso: `{modelo_en_uso()}`")

claves_listas = bool(serpapi_key) and bool(groq_key)

if not claves_listas:
    st.warning(
        "⚠️ Ingresa tu **SerpAPI Key** y tu **Groq API Key** en el panel "
        "lateral izquierdo para poder generar el reporte."
    )

# ---------------------------------------------------------------------------
# LÓGICA COMPARTIDA: procesar un solo país (con o sin forzar regeneración)
# ---------------------------------------------------------------------------

def procesar_un_pais(pais: str, forzar: bool = False, progress_callback=None) -> dict:
    """
    Devuelve el reporte procesado de un país. Usa caché de hoy si existe
    y no se fuerza regeneración; si no, llama a los agentes 1 y 2 y
    actualiza el caché.

    progress_callback(etapa, hecho, total) se propaga al Agente 2 para
    poder mostrar avance mientras se generan los resúmenes.
    """
    if not forzar:
        cacheado = cache.obtener_cache_pais(pais)
        if cacheado is not None:
            return {**cacheado["reporte_procesado"], "_desde_cache": True,
                     "_actualizado_en": cacheado["actualizado_en"]}

    if progress_callback:
        progress_callback("buscando", 0, n_noticias)
    resultado_busqueda = buscar_noticias_pais(pais, serpapi_key, n_noticias_necesarias=n_noticias)

    if resultado_busqueda.get("error"):
        # Error de conexión/API de SerpAPI — se muestra explícitamente
        # en vez de tratarlo en silencio como "sin resultados".
        reporte = {
            "pais": pais,
            "noticias": [],
            "sin_resultados": True,
            "errores_llm": [],
            "error_busqueda": resultado_busqueda["error"],
        }
    else:
        reporte = procesar_pais(
            pais, resultado_busqueda, groq_key, n_noticias,
            progress_callback=progress_callback,
        )

    cache.guardar_cache_pais(pais, resultado_busqueda, reporte)

    return {**reporte, "_desde_cache": False, "_actualizado_en": _ahora().strftime("%Y-%m-%d %H:%M:%S")}


# ---------------------------------------------------------------------------
# BOTÓN PRINCIPAL: PROCESAR TODOS LOS PAÍSES (usa caché cuando aplica)
# ---------------------------------------------------------------------------

col1, col2 = st.columns([1, 3])
with col1:
    ejecutar_todos = st.button(
        "🚀 Buscar noticias de hoy (todos los países)",
        type="primary",
        disabled=not claves_listas,
        use_container_width=True,
    )

# Datos que se muestran, rotando, durante la espera. No son adorno:
# explican lo que el sistema está haciendo justo en ese momento, así
# que el rato de espera sirve para entender la herramienta. Cada uno
# corresponde a una decisión de diseño real del proyecto.
DATOS_MIENTRAS_ESPERAS = [
    "Cada país se busca en una lista curada de medios reales, investigada uno por uno. "
    "Un medio que no está en la lista de su país no puede aparecer en su sección.",

    "Haití se busca en francés. Su prensa publica en ese idioma, y buscarlo en español "
    "dejaba fuera a Le Nouvelliste, AlterPresse y los demás medios haitianos.",

    "Los resúmenes se redactan solo con el titular y el extracto reales de cada noticia. "
    "El modelo no consulta su memoria ni busca por su cuenta, así que no puede inventar.",

    "La espera entre resúmenes es deliberada. El servicio de IA permite 8.000 tokens por "
    "minuto: espaciar las llamadas 3,5 segundos evita chocar contra el límite y fallar.",

    "Lo que no pasa un filtro no se tira: queda apartado. Solo si a un país le faltan "
    "noticias se revisan esas dudosas, una por una, con más criterio.",

    "Si un país no tuvo cobertura esta semana, el reporte lo va a decir. Nunca rellena "
    "el hueco con algo que no venga al caso.",

    "Si una noticia aparece en dos búsquedas distintas con enlaces distintos, se "
    "detecta que es la misma por el parecido entre los titulares y solo se incluye una vez.",

    "Google fecha por rastreo las páginas que no llevan fecha propia, y así reporta "
    "material viejo como reciente. Por eso también se lee la fecha incrustada en el enlace.",

    "Cada noticia llega con su fuente, su fecha y su enlace. Todo lo que dice el resumen "
    "se puede comprobar en la nota original con un clic.",

    "El nombre de un país dentro del nombre de otro lugar no cuenta. 'Villa El Salvador' "
    "es un distrito de Lima, y el sistema ya lo sabe.",
]

ETIQUETA_ETAPA = {
    "buscando": "Buscando en la prensa",
    "verificando": "Revisando noticias dudosas",
    "resumiendo": "Redactando resúmenes",
}


def _mmss(segundos: float) -> str:
    segundos = max(0, int(segundos))
    return f"{segundos // 60}:{segundos % 60:02d}"


if ejecutar_todos:
    import time as _time

    total = len(PAISES)
    inicio = _time.monotonic()

    barra = st.progress(0.0, text="Iniciando…")
    linea_estado = st.empty()
    linea_dato = st.empty()
    # Área de resultados en vivo: las noticias de cada país se muestran
    # en cuanto están listas, sin esperar a que terminen los 11. Es el
    # cambio que más acorta la espera percibida — a los 30 segundos ya
    # hay algo que leer, y el resto carga mientras tanto.
    #
    # Tiene que ser un st.empty() y no un st.container(): al final hay
    # que borrar esta vista, porque justo debajo se dibujan las pestañas
    # definitivas y si no se duplicaría el reporte entero. Un contenedor
    # no se puede vaciar; un placeholder sí. El precio es volver a
    # pintar la lista completa en cada vuelta, que con 11 países no se
    # nota.
    area_en_vivo = st.empty()
    terminados = []

    # Contador global de pasos, para que la barra avance de forma
    # pareja: cada país son ~6 pasos (1 búsqueda + 5 resúmenes).
    PASOS_POR_PAIS = n_noticias + 1
    pasos_totales = total * PASOS_POR_PAIS
    estado = {"pasos": 0, "dato": 0}

    def _pintar(pais_actual: str, indice_pais: int, etapa: str, hecho: int, de: int):
        fraccion = min(0.999, estado["pasos"] / pasos_totales)
        transcurrido = _time.monotonic() - inicio

        if fraccion > 0.02:
            restante = _mmss(transcurrido / fraccion - transcurrido)
        else:
            restante = "calculando…"

        barra.progress(fraccion, text=f"{pais_actual} · país {indice_pais}/{total}")

        detalle = ETIQUETA_ETAPA.get(etapa, etapa)
        if etapa == "resumiendo" and de:
            detalle += f" ({hecho + 1} de {de})"
        linea_estado.markdown(
            f"**{detalle}** · {_mmss(transcurrido)} transcurrido · "
            f"faltan ~{restante}"
        )

        # El dato cambia cada dos pasos: lo bastante seguido para que se
        # note que la app está viva, sin que dé tiempo a leerlo a medias.
        if estado["pasos"] % 2 == 0:
            estado["dato"] = (estado["dato"] + 1) % len(DATOS_MIENTRAS_ESPERAS)
        linea_dato.info(f"💡 {DATOS_MIENTRAS_ESPERAS[estado['dato']]}")

    for i, pais in enumerate(PAISES):
        def _cb(etapa, hecho, de, _p=pais, _i=i + 1):
            _pintar(_p, _i, etapa, hecho, de)
            estado["pasos"] += 1

        _pintar(pais, i + 1, "buscando", 0, n_noticias)
        reporte = procesar_un_pais(pais, forzar=False, progress_callback=_cb)
        st.session_state.reportes[pais] = reporte

        # Los pasos que no se hayan consumido (país desde caché, o con
        # menos noticias de las esperadas) se dan por hechos, para que la
        # barra no se quede atrás respecto de los países ya terminados.
        estado["pasos"] = max(estado["pasos"], (i + 1) * PASOS_POR_PAIS)

        terminados.append((pais, reporte))
        with area_en_vivo.container():
            st.caption("Ya puedes ir leyendo — el resto sigue cargando:")
            for nombre_pais, rep in terminados:
                etiqueta = "📦 caché" if rep.get("_desde_cache") else "🆕 nuevo"
                n = len(rep.get("noticias", []))
                if rep.get("error_busqueda"):
                    resumen_pais = "⚠️ error de búsqueda"
                elif n == 0:
                    resumen_pais = "sin cobertura esta semana"
                else:
                    resumen_pais = f"{n} noticia(s)"
                # Solo el último país queda abierto: es la novedad, y
                # así la lista no crece hasta volverse inmanejable.
                es_ultimo = nombre_pais == terminados[-1][0]
                with st.expander(
                    f"✅ {nombre_pais} — {resumen_pais} · {etiqueta}",
                    expanded=es_ultimo,
                ):
                    if rep.get("error_busqueda"):
                        st.warning(rep["error_busqueda"])
                    for noticia in rep.get("noticias", []):
                        st.markdown(
                            f"**{noticia['titulo']}**  \n"
                            f"*{noticia.get('fuente','')} · {noticia.get('fecha','')}*  \n"
                            f"{noticia.get('resumen','')}  \n"
                            f"[Ver nota original]({noticia.get('link','')})"
                        )
                        st.markdown("---")

    barra.progress(1.0, text=f"✅ Listo en {_mmss(_time.monotonic() - inicio)}")
    linea_estado.empty()
    linea_dato.empty()
    # Se limpia la vista en vivo: justo debajo se renderizan las
    # pestañas definitivas, y dejar ambas duplicaría todo el reporte.
    area_en_vivo.empty()
    st.success("¡Reporte actualizado! Revisa los resultados abajo.")

# ---------------------------------------------------------------------------
# RESULTADOS POR PAÍS — con botón individual de regeneración
# ---------------------------------------------------------------------------

if st.session_state.reportes:
    st.divider()
    st.markdown("## 📄 Resultados por país")
    st.caption(
        "Cada país muestra si su resultado viene del caché de hoy o se "
        "generó recién. Usa '🔄 Regenerar' para forzar una nueva búsqueda "
        "de un país específico sin afectar a los demás."
    )

    tabs = st.tabs(PAISES)

    for tab, pais in zip(tabs, PAISES):
        with tab:
            reporte = st.session_state.reportes.get(pais)

            col_info, col_btn = st.columns([3, 1])
            with col_btn:
                regenerar = st.button(
                    "🔄 Regenerar",
                    key=f"regen_{pais}",
                    disabled=not claves_listas,
                    use_container_width=True,
                )

            if regenerar:
                with st.spinner(f"Regenerando noticias de {pais}..."):
                    st.session_state.reportes[pais] = procesar_un_pais(pais, forzar=True)
                reporte = st.session_state.reportes[pais]
                st.success(f"{pais} regenerado.")

            if reporte is None:
                with col_info:
                    st.info("Aún no se ha consultado este país en esta sesión.")
                continue

            with col_info:
                if reporte.get("_desde_cache"):
                    st.caption(f"📦 Desde caché de hoy — última actualización: {reporte['_actualizado_en']}")
                else:
                    st.caption(f"🆕 Recién generado — {reporte['_actualizado_en']}")

            if reporte.get("error_busqueda"):
                st.error(f"⚠️ Error al consultar SerpAPI para este país: {reporte['error_busqueda']}")
            elif reporte["sin_resultados"]:
                st.info("No se encontraron noticias relevantes en la última semana (ni en las últimas 2 semanas).")
            else:
                for i, noticia in enumerate(reporte["noticias"], start=1):
                    st.markdown(f"**{i}. {noticia['titulo']}**")
                    st.caption(f"Fuente: {noticia['fuente']} | Fecha: {noticia['fecha']}")
                    st.write(noticia["resumen"])
                    if noticia.get("link"):
                        st.markdown(f"[Ver noticia completa]({noticia['link']})")
                    st.markdown("---")

                if reporte.get("errores_llm"):
                    n_fallidos = len(reporte["errores_llm"])
                    n_noticias = len(reporte["noticias"])

                    # Si fallaron TODOS los resúmenes, no es un tropiezo
                    # puntual sino una falla sistémica (modelo retirado,
                    # key vencida, Groq caído). Se muestra de forma
                    # prominente: la deprecación del modelo de agosto de
                    # 2026 pasó un mes inadvertida justamente porque este
                    # aviso vivía escondido dentro de un desplegable.
                    if n_noticias > 0 and n_fallidos == n_noticias:
                        # El aviso distingue la causa. Antes decía
                        # siempre "modelo retirado / key vencida /
                        # servicio caído", y el 29-sep-2026 mandó a
                        # revisar tres cosas que estaban bien: el fallo
                        # real era que Cloudflare bloqueaba la IP de
                        # Streamlit Cloud antes de mirar la clave.
                        hay_bloqueo_de_red = any(
                            es_error_de_bloqueo_de_red(e)
                            for e in reporte.get("errores_llm", [])
                        )
                        if hay_bloqueo_de_red:
                            st.error(
                                "🔴 **Groq está rechazando las peticiones por la RED, "
                                "no por la clave.** Lo que se muestra arriba es el texto "
                                "original de cada noticia, no un resumen.\n\n"
                                "El error 403 *\"Access denied — check your network "
                                "settings\"* lo devuelve el Cloudflare que Groq tiene "
                                "delante, **antes** de comprobar la API key, porque "
                                "bloquea las IP de centros de datos y Streamlit Cloud "
                                "es uno. Tu clave y tu cuota están bien, y cambiar de "
                                "modelo no ayuda.\n\n"
                                "**Qué hacer:** primero reinicia la app (puede tocarte "
                                "otra IP de salida). Si sigue igual, hay que enrutar por "
                                "una pasarela añadiendo el secret `GROQ_BASE_URL` — el "
                                "README explica cómo, y no requiere tocar el código."
                            )
                        else:
                            st.error(
                                "🔴 **Ningún resumen pudo generarse con IA.** Lo que se "
                                "muestra arriba es el texto original de cada noticia, no un "
                                "resumen. Suele deberse a que el modelo de Groq fue retirado, "
                                "a que la API key venció, o a que el servicio está caído. "
                                "Revisa el detalle técnico abajo."
                            )

                    with st.expander(
                        f"⚠️ {n_fallidos} resumen(es) usaron el "
                        "texto original por un error de Groq — ver detalle técnico"
                    ):
                        for err in reporte["errores_llm"]:
                            st.code(err, language=None)

    # -----------------------------------------------------------------
    # DESCARGA DEL DOCUMENTO WORD (combina todos los países disponibles,
    # ya sea de caché o recién generados)
    # -----------------------------------------------------------------
    st.divider()
    paises_listos = [p for p in PAISES if st.session_state.reportes.get(p) is not None]
    paises_faltantes = [p for p in PAISES if p not in paises_listos]

    if paises_faltantes:
        st.warning(
            f"⚠️ Aún faltan {len(paises_faltantes)} país(es) por consultar: "
            f"{', '.join(paises_faltantes)}. El documento se generará solo "
            "con los países ya disponibles, o usa el botón principal para "
            "completarlos todos."
        )

    # Limpiar las claves internas (_desde_cache, _actualizado_en) antes de
    # pasarle los datos al generador de Word, que no las espera.
    reportes_para_docx = []
    for pais in paises_listos:
        r = st.session_state.reportes[pais]
        reportes_para_docx.append({
            "pais": r["pais"],
            "sin_resultados": r["sin_resultados"],
            "noticias": r["noticias"],
            "error_busqueda": r.get("error_busqueda"),
        })

    fecha_hoy = _ahora().strftime("%Y-%m-%d")

    if reportes_para_docx:
        docx_buffer = generar_documento_word(reportes_para_docx)
        st.download_button(
            label=f"⬇️ Descargar documento Word ({len(paises_listos)}/{len(PAISES)} países)",
            data=docx_buffer,
            file_name=f"reporte_proteccion_social_{fecha_hoy}.docx",
            mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            type="primary",
        )
    else:
        st.info("Aún no hay ningún país listo para descargar. Usa el botón principal para empezar.")

    # -----------------------------------------------------------------
    # DESCARGA DE UN SOLO PAÍS (documento Word con solo sus 5 noticias)
    # -----------------------------------------------------------------
    if paises_listos:
        st.divider()
        st.markdown("### 📍 O descarga solo un país")

        col_select, col_download = st.columns([2, 1])
        with col_select:
            pais_elegido = st.selectbox(
                "Elige un país",
                options=paises_listos,
                key="selector_pais_individual",
                label_visibility="collapsed",
            )

        reporte_pais_elegido = st.session_state.reportes[pais_elegido]
        docx_pais_individual = generar_documento_word([{
            "pais": reporte_pais_elegido["pais"],
            "sin_resultados": reporte_pais_elegido["sin_resultados"],
            "noticias": reporte_pais_elegido["noticias"],
            "error_busqueda": reporte_pais_elegido.get("error_busqueda"),
        }])

        nombre_archivo_pais = (
            f"reporte_{_normalizar_nombre_archivo(pais_elegido)}_{fecha_hoy}.docx"
        )

        with col_download:
            st.download_button(
                label=f"⬇️ Descargar {pais_elegido}",
                data=docx_pais_individual,
                file_name=nombre_archivo_pais,
                mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                use_container_width=True,
            )
