# Resumen Diario: Programas de Protección Social (CA + Caribe)

App con dos agentes que recolectan y resumen noticias diarias sobre
programas de protección social en Costa Rica, Cuba, El Salvador,
Guatemala, Haití, Honduras, México, Nicaragua, Panamá y República
Dominicana, y generan un documento Word descargable.

Incluye **caché diario** (SQLite) para no repetir búsquedas si varios
usuarios abren la app el mismo día, y un botón de **regeneración por
país** para refrescar solo uno sin gastar cuota en los otros 9.

## Arquitectura

```
app.py          -> Interfaz Streamlit, orquesta los dos agentes + caché
scraper.py       -> AGENTE 1: recolecta noticias vía SerpAPI (google_news)
summarizer.py    -> AGENTE 2: resume con Groq (GPT OSS 120B) + genera el .docx
cache.py         -> Caché diario por país en SQLite (cache_noticias.db)
requirements.txt -> Dependencias
```

## Cómo funciona el caché

- Cada vez que se procesa un país (Agente 1 + Agente 2), el resultado
  se guarda en `cache_noticias.db` con clave `(país, fecha_de_hoy)`.
- Si otro usuario (o tú mismo, recargando la página) vuelve a pedir ese
  país el mismo día, la app **lee del caché** en vez de volver a llamar
  a SerpAPI/Groq — cero gasto de cuota adicional.
- El botón **"🔄 Regenerar"** dentro de cada pestaña de país **fuerza**
  una nueva búsqueda para ese país específico, sobrescribe su entrada
  en caché, y no toca el caché de los otros 9 países.
- El botón principal **"🚀 Buscar noticias de hoy"** procesa los 10
  países usando caché cuando esté disponible (es decir, en la práctica
  solo gasta cuota real la primera vez que se corre cada día).
- El caché se limpia automáticamente de entradas con más de 3 días de
  antigüedad cada vez que arranca la app, para que la base de datos no
  crezca indefinidamente. Ajustable en `cache.limpiar_cache_antiguo()`.
- El archivo `cache_noticias.db` está en `.gitignore` a propósito: no
  debe subirse a GitHub. En Streamlit Cloud persiste mientras el
  contenedor de la app esté activo; si la app se reinicia (redeploy o
  inactividad prolongada), el caché se vacía y se vuelve a poblar
  normalmente con las siguientes consultas.

## 1. Probar el Agente 1 solo (validar tu SerpAPI key)

Antes de correr toda la app, prueba rápidamente que tu SerpAPI key
funciona, sin gastar llamadas de más:

```bash
pip install requests
export SERPAPI_KEY="tu_key_real_aqui"
python3 scraper.py
```

Esto hace **una sola búsqueda** (Costa Rica) y te imprime el JSON crudo.
Si ves noticias con título/fuente/fecha, tu key está bien configurada.

## 2. Probar todo localmente con Streamlit

```bash
pip install -r requirements.txt
```

Crea el archivo de secrets (cópialo desde la plantilla):

```bash
cp .streamlit/secrets.toml.example .streamlit/secrets.toml
```

Edita `.streamlit/secrets.toml` y pon tus keys reales:

```toml
SERPAPI_KEY = "tu_key_real_de_serpapi"
GROQ_API_KEY = "tu_key_real_de_groq"
```

Corre la app:

```bash
streamlit run app.py
```

Se abrirá en `http://localhost:8501`. Si no usaste secrets.toml, la app
te dejará pegar las keys directamente en el panel lateral (modo manual).

La primera vez que ejecutes "🚀 Buscar noticias de hoy" gastará 10
búsquedas reales. Si lo corres de nuevo en la misma sesión/día, debería
usar el caché — verás la etiqueta "📦 Desde caché de hoy" en cada
pestaña de país en vez de "🆕 Recién generado".

## 3. Desplegar en Streamlit Community Cloud (gratis)

1. Sube este proyecto a un repositorio de GitHub.
   **IMPORTANTE:** el `.gitignore` ya excluye `secrets.toml` y
   `cache_noticias.db` — verifica que no se suban con datos sensibles.
