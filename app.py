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

import streamlit as st
import unicodedata
from datetime import datetime
from cache import _ahora

from scraper import buscar_noticias_pais, PAISES, TERMINOS_TEMATICOS
from summarizer import procesar_pais, generar_documento_word
import cache


def _normalizar_nombre_archivo(texto: str) -> str:
    """Quita tildes/diacríticos y reemplaza espacios por guion bajo,
    para nombres de archivo compatibles con cualquier sistema."""
    sin_tildes = unicodedata.normalize("NFKD", texto)
    sin_tildes = "".join(c for c in sin_tildes if not unicodedata.combining(c))
    return sin_tildes.lower().replace(" ", "_")


# ---------------------------------------------------------------------------
# CONFIGURACIÓN DE PÁGINA E INICIALIZACIÓN
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="Noticias: Protección Social en México, Centroamérica y el Caribe",
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
st.subheader("Programas de Protección Social en México, Centroamérica y el Caribe")

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
    if nombre_secret in st.secrets:
        return st.secrets[nombre_secret]
    return st.sidebar.text_input(label, type="password", key=nombre_secret)


with st.sidebar:
    st.header("⚙️ Configuración")
    serpapi_key = obtener_api_key("SERPAPI_KEY", "SerpAPI Key")
    groq_key = obtener_api_key("GROQ_API_KEY", "Groq API Key")

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

claves_listas = bool(serpapi_key) and bool(groq_key)

if not claves_listas:
    st.warning(
        "⚠️ Ingresa tu **SerpAPI Key** y tu **Groq API Key** en el panel "
        "lateral izquierdo para poder generar el reporte."
    )

# ---------------------------------------------------------------------------
# LÓGICA COMPARTIDA: procesar un solo país (con o sin forzar regeneración)
# ---------------------------------------------------------------------------

def procesar_un_pais(pais: str, forzar: bool = False) -> dict:
    """
    Devuelve el reporte procesado de un país. Usa caché de hoy si existe
    y no se fuerza regeneración; si no, llama a los agentes 1 y 2 y
    actualiza el caché.
    """
    if not forzar:
        cacheado = cache.obtener_cache_pais(pais)
        if cacheado is not None:
            return {**cacheado["reporte_procesado"], "_desde_cache": True,
                     "_actualizado_en": cacheado["actualizado_en"]}

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
        reporte = procesar_pais(pais, resultado_busqueda, groq_key, n_noticias)

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

if ejecutar_todos:
    progreso = st.progress(0, text="Iniciando...")
    total = len(PAISES)

    for i, pais in enumerate(PAISES):
        progreso.progress(i / total, text=f"Procesando {pais}... ({i + 1}/{total})")
        st.session_state.reportes[pais] = procesar_un_pais(pais, forzar=False)

    progreso.progress(1.0, text="✅ Listo.")
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
                    with st.expander(
                        f"⚠️ {len(reporte['errores_llm'])} resumen(es) usaron el "
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
