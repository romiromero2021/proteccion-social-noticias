"""
TEXTOS DE LA INTERFAZ (idiomas.py)
==================================

Todos los rótulos de la pantalla, en español e inglés, en un solo
sitio. Añadido el 21-oct-2026 para poder presentar la herramienta en un
taller en inglés.

QUÉ SE TRADUCE Y QUÉ NO — y por qué
-----------------------------------
Se traduce lo que escribimos nosotros: títulos, botones, mensajes de
estado, rótulos del panel de descartes y las fichas de país
(`datos_paises.py`).

NO se traduce lo que escribe el modelo: los resúmenes y los motivos de
relevancia ("repite la noticia 2", "conmemoración histórica, sin
política"). Salen en español porque los prompts del editor y del
resumidor están en español, y **un prompt no es texto decorativo, es
comportamiento**: traducirlo puede mover las notas de un sistema que
costó varios días afinar. Tampoco se traducen los titulares ni el
documento Word, que son el producto real y van dirigidos a lectores
hispanohablantes.

Tampoco se traducen los NOMBRES DE PAÍS como clave. Se traducen solo
para mostrar, con `datos_paises.nombre_pais()`. La clave interna sigue
siendo el nombre en español en todas partes: caché, SITIOS_PAIS,
scraper y Word. Ver el comentario de esa función.

CÓMO AÑADIR UN TEXTO
--------------------
Se añade la clave a TEXTOS con sus dos idiomas y se usa `t("clave",
idioma)`. Si lleva huecos, se usan los de `str.format`: `t("clave",
idioma, pais="Cuba")`. `test_idiomas.py` falla si alguna clave se queda
sin traducir o si los huecos no coinciden entre los dos idiomas.
"""

from typing import Dict, List

IDIOMA_POR_DEFECTO = "es"

# Lo que se ve en el selector. La bandera no: en una herramienta
# regional, poner una bandera a un idioma es elegir un país.
IDIOMAS: Dict[str, str] = {
    "es": "Español",
    "en": "English",
}