2. Ve a [share.streamlit.io](https://share.streamlit.io) e inicia sesión
   con tu cuenta de GitHub.
3. Click en "New app", selecciona tu repo y la rama, y como
   "Main file path" pon `app.py`.
4. Antes de desplegar (o después, en Settings → Secrets), pega:
   ```toml
   SERPAPI_KEY = "tu_key_real_de_serpapi"
   GROQ_API_KEY = "tu_key_real_de_groq"
   # Opcional, solo si Groq devuelve 403 (ver más abajo):
   # GROQ_BASE_URL = "https://gateway.ai.cloudflare.com/v1/<cuenta>/<pasarela>/groq"
   ```
5. Deploy. Te dará una URL pública tipo `https://tu-app.streamlit.app`
   que puedes compartir o usar a diario.

## Notas sobre cuotas (para no quedarte sin crédito)

- **SerpAPI free tier:** ~100 búsquedas/mes. **Un reporte completo de los
  10 países consume entre 10 y 40 búsquedas** (típicamente ~30): cada
  país gasta 1 búsqueda si la capa `site:` ya llena el cupo, y hasta 4
  si hay que complementar con la capa de anclas y con el respaldo de 2
  semanas. Con ese consumo, el free tier alcanza para **unos 3 reportes
  completos al mes**, no para uso diario.

  El caché diario evita repetir búsquedas *dentro del mismo día*, así que
  ayuda cuando **varias personas** consultan la app la misma jornada
  (todas aprovechan la primera búsqueda), pero no reduce el consumo si
  una sola persona la corre todos los días. Para uso sostenido hace falta
  el plan de pago más económico de SerpAPI.

  **Antes de una demostración o presentación, conviene revisar el crédito
  restante en el panel de serpapi.com**: si la cuota se agotó, la app
  mostrará un error de búsqueda en todos los países.
- **Estrategia de búsqueda en TRES capas** (arquitectura más robusta,
  implementada tras varias rondas de ruido cruzado entre países):
  1. **site:** — cada país busca restringido a una lista curada de
     medios reales (`SITIOS_PAIS` en `scraper.py`, investigada
     manualmente). Esto elimina estructuralmente el ruido de otros
     países: un sitio que no está en la lista no puede aparecer, sin
     depender de detectar nombres de país, demónimos, o siglas en el
     texto — la causa de fondo de varios bugs anteriores (Uruguay
     colándose en Cuba/Guatemala, Veracruz en Honduras, etc.).
  2. **Anclas de texto (respaldo)** — si la capa 1 no trae ninguna
     noticia aceptada (la lista de sitios no cubre algún medio
     relevante todavía no identificado), se reintenta sin restricción
     de dominio, usando el nombre del país + su institución rectora.
  3. **Agente verificador con Groq** — si después de las capas 1 y 2
     no hay suficientes noticias para completar el cupo (n_noticias),
     las candidatas que los filtros de texto habían descartado por
     dudosas se revisan una por una con Groq ("¿esta noticia es
     genuinamente relevante para este país?"), para rescatar casos
     ambiguos que ningún filtro de texto puede anticipar de forma
     exhaustiva. Esta capa SOLO se activa cuando hace falta — un país
     con cobertura normal (la mayoría) nunca la usa, así que no
     incrementa el consumo de cuota de Groq en el caso común.
- **Filtro de fecha a prueba de páginas de archivo.** Google fecha por
  rastreo las páginas que no llevan fecha propia, y entonces reporta
  material viejo como si fuera de esta semana. Ocurrió el 29-sep-2026:
  en Guatemala entró `Conversatorio-UNOPS-IGSS-Guatemala-2018-2`, que no
  era una noticia sino la página de una **foto de un evento de 2018**,
  con `date: "hace 6 días"`. El dato de fecha era falso en origen, así
  que ningún filtro de fecha podía atraparlo. Ahora se usan tres
  señales, en este orden (ver `_dentro_del_rango` en `scraper.py`):
  1. **La fecha incrustada en la URL** (`/2026/09/23/…`), cuando existe.
     La pone el propio medio al publicar y manda sobre lo que diga
     Google. Se interpreta como el final de ese día, para que una nota
     publicada justo en el límite del rango no se pierda por unas horas
     que el dato nunca tuvo.
  2. **Señales de archivo antiguo**: un año pasado en el título o en la
     ruta de la URL sin ningún año reciente que lo acompañe, o un título
     con forma de nombre de archivo (sin espacios y con guiones, típico
     de fotos, galerías y PDFs sueltos). Solo se mira el título y la
     URL, nunca el extracto: en el cuerpo de una noticia actual es
     normal citar años pasados.
  3. La fecha que reporta SerpAPI, como antes.

  Estas noticias se descartan **en duro**: no pasan al verificador. La
  antigüedad es un hecho objetivo, no un caso dudoso que convenga que
  un modelo revise.
- **Topónimos homónimos: el nombre de un país dentro del nombre de otro
  lugar.** Confirmado el 29-sep-2026: en el reporte de El Salvador entró
  una nota de **Perú** (Agencia Andina) sobre *Villa El Salvador*, un
  distrito de Lima de unos 400.000 habitantes. El filtro buscaba
  "El Salvador" como palabra completa y lo encontraba —dentro del nombre
  de otro lugar—, así que la nota pasaba la prueba de país.

  Es un fallo de clase, no un caso aislado: *Nuevo México* es un estado
  de Estados Unidos, *Panama City* está en Florida, hay una comuna
  llamada *Cuba* en Pereira (Colombia) y un corregimiento llamado
  *Honduras* en el Cauca (Colombia). La corrección es estructural y
  tiene tres piezas:

  1. **Enmascarado** (`TOPONIMOS_HOMONIMOS`). Antes de buscar el nombre
     del país, los topónimos conocidos se sustituyen por un marcador
     neutro: donde el texto diga "Villa El Salvador" ya no queda ningún
     "El Salvador" que encontrar. Enmascarar es mejor que excluir la
     noticia entera, porque una nota que hable de *Villa El Salvador*
     **y** de *El Salvador* conserva la segunda mención. Además, el
     topónimo pasa a ser **evidencia positiva** del país real: quien
     menciona Villa El Salvador está hablando de Perú.
  2. **Marcadores geográficos** (en `SUBDIVISIONES_DE_RIESGO_CONFIRMADAS`)
     para los lugares que se llaman *exactamente* igual que un país
     —el municipio El Salvador de Guantánamo (Cuba), la sindicatura
     Costa Rica de Culiacán (México), el pueblo minero El Salvador de
     Atacama (Chile)—. Esos no se pueden enmascarar sin romper las
     menciones legítimas, así que se detectan por el territorio que los
     rodea. Estos solo marcan la noticia como dudosa, no la eliminan.
  3. **Un descarte duro nuevo** (`_es_de_otro_pais_con_certeza`): dominio
     nacional de otro país **y** el texto no nombra al buscado ni una
     vez. Hacía falta porque la nota peruana **ya estaba marcada como
     marginal** (su TLD es `.pe`): llegó al reporte porque El Salvador
     se quedó corto de noticias y **el verificador de Groq la rescató**,
     al leer "Villa El Salvador" en el titular. El verificador cae en la
     misma trampa que los filtros de texto, así que este caso ya no
     queda a su juicio. Al verificador se le añadió además la regla
     explícita sobre topónimos, para los casos aún no catalogados.

  El descarte duro es deliberadamente estrecho: **no** basta el TLD
  extranjero. La prensa mexicana cubre Centroamérica, y una nota de un
  medio `.mx` sobre el IGSS de Guatemala sí nombra a Guatemala, así que
  sobrevive como marginal y el verificador puede rescatarla.

  Comprobado contra el reporte real del 29-sep: de sus 44 noticias,
  sobreviven 42 y caen exactamente las dos defectuosas.
- **Fallback automático a 2 semanas:** dentro de las capas 1 y 2, si la
  búsqueda de 1 semana no trae ninguna noticia aceptada, se reintenta
  con un rango de 2 semanas antes de pasar a la siguiente capa (o
  devolver "sin resultados"). Combinando todo lo anterior, el **peor
  caso real es de hasta 4 búsquedas a SerpAPI por país** (site: en 1 y
  2 semanas, anclas en 1 y 2 semanas) — esto solo ocurre cuando
  genuinamente no hay cobertura noticiosa reciente. Un país con
  cobertura normal sigue gastando solo 1 búsqueda.
- **Groq (openai/gpt-oss-120b), free tier:** 30 solicitudes/minuto,
  1,000 solicitudes/día y **8,000 tokens/minuto**. Con **5 noticias por
  país × 10 países = 50 llamadas por ejecución**, el límite diario
  (1,000 RPD) sobra de lejos. El límite que sí manda es el de **tokens
  por minuto**: cada resumen consume ~440 tokens entre entrada y salida,
  así que el techo real son ~18 llamadas por minuto, no 30. Por eso el
  código espera **3.5 segundos entre llamadas** (constante
  `ESPERA_ENTRE_LLAMADAS_SEGUNDOS` en `summarizer.py`), lo que hace que
  un reporte completo tome unos 3 minutos de forma estable en vez de
  chocar contra el límite.

  Nota: el modelo anterior permitía 12,000 tokens/minuto; al migrar a
  `gpt-oss-120b` el margen se redujo, y el ritmo se ajustó en
  consecuencia. Si aun así aparecen errores 429 en el detalle técnico,
  el código los absorbe con reintentos y espera progresiva (2s, 4s, 8s):
  la ejecución tarda más, pero no falla.

## Por qué no hay una sección de la CEPAL (y por qué no insistir)

Se intentó y **se retiró el 29-sep-2026** tras tres aproximaciones
fallidas. Queda escrito para que nadie lo reintente sin saber esto:

1. **La palabra "CEPAL" como término de búsqueda.** No podía funcionar:
   la capa 1 restringe con `site:` a prensa nacional y cepal.org no
   cabe ahí; en la capa 2 se buscaba como frase exacta, que no aparece
   en ningún titular.
2. **Los feeds RSS de ReDeSoc.** Era la vía ideal —gratis, ya curada
   por la División de Desarrollo Social—, pero **están rotos del lado
   de la CEPAL**: `redesoc-rss.php` y `redesoc-proteccionsocial.php`
   devuelven HTTP 500.
3. **Búsqueda con `site:cepal.org`.** Agota el tiempo de espera de
   SerpAPI, y no por longitud —esa consulta era la más corta de todas,
   173 caracteres frente a los 430 de Haití— sino porque se le pedía a
   Google *Noticias* un dominio que no indexa como prensa.

Lo que sí funciona y sigue activo: que una noticia de prensa **mencione**
a la CEPAL se detecta con la palabra clave `cepal` de
`PALABRAS_CLAVE_RELEVANCIA`.

Si alguien quiere reintentarlo, la vía con más futuro es que los feeds
de ReDeSoc vuelvan a responder (https://dds.cepal.org/redesoc/noticias).

## El editor: cómo se decide qué entra (reescrito el 29-sep-2026)

Durante semanas el sistema decidía con **listas de palabras clave** y
solo llamaba al modelo al final, para rescatar dudosas cuando faltaba
cupo. Un reporte tras otro se colaba algo —loterías, un artículo sobre
IA, unos desalojos, una fiesta patria, cinco comunicados del IGSS— y
cada vez se añadía una regla nueva.

Mirando los once fallos juntos apareció el patrón: **casi todos eran el
sistema rellenando un cupo**, y las reglas eran una lista de
exclusiones aprendida a golpes que nunca iba a estar completa.

La corrección son dos decisiones, y entre las dos **quitan código en
vez de añadirlo**.

### 1. El cupo es un techo, no una meta

`n_noticias` era un objetivo que el sistema se esforzaba en alcanzar.
Ahora es un máximo. Si un país solo tiene dos noticias que valgan, se
publican dos y el reporte lo dice.

Eso no es una carencia: **es información**. Que un país tenga dos y
otro cinco dice algo real sobre la cobertura mediática de la protección
social en cada uno.

### 2. Los filtros deciden el país; el editor decide el tema

Estaba al revés. Se usaban reglas de texto para lo que peor se les da
—juzgar si una noticia *trata* del tema— y se reservaba para último
recurso el componente que mejor lo juzga.

Ahora:

- **Los filtros de texto deciden el PAÍS**: dominio curado, nombre del
  país, topónimos homónimos, TLD, fecha, páginas de índice. Todo eso es
  objetivo, barato y verificable, y ahí las reglas funcionan bien.
- **El editor (`puntuar_candidatas`) puntúa el TEMA y el valor
  noticioso** de *todas* las candidatas, de 0 a 3, con una razón. Se
  publican las que llegan a `NOTA_MINIMA_PARA_PUBLICAR` (2), ordenadas
  por nota.

**El lote es lo que lo hace viable.** Puntuar de una en una serían ~120
llamadas y siete minutos. Metiendo todas las candidatas de un país en
un solo mensaje son **10 llamadas por reporte**. Y hay un efecto
secundario que importa más que el ahorro: el modelo ve las candidatas
**juntas y en competencia** ("de estas ocho, ¿cuáles son las mejores?")
en vez de una a una con un hueco que llenar, que era exactamente la
situación que lo volvía complaciente.

**Coste:** ~45 llamadas y ~33.000 fichas por reporte, frente a las
~22.000 de antes. Unos 4 minutos de API, comparable a la versión
anterior en sus casos malos.

**Si el editor no responde** (Groq caído, bloqueo de red), no se pierde
el reporte: se publica lo que aprobaron los filtros, marcado como
*sin revisar*, y se avisa.

### El alcance temático: dónde está la frontera

Decisión de la Unidad, 30-sep-2026, tras ver que el editor descartaba
el debate salvadoreño sobre la jornada de cuatro días:

> **La política laboral entra solo cuando toca la seguridad social.**
> Cotizaciones, afiliación, pensiones, cobertura, prestaciones: sí. Una
> reforma de la jornada o del salario mínimo por sí sola: no. La misma
> reforma contada por su efecto sobre las cotizaciones: sí.

Está escrita como regla explícita en el prompt del editor. Es la clase
de criterio que una lista de palabras clave no puede expresar —depende
de qué trata la noticia, no de qué palabras contiene— y es justo por
esto que la decisión pasó al modelo.

Si el criterio cambia, se ajusta ahí: no hay que tocar ninguna lista.

### Lo que esto te da además

Cada noticia lleva su **nota y su razón**, visibles en la app, y hay un
panel con **lo que se revisó y no se incluyó**, también con su razón.
La decisión deja de ser una caja negra: se puede comprobar si algo
bueno se quedó fuera.

Y esas puntuaciones, revisadas por una persona, son exactamente el
**conjunto etiquetado** que hace falta para evaluar el sistema con
método (ver la propuesta de evals). El período de prueba produce el
dataset como subproducto.

### Qué se retiró

`verificar_relevancia_llm` (el verificador de una en una) y
`_completar_con_verificacion_llm` (el que rellenaba el cupo). Las
reglas temáticas de texto siguen ahí como señal para ordenar las
candidatas, pero ya no deciden.

## Reparación del titular (30-sep-2026)

Dos defectos de presentación que venían de la fuente, no de la app,
pero que quedaban igual de mal en el documento. Se corrigen en
`_convertir`, la puerta de entrada, para que todo lo de aguas abajo
—editor, resumen, Word— trabaje ya con el título limpio.

**Titulares cortados.** Las cuatro noticias de El Salvador salieron
como "Piden a la OIT observar proceso de modificación ...": Google
trunca los titulares largos en su pestaña de Noticias. La pieza que
faltaba estaba a la vista: **el titular completo está en la URL**,
porque los gestores de contenido generan el enlace a partir de él.
`completar_titulo_truncado` conserva el trozo original —bien escrito,
con tildes y mayúsculas— y añade solo lo que falta, tomado del slug.

Dos salvaguardas para no inventar titulares: se exige que el prefijo
solape con el slug en al menos un 60 % de sus palabras (si no, el
enlace no corresponde al titular y no se toca nada), y si algo no
cuadra se devuelve el título tal cual. **Es preferible un titular
cortado a uno inventado.**

El trozo que viene del slug llega sin tildes ni eñes, así que se
restauran **copiándolas del extracto** cuando esas mismas palabras
aparecen allí bien escritas: no se inventa nada, se copia de lo que el
propio medio publicó. Cuando el extracto no las trae, el titular queda
completo pero con alguna palabra sin tilde — un defecto mucho menor
que los puntos suspensivos.

Ojo con los identificadores del final del slug: se descartan
("...-893510", "...-20260928-0086"), pero **un año de cuatro cifras se
conserva**, porque suele formar parte del titular
("...-a-agosto-de-2026").

**Caracteres corruptos.** "Sigue Coahuila sumando establecimientos a la
cruzada por la inclusiÃ³n": esa "Ã³" son los dos bytes de la "ó"
leídos de uno en uno. `reparar_mojibake` lo deshace, y solo actúa si la
conversión de vuelta deja menos secuencias raras de las que había — un
texto correcto sale intacto.

## Repeticiones del mismo hecho

En Haití las cinco noticias eran la misma historia —la reforma de
pensiones del ONA— contada por cinco medios, dos de ellas del mismo
diario con una semana de diferencia. No eran duplicados: eran
artículos distintos sobre el mismo hecho, así que el deduplicado por
parecido de titulares no podía atraparlos (comparten dos palabras de
seis).

Lo resuelve el editor, y es un buen ejemplo de por qué puntuar **por
lotes** era la decisión correcta: como ve todas las candidatas del país
a la vez, puede reconocer que cubren el mismo hecho. Su instrucción es
quedarse con la más completa y marcar el resto con nota 1 y la razón
"repite la noticia N". Un verificador que las mirara de una en una
nunca podría hacerlo.

## Páginas de listado que no son noticias

En Nicaragua entraron dos entradas tituladas "Vienicsa" y
"Económicas": no eran notas, sino la página de una etiqueta de La
Prensa y el listado de la sección Económicas de El 19 Digital.
`_es_pagina_indice` las detecta por la ruta de la URL (`/tag/`,
`/vertodos/`, `/seccion/`, `?page=`…) o porque el título tiene una o
dos palabras — ningún titular real se resume en dos palabras, pero los
nombres de sección sí. Es un descarte duro.

## Mantenimiento: las listas de medios

`SITIOS_PAIS` en `scraper.py` es el corazón del sistema: un medio que
no está en la lista de su país no puede aparecer en su sección.

**Revisión completa con verificación por búsqueda: 29-sep-2026.** Se
comprobó dominio por dominio que existe, que la grafía es correcta y
que el medio sigue publicando. Lo que apareció:

- **`republica.gt` estaba muerto.** Redirige a `republica.com/usa`, así
  que una de las cinco entradas de Guatemala llevaba tiempo sin
  devolver nada. Retirado.
- **`elmundo.sv` y `diario.elmundo.sv` eran la misma cosa.** Se deja
  solo `elmundo.sv`: el operador `site:` y el código hacen match por
  subdominio, así que cubre los dos.
- **La lista de Cuba era toda de medios del exilio.** Faltaba la prensa
  oficial publicada desde Cuba —Granma, Cubadebate, Trabajadores—, que
  es justamente la que informa de los pagos a jubilados y las
  resoluciones del MTSS. Sin ella, la sección de Cuba solo veía el tema
  desde fuera.
- **Haití**, el país con peor cobertura histórica, tenía cinco medios y
  uno (`loophaiti.com`) sin publicaciones verificables desde 2020. Se
  retiró y se añadieron cinco medios francófonos, entre ellos
  `lenational.org`, que cubrió el foro del ONA sobre pensiones.
- Varios medios que ya venían aportando noticias **por la capa 2**
  —`criterio.hn`, `proceso.hn`, `elmundo.cr`, `juno7.ht`,
  `divergentes.com`, `grupoanimal.mx`— no estaban en la capa 1. Ahora
  sí, que es más barato y más preciso.
- `animalpolitico.com` redirige a `grupoanimal.mx`; se usa el segundo.
- `lateja.cr` (sucesos y deportes) y `periodicocubano.com` se retiraron
  para dejar sitio sin alargar de más la consulta.

**Criterios al añadir un medio:**

1. Diarios nacionales, medios económicos y medios de investigación de
   alcance nacional. **Nunca medios locales o estatales** — son la
   causa de las notas de Veracruz, Coahuila y Quintana Roo que se
   colaron en reportes anteriores.
2. **Unos 8 dominios por país como tope.** Cada dominio alarga la
   consulta, y las consultas largas con `site:` fueron lo que falló en
   la incidencia de SerpAPI del 20-sep-2026. Hoy las consultas van de
   270 a 430 caracteres (Haití es la más larga, por el vocabulario
   francés). Si vuelven los tiempos de espera agotados, este es el
   primer sitio donde mirar.
3. Verificar el dominio con una búsqueda antes de añadirlo. Dos de las
   sorpresas de esta revisión fueron dominios que parecían obvios y
   estaban mal.

### Sitios institucionales (reserva, no están en uso)

Se verificaron pero **se dejaron fuera a propósito**: ya llegan por la
capa de anclas cuando son noticia, y en la capa 1 desplazarían al
periodismo por comunicados — Guatemala ya salió 4 de 5 con notas del
IGSS. Quedan aquí por si algún país necesita refuerzo:

| País | Dominios verificados |
|---|---|
| Costa Rica | `ccss.sa.cr`, `imas.go.cr`, `supen.fi.cr`, `fodesaf.go.cr`, `mtss.go.cr` |
| Cuba | `mtss.gob.cu` (el INASS fue disuelto y absorbido por el MTSS) |
| El Salvador | `isss.gob.sv`, `pensiones.gob.sv` (ISP), `mtps.gob.sv`, `mindel.gob.sv` |
| Guatemala | `igssgt.org`, `mides.gob.gt`, `mintrabajo.gob.gt` |
| Haití | `ona.ht` (no `ona.gouv.ht`), `ofatma.gouv.ht`, `faes.gouv.ht`, `communication.gouv.ht` (comunicados del MAST) |
| Honduras | `ihss.hn`, `sedesol.gob.hn`, `injupemp.gob.hn`, `inprema.gob.hn` |
| México | `imss.gob.mx`, `bienestar.gob.mx`, `coneval.org.mx` (los comunicados están en `.org.mx`, no en `.gob.mx`) |
| Nicaragua | `inss.gob.ni` — `mifamilia.gob.ni` emite `noindex`, así que `site:` no lo alcanza |
| Panamá | `css.gob.pa`, `mides.gob.pa`, `mitradel.gob.pa` |
| Rep. Dominicana | `cnss.gob.do`, `tss.gob.do`, `gabinetesocial.gob.do`, `superate.gob.do`, `siuben.gob.do` |

## Cuando Groq responde 403: bloqueo de red, no de clave

**Caso real del 29-sep-2026.** De un día para otro, ningún resumen se
generaba y el detalle técnico decía:

```
403 - {'error': {'message': 'Access denied. Please check your network settings.'}}
```

No era la clave (sería 401), ni la cuota (429), ni el modelo retirado
(`gpt-oss-120b` sigue siendo el recomendado por Groq). **Es Cloudflare,
que Groq tiene delante de su API, bloqueando las peticiones que salen
de rangos de IP de centros de datos y VPN.** Streamlit Cloud es un
centro de datos.

Tres consecuencias que conviene entender:

- El rechazo ocurre **antes** de comprobar la clave, así que renovarla
  no sirve de nada.
- **Cambiar de modelo tampoco**: ninguna petición llega al modelo. Por
  eso la lista de respaldo `MODELOS_GROQ` no ayuda aquí, y hace bien en
  no avanzar (un 403 no es señal de retiro).
- **No aparecerá en groqstatus.com.** Para Groq no es una avería: es su
  política de seguridad funcionando. No se "arregla" solo.

### Qué hacer, en orden

**1. Reiniciar la app.** Al reiniciar puede tocarte otra IP de salida y
a veces basta con eso. Es gratis y tarda un minuto, así que se prueba
primero.

**2. Enrutar por una pasarela, sin tocar el código.** Si el bloqueo
persiste, añade en Streamlit Cloud (Settings → Secrets) el secret
opcional:

```toml
GROQ_BASE_URL = "https://gateway.ai.cloudflare.com/v1/<cuenta>/<pasarela>/groq"
```

La app lo detecta sola, lo usa en vez de la API oficial y muestra un
aviso en el panel lateral. Sin ese secret todo sigue como siempre.

Para obtener esa dirección: crear una cuenta gratuita en Cloudflare →
AI Gateway → crear una pasarela → elegir Groq como proveedor. Cloudflare
lo documenta en
https://developers.cloudflare.com/ai-gateway/usage/providers/groq/ .
Groq acepta ese tráfico por venir de un servicio suyo conocido.

Advertencia honesta: la pasarela pasa a ver las claves y los textos que
circulan. Para noticias públicas no es grave, pero conviene saberlo.

**3. Si nada de lo anterior funciona**, la otra vía documentada es
cambiar la huella TLS del cliente (con `curl_cffi`), porque parte del
bloqueo es por *fingerprinting* y no solo por IP. Es más frágil y solo
merece la pena si la pasarela falla.

No hay procedimiento oficial de Groq para pedir el desbloqueo de un
rango, ni dato público sobre cuánto tardan. El foro
(community.groq.com) es la única vía de contacto identificable.

## Mantenimiento: deprecaciones de modelos de Groq

Groq retira modelos periódicamente. Avisa por correo con semanas de
anticipación y los apaga en una fecha fija; después de esa fecha, las
llamadas a ese modelo fallan y el Agente 2 deja de generar resúmenes.
**Esto ya ocurrió**: el 16 de agosto de 2026 se apagó
`llama-3.3-70b-versatile`, que era el único modelo de la app, y los
reportes pasaron a mostrar el texto original de cada noticia en vez de
un resumen.

Para que no vuelva a tumbar la app, `summarizer.py` ya no depende de un
modelo único sino de una **lista de respaldo** (`MODELOS_GROQ`). Si el
modelo preferido ya no existe, el sistema pasa solo al siguiente y sigue
trabajando; además, la app ahora muestra un aviso rojo bien visible
cuando ningún resumen pudo generarse, en vez de fallar en silencio.

**Cuándo actuar:** al recibir un correo de deprecación de Groq, o si el
panel lateral muestra un modelo distinto al esperado. La acción es
sencilla: agregar el modelo nuevo **al inicio** de `MODELOS_GROQ` en
`summarizer.py` y subir el archivo. La tabla oficial de retiros está en
https://console.groq.com/docs/deprecations — conviene revisarla cada
pocos meses, porque los modelos de respaldo también pueden caducar.

## Posibles mejoras futuras

- Exportar también a PDF además de Word.
- Guardar histórico de reportes generados (por fecha) en Google Drive
  o una base de datos persistente fuera del contenedor (ej. Supabase),
  ya que SQLite local se pierde en cada redeploy de Streamlit Cloud.
- Programar la ejecución automática diaria (ej. con un cron job o
  GitHub Actions) que llene el caché una vez al día, para que los
  usuarios siempre encuentren el reporte ya listo sin esperar.
- Evaluar un plan de pago de Groq si el uso diario lo justifica: subiría
  el límite de tokens por minuto y permitiría bajar la espera entre
  llamadas, acortando el tiempo del reporte completo.

