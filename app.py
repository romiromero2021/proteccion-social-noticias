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
from datos_paises import ficha, nombre_pais
from idiomas import (IDIOMAS, IDIOMA_POR_DEFECTO, t, datos_de_espera,
                     etiqueta_etapa)

from scraper import buscar_noticias_pais, PAISES, TERMINOS_TEMATICOS
from summarizer import (procesar_pais, generar_documento_word, modelo_en_uso,
                        configurar_base_url, es_error_de_bloqueo_de_red,
                        sello_de_version)
import cache
import memoria


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
    # El título de la pestaña se fija antes de poder leer el idioma
    # elegido (set_page_config tiene que ser la primera llamada de
    # Streamlit), así que va bilingüe de una vez.
    page_title="Protección Social / Social Protection — México, Centroamérica y el Caribe",
    page_icon="📰",
    layout="wide",
)

cache.inicializar_db()
cache.limpiar_cache_antiguo(dias_a_conservar=3)

# La memoria entre corridas vive en su propio archivo y se conserva
# mucho más tiempo que el caché: su valor está en ser vieja (ver
# memoria.py). Por eso se limpia con su propio plazo y no con el de
# arriba.
memoria.inicializar_db()
memoria.limpiar_memoria_antigua()

# ---------------------------------------------------------------------------
# ESTADO DE SESIÓN (se inicializa temprano para que el sidebar pueda usarlo)
# ---------------------------------------------------------------------------

if "reportes" not in st.session_state:
    # dict {pais: reporte} — se va llenando a medida que se procesan países
    st.session_state.reportes = {}

if "idioma" not in st.session_state:
    st.session_state.idioma = IDIOMA_POR_DEFECTO

# El selector va arriba del todo y fuera del panel lateral: en un taller
# tiene que verse sin abrir nada.
_col_titulo, _col_idioma = st.columns([4, 1])
with _col_idioma:
    idioma = st.radio(
        t("idioma_selector", st.session_state.idioma),
        options=list(IDIOMAS),
        format_func=lambda c: IDIOMAS[c],
        horizontal=True,
        key="idioma",
    )

with _col_titulo:
    st.title(t("titulo", idioma))
    st.subheader(t("subtitulo", idioma))

st.markdown(t("introduccion", idioma))
if t("nota_idioma_contenido", idioma):
    st.caption(t("nota_idioma_contenido", idioma))

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
    st.header(t("configuracion", idioma))
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
        st.caption(t("pasarela_groq", idioma))

    st.divider()
    n_noticias = st.slider(t("noticias_por_pais", idioma), min_value=1, max_value=5, value=5)

    st.divider()
    if st.button(t("borrar_cache", idioma), use_container_width=True):
        cantidad = cache.borrar_cache_de_hoy()
        st.session_state.reportes = {}  # también limpiar lo que se ve en pantalla
        st.success(t("cache_borrado", idioma, cantidad=cantidad))
    st.caption(t("ayuda_cache", idioma))

    # VETO MANUAL Y REINCIDENTES (9-nov-2026).
    #
    # Hasta ahora, cuando alguien abría una noticia y comprobaba que su
    # fecha era falsa, no había dónde dejar constancia: el sistema la
    # volvía a publicar la semana siguiente. Esto es ese sitio.
    #
    # Es la única parte de la aplicación donde un juicio humano cambia
    # el comportamiento del sistema, así que pide un motivo y lo
    # guarda con la fecha. Ver memoria.py.
    st.divider()
    with st.expander(t("revision_manual", idioma)):
        sospechosas = memoria.reincidentes()
        if sospechosas:
            st.caption(t("reincidentes_hay", idioma, n=len(sospechosas)))
            for fila in sospechosas[:10]:
                st.caption(
                    f"· {fila['titulo'][:70]} — {fila['veces']}× "
                    f"(desde {fila['primera_vez']})"
                )
        else:
            st.caption(t("reincidentes_ninguna", idioma))

        enlace_a_vetar = st.text_input(t("vetar_enlace", idioma), key="veto_url")
        motivo_veto = st.text_input(t("vetar_motivo", idioma), key="veto_motivo")
        if st.button(t("vetar_boton", idioma), use_container_width=True):
            if enlace_a_vetar.strip() and motivo_veto.strip():
                memoria.vetar(enlace_a_vetar, motivo_veto.strip())
                st.success(t("vetar_hecho", idioma))
            else:
                st.warning(t("vetar_faltan_datos", idioma))

    st.divider()
    st.caption(t("paises_cubiertos", idioma, n=len(PAISES)))
    st.caption(", ".join(nombre_pais(p, idioma) for p in PAISES))
    st.caption(t("terminos_busqueda", idioma, terminos=", ".join(TERMINOS_TEMATICOS)))
    st.caption(t("modelo_en_uso", idioma, modelo=modelo_en_uso()))

    # SELLO DE VERSIÓN (10-nov-2026). Se muestra aquí además de en el
    # Word para poder comprobar un despliegue sin gastar una consulta:
    # tras subir archivos a GitHub basta recargar la página y comparar
    # la huella con la que acompaña a los archivos. Ver
    # summarizer.sello_de_version().
    st.caption(t("version_codigo", idioma, sello=sello_de_version()))