TEXTOS: Dict[str, Dict[str, str]] = {
    # --- Cabecera -----------------------------------------------------
    "titulo_pagina": {
        "es": "Noticias: Protección Social en México, Centroamérica y el Caribe",
        "en": "News Monitor: Social Protection in Mexico, Central America and the Caribbean",
    },
    "titulo": {
        "es": "📰 Resumen Diario de Noticias",
        "en": "📰 Daily News Digest",
    },
    "subtitulo": {
        "es": "Programas de Protección Social en México, Centroamérica y el Caribe",
        "en": "Social Protection Programmes in Mexico, Central America and the Caribbean",
    },
    "introduccion": {
        "es": (
            "Esta aplicación combina dos agentes automatizados:\n"
            "1. **Agente recolector** — busca noticias recientes (última semana) vía SerpAPI.\n"
            "2. **Agente sintetizador** — selecciona las noticias más relevantes por país, "
            "las resume con Groq y genera un documento Word descargable.\n\n"
            "🗄️ Los resultados de cada país se **cachean por el día** — si tú u otro "
            "usuario ya consultaron un país hoy, no se vuelve a gastar cuota de "
            "SerpAPI/Groq para ese país a menos que pidas regenerarlo explícitamente."
        ),
        "en": (
            "This application combines two automated agents:\n"
            "1. **Collector agent** — searches for recent news (past week) via SerpAPI.\n"
            "2. **Synthesiser agent** — selects the most relevant news per country, "
            "summarises it with Groq and produces a downloadable Word document.\n\n"
            "🗄️ Results are **cached per country per day** — if you or another user "
            "have already queried a country today, no further SerpAPI/Groq quota is "
            "spent on it unless you explicitly ask to regenerate.\n\n"
            "ℹ️ Headlines, summaries and relevance reasons stay in the original "
            "working language (Spanish, and French for Haiti): they are the product "
            "itself, written for the analysts who use the bulletin."
        ),
    },
    "nota_idioma_contenido": {
        "es": "",
        "en": ("ℹ️ Interface in English. Headlines, summaries and relevance "
               "reasons remain in Spanish (French for Haiti)."),
    },

    # --- Panel lateral ------------------------------------------------
    "idioma_selector": {"es": "Idioma", "en": "Language"},
    "configuracion": {"es": "⚙️ Configuración", "en": "⚙️ Settings"},
    "pasarela_groq": {
        "es": "🔀 Groq se está consultando a través de una pasarela alternativa.",
        "en": "🔀 Groq is being reached through an alternative gateway.",
    },
    "noticias_por_pais": {
        "es": "Noticias por país",
        "en": "News items per country",
    },
    "borrar_cache": {
        "es": "🗑️ Borrar caché de hoy",
        "en": "🗑️ Clear today's cache",
    },
    "cache_borrado": {
        "es": "Caché de hoy borrado ({cantidad} país(es)). Vuelve a buscar para regenerar todo.",
        "en": "Today's cache cleared ({cantidad} country/countries). Search again to regenerate everything.",
    },
    "ayuda_cache": {
        "es": ("Usa esto si acabas de actualizar el código de la app y quieres "
               "que la próxima búsqueda ignore resultados guardados con la "
               "lógica anterior (ej. cambios en cantidad de noticias o modelo)."),
        "en": ("Use this after updating the app's code, so the next search "
               "ignores results stored under the previous logic (e.g. changes "
               "to the number of items or to the model)."),
    },
    # Revisión manual y memoria entre corridas (ver memoria.py).
    "revision_manual": {
        "es": "🔎 Revisión manual",
        "en": "🔎 Manual review",
    },
    "reincidentes_hay": {
        "es": ("{n} noticia(s) han salido varias veces sin que se pudiera "
               "verificar su fecha. Conviene abrirlas y, si están mal, vetarlas:"),
        "en": ("{n} item(s) have appeared several times without their date "
               "ever being verified. Worth opening and, if wrong, vetoing:"),
    },
    "reincidentes_ninguna": {
        "es": "Ninguna noticia reincide sin verificar por ahora.",
        "en": "No repeat items without verification so far.",
    },
    "vetar_enlace": {
        "es": "Enlace de la noticia a vetar",
        "en": "Link of the item to veto",
    },
    "vetar_motivo": {
        "es": "Motivo (queda escrito en el registro)",
        "en": "Reason (it is kept on the record)",
    },
    "vetar_boton": {
        "es": "Vetar esta noticia",
        "en": "Veto this item",
    },
    "vetar_hecho": {
        "es": "Vetada. No volverá a publicarse y el motivo quedó guardado.",
        "en": "Vetoed. It will not be published again and the reason is stored.",
    },
    "vetar_faltan_datos": {
        "es": "Hacen falta el enlace y el motivo.",
        "en": "Both the link and the reason are required.",
    },
    "paises_cubiertos": {
        "es": "Países cubiertos ({n}):",
        "en": "Countries covered ({n}):",
    },
    "terminos_busqueda": {
        "es": "Términos de búsqueda: *{terminos}*",
        "en": "Search terms: *{terminos}*",
    },
    "modelo_en_uso": {
        "es": "Modelo de IA en uso: `{modelo}`",
        "en": "AI model in use: `{modelo}`",
    },
    "faltan_claves": {
        "es": ("⚠️ Ingresa tu **SerpAPI Key** y tu **Groq API Key** en el panel "
               "lateral izquierdo para poder generar el reporte."),
        "en": ("⚠️ Enter your **SerpAPI key** and your **Groq API key** in the "
               "left-hand sidebar to generate the report."),
    },

    # --- Botón principal y progreso -----------------------------------
    "boton_buscar": {
        "es": "🚀 Buscar noticias de hoy (todos los países)",
        "en": "🚀 Search today's news (all countries)",
    },
    "iniciando": {"es": "Iniciando…", "en": "Starting…"},
    "progreso_pais": {
        "es": "{pais} · país {i}/{total}",
        "en": "{pais} · country {i}/{total}",
    },
    "linea_estado": {
        "es": "**{detalle}** · {transcurrido} transcurrido · faltan ~{restante}",
        "en": "**{detalle}** · {transcurrido} elapsed · ~{restante} remaining",
    },
    "calculando": {"es": "calculando…", "en": "estimating…"},
    "etapa_buscando": {
        "es": "Buscando en la prensa",
        "en": "Searching the press",
    },
    "etapa_puntuando": {
        "es": "Valorando la relevancia de las candidatas",
        "en": "Scoring the relevance of candidates",
    },
    "etapa_resumiendo": {
        "es": "Redactando resúmenes",
        "en": "Writing summaries",
    },
    "resumiendo_de": {"es": "({hecho} de {de})", "en": "({hecho} of {de})"},
    "listo_en": {"es": "✅ Listo en {tiempo}", "en": "✅ Done in {tiempo}"},
    "reporte_actualizado": {
        "es": "¡Reporte actualizado! Revisa los resultados abajo.",
        "en": "Report updated. See the results below.",
    },

    # --- Ficha de país -------------------------------------------------
    "ficha_capital": {"es": "Capital", "en": "Capital"},
    "ficha_idioma": {"es": "Idioma", "en": "Language"},
    "ficha_fronteras": {"es": "Colinda con", "en": "Borders"},
    "ficha_moneda": {"es": "Moneda", "en": "Currency"},
    "ficha_sitios": {
        "es": "Sitios históricos y arqueológicos",
        "en": "Historical and archaeological sites",
    },
    "ficha_institucion": {
        "es": "Protección social",
        "en": "Social protection",
    },

    # --- Resultados en vivo --------------------------------------------
    "ya_puedes_leer": {
        "es": "Ya puedes ir leyendo — el resto sigue cargando:",
        "en": "You can start reading — the rest is still loading:",
    },
    "etiqueta_cache": {"es": "📦 caché", "en": "📦 cached"},
    "etiqueta_nuevo": {"es": "🆕 nuevo", "en": "🆕 new"},
    "error_de_busqueda": {
        "es": "⚠️ error de búsqueda",
        "en": "⚠️ search error",
    },
    "sin_cobertura_semana": {
        "es": "sin cobertura esta semana",
        "en": "no coverage this week",
    },
    "n_noticias": {"es": "{n} noticia(s)", "en": "{n} item(s)"},
    "ver_nota_original": {
        "es": "Ver nota original",
        "en": "Open the original article",
    },

    # --- Resultados por país -------------------------------------------
    "resultados_por_pais": {
        "es": "## 📄 Resultados por país",
        "en": "## 📄 Results by country",
    },
    "ayuda_resultados": {
        "es": ("Cada país muestra si su resultado viene del caché de hoy o se "
               "generó recién. Usa '🔄 Regenerar' para forzar una nueva búsqueda "
               "de un país específico sin afectar a los demás."),
        "en": ("Each country shows whether its result comes from today's cache "
               "or was just generated. Use '🔄 Regenerate' to force a fresh "
               "search for one country without affecting the others."),
    },
    "regenerar": {"es": "🔄 Regenerar", "en": "🔄 Regenerate"},
    "regenerando": {
        "es": "Regenerando noticias de {pais}...",
        "en": "Regenerating news for {pais}...",
    },
    "pais_regenerado": {"es": "{pais} regenerado.", "en": "{pais} regenerated."},
    "sin_consultar": {
        "es": "Aún no se ha consultado este país en esta sesión.",
        "en": "This country has not been queried in this session yet.",
    },
    "desde_cache": {
        "es": "📦 Desde caché de hoy — última actualización: {cuando}",
        "en": "📦 From today's cache — last updated: {cuando}",
    },
    "recien_generado": {
        "es": "🆕 Recién generado — {cuando}",
        "en": "🆕 Just generated — {cuando}",
    },
    "error_serpapi": {
        "es": "⚠️ Error al consultar SerpAPI para este país: {error}",
        "en": "⚠️ Error querying SerpAPI for this country: {error}",
    },
    "revisadas_ninguna_relevante": {
        "es": ("Se revisaron {n} noticia(s) de este país, pero ninguna "
               "trataba de protección social con suficiente centralidad. "
               "Puedes ver abajo qué se descartó y por qué."),
        "en": ("{n} item(s) from this country were reviewed, but none dealt "
               "with social protection centrally enough to include. You can "
               "see below what was discarded and why."),
    },
    "sin_resultados": {
        "es": "No se encontraron noticias relevantes en la última semana (ni en las últimas 2 semanas).",
        "en": "No relevant news found in the past week (nor in the past two weeks).",
    },
    "fuente_fecha": {
        "es": "Fuente: {fuente} | Fecha: {fecha}",
        "en": "Source: {fuente} | Date: {fecha}",
    },
    "relevancia": {
        "es": "🎯 Relevancia {nota}/3 — {razon}",
        "en": "🎯 Relevance {nota}/3 — {razon}",
    },
    "ver_noticia_completa": {
        "es": "Ver noticia completa",
        "en": "Read the full article",
    },

    # --- Panel de descartes ---------------------------------------------
    "descartes_titulo": {
        "es": "🔍 {n} noticia(s) revisadas y no incluidas — ver por qué",
        "en": "🔍 {n} item(s) reviewed and not included — see why",
    },
    "sin_nota": {"es": "sin nota", "en": "not scored"},

    # --- Errores de Groq -------------------------------------------------
    "error_bloqueo_red": {
        "es": ("🔴 **Groq está rechazando las peticiones por la RED, no por la "
               "clave.** Lo que se muestra arriba es el texto original de cada "
               "noticia, no un resumen.\n\n"
               "El error 403 *\"Access denied — check your network settings\"* lo "
               "devuelve el Cloudflare que Groq tiene delante, **antes** de "
               "comprobar la API key, porque bloquea las IP de centros de datos y "
               "Streamlit Cloud es uno. Tu clave y tu cuota están bien, y cambiar "
               "de modelo no ayuda.\n\n"
               "**Qué hacer:** primero reinicia la app (puede tocarte otra IP de "
               "salida). Si sigue igual, hay que enrutar por una pasarela añadiendo "
               "el secret `GROQ_BASE_URL` — el README explica cómo, y no requiere "
               "tocar el código."),
        "en": ("🔴 **Groq is rejecting the requests because of the NETWORK, not "
               "the key.** What you see above is each article's original text, "
               "not a summary.\n\n"
               "The 403 *\"Access denied — check your network settings\"* comes "
               "from the Cloudflare layer in front of Groq, **before** the API key "
               "is checked, because it blocks data-centre IP addresses and "
               "Streamlit Cloud is one. Your key and your quota are fine, and "
               "switching models will not help.\n\n"
               "**What to do:** first restart the app (you may get a different "
               "outbound IP). If it persists, route through a gateway by adding "
               "the `GROQ_BASE_URL` secret — the README explains how, and it needs "
               "no code changes."),
    },
    "error_sin_resumenes": {
        "es": ("🔴 **Ningún resumen pudo generarse con IA.** Lo que se muestra "
               "arriba es el texto original de cada noticia, no un resumen. Suele "
               "deberse a que el modelo de Groq fue retirado, a que la API key "
               "venció, o a que el servicio está caído. Revisa el detalle técnico "
               "abajo."),
        "en": ("🔴 **No summary could be generated by the AI.** What you see above "
               "is each article's original text, not a summary. This usually means "
               "the Groq model was retired, the API key expired, or the service is "
               "down. See the technical detail below."),
    },
    "detalle_tecnico": {
        "es": "⚠️ {n} resumen(es) usaron el texto original por un error de Groq — ver detalle técnico",
        "en": "⚠️ {n} summary/summaries fell back to the original text after a Groq error — see technical detail",
    },

    # --- Descargas --------------------------------------------------------
    "faltan_paises": {
        "es": ("⚠️ Aún faltan {n} país(es) por consultar: {paises}. El documento "
               "se generará solo con los países ya disponibles, o usa el botón "
               "principal para completarlos todos."),
        "en": ("⚠️ {n} country/countries still pending: {paises}. The document "
               "will be generated with the countries available so far, or use the "
               "main button to complete them all."),
    },
    "descargar_word": {
        "es": "⬇️ Descargar documento Word ({listos}/{total} países)",
        "en": "⬇️ Download Word document ({listos}/{total} countries)",
    },
    "nada_que_descargar": {
        "es": "Aún no hay ningún país listo para descargar. Usa el botón principal para empezar.",
        "en": "No country is ready to download yet. Use the main button to start.",
    },
    "descarga_individual": {
        "es": "### 📍 O descarga solo un país",
        "en": "### 📍 Or download a single country",
    },
    "elige_pais": {"es": "Elige un país", "en": "Choose a country"},
    "descargar_pais": {
        "es": "⬇️ Descargar {pais}",
        "en": "⬇️ Download {pais}",
    },
    "nota_word_en_espanol": {
        "es": "",
        "en": "The Word document is produced in Spanish, the bulletin's working language.",
    },
}