claves_listas = bool(serpapi_key) and bool(groq_key)

if not claves_listas:
    st.warning(t("faltan_claves", idioma))

# ---------------------------------------------------------------------------
# LÓGICA COMPARTIDA: procesar un solo país (con o sin forzar regeneración)
# ---------------------------------------------------------------------------

# Nombre legible de cada rama automática, para el rastro que se
# muestra en la pestaña del país.
_ETIQUETA_RAMA = {
    "busqueda_abierta_sin_lista_de_medios":
        "la lista de medios no bastó: se buscó también en abierto",
    "ventana_ampliada_a_2_semanas":
        "una consulta volvió vacía: se amplió la ventana a dos semanas",
    "reintento_con_consulta_corta":
        "el buscador se colgó: se reintentó con una consulta más corta",
    "editor_sin_respuesta_publicado_sin_revisar":
        "⚠ el editor no respondió: se publicó SIN revisión del modelo",
    "el_buscador_dijo_sin_resultados":
        "⚠ el buscador contestó «sin resultados» a alguna consulta: "
        "puede ser que no hubiera noticias, o que el proveedor fallara",
}


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
        t("boton_buscar", idioma),
        type="primary",
        disabled=not claves_listas,
        use_container_width=True,
    )

# Los textos que rotan durante la espera y los nombres de las etapas
# viven ahora en idiomas.py, con sus dos versiones.
DATOS_MIENTRAS_ESPERAS = datos_de_espera(idioma)


def _mmss(segundos: float) -> str:
    segundos = max(0, int(segundos))
    return f"{segundos // 60}:{segundos % 60:02d}"


if ejecutar_todos:
    import time as _time

    total = len(PAISES)
    inicio = _time.monotonic()

    barra = st.progress(0.0, text=t("iniciando", idioma))
    linea_estado = st.empty()
    # Ficha del país que se está procesando en ese momento. La espera
    # ronda los veinte minutos, así que en vez de una barra muda se
    # muestra algo que se pueda leer — y que además sitúa al lector en
    # el país cuyas noticias están llegando.
    area_ficha = st.empty()
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
    estado = {"pasos": 0, "dato": 0, "pais_en_ficha": None}

    def _pintar_ficha(pais_actual: str):
        """Dibuja la ficha del país en curso.

        Dos cuidados, los dos por el mismo motivo. Streamlit no vuelve a
        dibujar el hueco desde cero: compara el árbol nuevo con el
        anterior elemento por elemento, y si el nuevo tiene MENOS
        elementos que el viejo, los que sobran se quedan en pantalla.
        Por eso:

        1. La ficha emite siempre el MISMO número de elementos para los
           diez países. Los sitios históricos van en un solo markdown,
           no uno por sitio: México y Guatemala tienen tres y los demás
           dos, y esa diferencia dejaba colgada la curiosidad del país
           anterior (el último elemento) al pasar de tres sitios a dos.
        2. Se vacía el hueco antes de volver a llenarlo.

        Y se redibuja solo al cambiar de país, que es lo único que
        cambia el contenido: así no parpadea en cada paso.
        """
        if estado["pais_en_ficha"] == pais_actual:
            return
        estado["pais_en_ficha"] = pais_actual
        area_ficha.empty()
        datos = ficha(pais_actual, idioma)
        if not datos:
            return
        with area_ficha.container(border=True):
            st.markdown(f"### {nombre_pais(pais_actual, idioma)}")
            col_a, col_b = st.columns(2)
            with col_a:
                st.markdown(f"**{t('ficha_capital', idioma)}**  \n{datos['capital']}")
                st.markdown(f"**{t('ficha_idioma', idioma)}**  \n{datos['idioma']}")
            with col_b:
                st.markdown(f"**{t('ficha_fronteras', idioma)}**  \n{datos['fronteras']}")
                st.markdown(f"**{t('ficha_moneda', idioma)}**  \n{datos['moneda']}")
            st.markdown(
                f"**{t('ficha_sitios', idioma)}**\n\n"
                + "\n".join(f"- {sitio}" for sitio in datos["sitios"])
            )
            st.markdown(f"**{t('ficha_institucion', idioma)}**  \n{datos['institucion']}")
            st.info(datos["curiosidad"])

    def _pintar(pais_actual: str, indice_pais: int, etapa: str, hecho: int, de: int):
        fraccion = min(0.999, estado["pasos"] / pasos_totales)
        transcurrido = _time.monotonic() - inicio

        if fraccion > 0.02:
            restante = _mmss(transcurrido / fraccion - transcurrido)
        else:
            restante = t("calculando", idioma)

        barra.progress(fraccion, text=t("progreso_pais", idioma,
                                        pais=nombre_pais(pais_actual, idioma),
                                        i=indice_pais, total=total))

        detalle = etiqueta_etapa(etapa, idioma)
        if etapa == "resumiendo" and de:
            detalle += " " + t("resumiendo_de", idioma, hecho=hecho + 1, de=de)
        linea_estado.markdown(t("linea_estado", idioma, detalle=detalle,
                                transcurrido=_mmss(transcurrido),
                                restante=restante))

        _pintar_ficha(pais_actual)

        # El dato cambia cada dos pasos: lo bastante seguido para que se
        # note que la app está viva, sin que dé tiempo a leerlo a medias.
        if estado["pasos"] % 2 == 0:
            estado["dato"] = (estado["dato"] + 1) % len(DATOS_MIENTRAS_ESPERAS)
        linea_dato.caption(f"💡 {DATOS_MIENTRAS_ESPERAS[estado['dato']]}")

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
            st.caption(t("ya_puedes_leer", idioma))
            for nombre_pais_clave, rep in terminados:
                etiqueta = (t("etiqueta_cache", idioma) if rep.get("_desde_cache")
                            else t("etiqueta_nuevo", idioma))
                n = len(rep.get("noticias", []))
                if rep.get("error_busqueda"):
                    resumen_pais = t("error_de_busqueda", idioma)
                elif n == 0:
                    resumen_pais = t("sin_cobertura_semana", idioma)
                else:
                    resumen_pais = t("n_noticias", idioma, n=n)
                # Solo el último país queda abierto: es la novedad, y
                # así la lista no crece hasta volverse inmanejable.
                es_ultimo = nombre_pais_clave == terminados[-1][0]
                with st.expander(
                    f"✅ {nombre_pais(nombre_pais_clave, idioma)} — {resumen_pais} · {etiqueta}",
                    expanded=es_ultimo,
                ):
                    if rep.get("error_busqueda"):
                        st.warning(rep["error_busqueda"])
                    for noticia in rep.get("noticias", []):
                        st.markdown(
                            f"**{noticia['titulo']}**  \n"
                            f"*{noticia.get('fuente','')} · {noticia.get('fecha','')}*  \n"
                            f"{noticia.get('resumen','')}  \n"
                            f"[{t('ver_nota_original', idioma)}]({noticia.get('link','')})"
                        )
                        st.markdown("---")

    barra.progress(1.0, text=t("listo_en", idioma,
                               tiempo=_mmss(_time.monotonic() - inicio)))
    linea_estado.empty()
    area_ficha.empty()
    linea_dato.empty()
    # Se limpia la vista en vivo: justo debajo se renderizan las
    # pestañas definitivas, y dejar ambas duplicaría todo el reporte.
    area_en_vivo.empty()
    st.success(t("reporte_actualizado", idioma))

# ---------------------------------------------------------------------------
# RESULTADOS POR PAÍS — con botón individual de regeneración
# ---------------------------------------------------------------------------