# Los datos que rotan durante la espera. No son adorno: explican lo que
# el sistema está haciendo justo en ese momento, así que el rato de
# espera sirve para entender la herramienta. Cada uno corresponde a una
# decisión de diseño real del proyecto.
DATOS_MIENTRAS_ESPERAS: Dict[str, List[str]] = {
    "es": [
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
    ],
    "en": [
        "Each country is searched within a curated list of real news outlets, researched one "
        "by one. An outlet that is not on its country's list cannot appear in its section.",

        "Haiti is searched in French. Its press publishes in that language, and searching in "
        "Spanish left out Le Nouvelliste, AlterPresse and the other Haitian outlets.",

        "Summaries are written only from each article's real headline and snippet. The model "
        "does not draw on its memory or search on its own, so it cannot make things up.",

        "The pause between summaries is deliberate. The AI service allows 8,000 tokens per "
        "minute: spacing calls 3.5 seconds apart avoids hitting the limit and failing.",

        "Whatever fails a filter is not thrown away: it is set aside. Those doubtful items "
        "are reviewed one by one, with closer judgement, only if a country runs short.",

        "If a country had no coverage this week, the report says so. It never fills the gap "
        "with something off the subject.",

        "If one story turns up in two different searches under different links, it is "
        "detected as the same story by headline similarity and included only once.",

        "Google dates undated pages by when it crawled them, which reports old material as "
        "recent. That is why the date embedded in the link is read as well.",

        "Every item carries its source, its date and its link. Everything the summary says "
        "can be checked against the original article in one click.",

        "A country's name inside the name of another place does not count. 'Villa El "
        "Salvador' is a district of Lima, and the system already knows that.",
    ],
}


def t(clave: str, idioma: str = IDIOMA_POR_DEFECTO, **huecos) -> str:
    """
    Texto de interfaz en el idioma pedido.

    Si falta la clave o el idioma, cae al español en vez de romper la
    pantalla: un rótulo sin traducir es un defecto cosmético, una
    excepción tumba la app entera delante de una sala.
    """
    entrada = TEXTOS.get(clave)
    if entrada is None:
        return clave
    texto = entrada.get(idioma) or entrada.get(IDIOMA_POR_DEFECTO, clave)
    if huecos:
        try:
            return texto.format(**huecos)
        except (KeyError, IndexError, ValueError):
            return texto
    return texto


def datos_de_espera(idioma: str = IDIOMA_POR_DEFECTO) -> List[str]:
    return DATOS_MIENTRAS_ESPERAS.get(idioma, DATOS_MIENTRAS_ESPERAS[IDIOMA_POR_DEFECTO])


def etiqueta_etapa(etapa: str, idioma: str = IDIOMA_POR_DEFECTO) -> str:
    """Nombre legible de la etapa en curso ('buscando', 'puntuando'…)."""
    return t(f"etapa_{etapa}", idioma) if f"etapa_{etapa}" in TEXTOS else etapa