if st.session_state.reportes:
    st.divider()
    st.markdown(t("resultados_por_pais", idioma))
    st.caption(t("ayuda_resultados", idioma))

    tabs = st.tabs([nombre_pais(p, idioma) for p in PAISES])

    for tab, pais in zip(tabs, PAISES):
        with tab:
            reporte = st.session_state.reportes.get(pais)

            col_info, col_btn = st.columns([3, 1])
            with col_btn:
                regenerar = st.button(
                    t("regenerar", idioma),
                    key=f"regen_{pais}",
                    disabled=not claves_listas,
                    use_container_width=True,
                )

            if regenerar:
                with st.spinner(t("regenerando", idioma, pais=nombre_pais(pais, idioma))):
                    st.session_state.reportes[pais] = procesar_un_pais(pais, forzar=True)
                reporte = st.session_state.reportes[pais]
                st.success(t("pais_regenerado", idioma, pais=nombre_pais(pais, idioma)))

            if reporte is None:
                with col_info:
                    st.info(t("sin_consultar", idioma))
                continue

            with col_info:
                if reporte.get("_desde_cache"):
                    st.caption(t("desde_cache", idioma, cuando=reporte["_actualizado_en"]))
                else:
                    st.caption(t("recien_generado", idioma, cuando=reporte["_actualizado_en"]))

            # Rastro de las ramas automáticas. Un país que trae dos
            # noticias porque esa semana hubo poco y otro que trae dos
            # porque la consulta se amplió o se recortó se veían
            # exactamente igual. Esto los distingue.
            if reporte.get("ramas"):
                st.caption("⤷ " + " · ".join(
                    _ETIQUETA_RAMA.get(r, r) for r in reporte["ramas"]))

            if reporte.get("error_busqueda"):
                st.error(t("error_serpapi", idioma, error=reporte["error_busqueda"]))
            elif reporte["sin_resultados"]:
                n_desc = len(reporte.get("descartadas", []))
                if n_desc:
                    st.info(t("revisadas_ninguna_relevante", idioma, n=n_desc))
                else:
                    st.info(t("sin_resultados", idioma))
            else:
                for i, noticia in enumerate(reporte["noticias"], start=1):
                    st.markdown(f"**{i}. {noticia['titulo']}**")
                    _pie = t("fuente_fecha", idioma, fuente=noticia["fuente"],
                             fecha=noticia["fecha"])
                    # Una fecha sin contrastar y una contrastada no son
                    # lo mismo, y el reporte no debe mostrarlas igual.
                    if not noticia.get("fecha_verificada", False):
                        _motivo = noticia.get("motivo_sin_verificar", "")
                        _pie += ("  ·  fecha sin verificar"
                                 + (f" ({_motivo})" if _motivo else ""))
                    st.caption(_pie)
                    # Marcado real de la página cuando la fecha no se
                    # pudo leer. Está plegado para no estorbar la
                    # lectura: solo se abre cuando hay que arreglar el
                    # lector de fechas. Ver verificacion.muestra_de_fechas().
                    if noticia.get("muestra_de_fecha"):
                        with st.expander(t("ver_marcado_de_fecha", idioma)):
                            st.code(noticia["muestra_de_fecha"], language=None)
                    st.write(noticia["resumen"])
                    if noticia.get("nota") is not None:
                        st.caption(t("relevancia", idioma, nota=noticia["nota"], razon=noticia.get("razon", "")))
                    if noticia.get("link"):
                        st.markdown(f"[{t('ver_noticia_completa', idioma)}]({noticia['link']})")
                    st.markdown("---")

            # Qué se descartó y por qué. Es lo que hace auditable la
            # decisión del editor: se puede comprobar si algo bueno se
            # quedó fuera, y sirve de conjunto etiquetado para evaluar
            # el sistema más adelante.
            if reporte.get("descartadas"):
                with st.expander(
                    t("descartes_titulo", idioma, n=len(reporte["descartadas"]))
                ):
                    for d in reporte["descartadas"]:
                        # nota None = el editor no la puntuó. Se muestra
                        # como tal en vez de "None/3".
                        etiqueta = (t("sin_nota", idioma) if d.get("nota") is None
                                    else f"{d['nota']}/3")
                        st.markdown(
                            f"**{etiqueta}** · {d['titulo']}  \n"
                            f"*{d.get('fuente','')}* — {d.get('razon','')}"
                        )
                        if d.get("link"):
                            st.caption(d["link"])

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
                            st.error(t("error_bloqueo_red", idioma))
                        else:
                            st.error(t("error_sin_resumenes", idioma))

                    with st.expander(t("detalle_tecnico", idioma, n=n_fallidos)):
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
        st.warning(t("faltan_paises", idioma, n=len(paises_faltantes),
                     paises=", ".join(nombre_pais(p, idioma) for p in paises_faltantes)))

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
            "descartadas": r.get("descartadas", []),
        })

    fecha_hoy = _ahora().strftime("%Y-%m-%d")

    if reportes_para_docx:
        docx_buffer = generar_documento_word(reportes_para_docx)
        st.download_button(
            label=t("descargar_word", idioma, listos=len(paises_listos), total=len(PAISES)),
            data=docx_buffer,
            file_name=f"reporte_proteccion_social_{fecha_hoy}.docx",
            mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            type="primary",
        )
        if t("nota_word_en_espanol", idioma):
            st.caption(t("nota_word_en_espanol", idioma))
    else:
        st.info(t("nada_que_descargar", idioma))

    # -----------------------------------------------------------------
    # DESCARGA DE UN SOLO PAÍS (documento Word con solo sus 5 noticias)
    # -----------------------------------------------------------------
    if paises_listos:
        st.divider()
        st.markdown(t("descarga_individual", idioma))

        col_select, col_download = st.columns([2, 1])
        with col_select:
            pais_elegido = st.selectbox(
                t("elige_pais", idioma),
                options=paises_listos,
                format_func=lambda p: nombre_pais(p, idioma),
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
                label=t("descargar_pais", idioma, pais=nombre_pais(pais_elegido, idioma)),
                data=docx_pais_individual,
                file_name=nombre_archivo_pais,
                mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                use_container_width=True,
            )
