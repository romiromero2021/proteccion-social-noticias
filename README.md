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
cepal.py         -> Sección regional de la CEPAL (dominios, términos, query)
summarizer.py    -> AGENTE 2: resume con Groq (GPT OSS 120B) + genera el .docx
cache.py         -> Caché diario por país en SQLite (cache_noticias.db)
requirements.txt -> Dependencias
```

El reporte tiene **11 secciones**: los 10 países más una sección
regional, `CEPAL (regional)`, con el material de la CEPAL que no
corresponde a un país en particular (informes regionales, seminarios,
notas comparativas).

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

## La sección regional de la CEPAL

Además de la prensa nacional, el reporte tiene una sección
`CEPAL (regional)` con lo que publica la propia CEPAL sobre el tema,
**incluidas sus notas sobre los diez países**. Ahí una nota sobre
Honduras no es ruido: es el contenido. Por eso, solo para esa sección,
los filtros de país cruzado no se aplican (ver `_buscar_una_vez`);
quedan el de fecha y el de tema.

Se busca con SerpAPI restringido a `cepal.org` y `dds.cepal.org`,
así que **consume 1 búsqueda por reporte**. Con una diferencia
importante respecto a los países: **usa la búsqueda WEB, no la
pestaña de Noticias de Google**.

Por qué. El 29-sep-2026, con `tbm=nws`, la consulta de la CEPAL agotó
el tiempo de espera (25 s, dos intentos) mientras los 10 países
respondían sin problema. No era cuestión de longitud: la consulta de
la CEPAL es la **más corta** de todas, 173 caracteres frente a los 430
de Haití. Era que se le estaba pidiendo a Google *Noticias* un dominio
que no indexa como prensa —cepal.org es un organismo internacional, no
un periódico—. Es la misma familia de fallo que la incidencia de
SerpAPI del 20-sep-2026 ("requests timing out while using tbm=nws with
advanced parameters"). Lo controla el parámetro `buscar_en_noticias`
de `_buscar_una_vez`.

Ese cambio arrastró dos ajustes más, porque los resultados web no
vienen igual que los de Noticias:

- **Fechas con el mes en letra** ("23 sept 2026", "Sep 23, 2026"). No
  se interpretaban, y como una fecha ilegible se deja pasar por
  defecto, el filtro de antigüedad quedaba desactivado de hecho para
  esta sección: habrían entrado páginas de hace años. Lo resuelve
  `_parsear_fecha_con_mes_en_letra`, en español e inglés.
- **Nombre del medio.** Los resultados web no suelen traer el campo
  `source`, y las notas salían como "Fuente desconocida". Ahora se
  deduce del dominio, y las de cepal.org se etiquetan como "CEPAL". Una nota de cepal.org nunca
aparece en la sección de un país: su dominio pertenece a esta sección.

**Historia, para no repetir el camino** (`cepal.py` la documenta en
detalle):

1. *La palabra "CEPAL" en los términos de búsqueda.* No podía
   funcionar: la capa 1 restringe con `site:` a prensa nacional y
   cepal.org no cabe ahí; en la capa 2 se buscaba como frase exacta,
   que no aparece en ningún titular. El término se retiró.
2. *Los feeds RSS de ReDeSoc.* Era la vía ideal —gratis, ya curada por
   la División de Desarrollo Social, sin gastar cuota—, pero **están
   rotos del lado de la CEPAL**: verificado el 29-sep-2026, tanto
   `redesoc-rss.php` como `redesoc-proteccionsocial.php` devuelven
   error HTTP 500. El reporte de ese día salió con la sección vacía
   por eso.
3. *La vía actual, con SerpAPI.* Más pobre que el RSS, pero reutiliza
   maquinaria ya probada en producción en vez de un camino propio que
   solo falla en silencio.

Si los feeds vuelven a responder conviene reconsiderarlo. La página de
referencia es https://dds.cepal.org/redesoc/noticias.

## Cuando el tema está en las palabras pero no en la noticia

Dos casos confirmados el 29-sep-2026, con causas distintas:

**El acto ceremonial.** "Celebra IMSS Veracruz Norte Fiestas Patrias
2026 en Centro de Seguridad Social Xalapa" pasó todos los filtros con
holgura, porque "seguridad social" e "IMSS" están literalmente en el
titular. Y lo están: es el nombre del lugar y el de la institución que
organiza la fiesta. `_es_evento_ceremonial` detecta ahora los actos
festivos, ceremoniales y deportivos en el TÍTULO
(`EVENTOS_CEREMONIALES`) y manda la noticia al verificador en vez de
aceptarla directo. No se descarta en duro: hay actos que sí son
noticia del tema —la firma de un convenio en un acto público—, y esa
distinción necesita criterio.

**La cola del verificador.** "Instituciones que persiguen el crimen
priorizan desalojos frente a otros delitos" entró en Honduras sin
tener ni una palabra del tema. Había quedado marginal por
`tema_ausente`, y el verificador la revisó para llenar el quinto hueco
y dijo que sí.

La corrección es de orden, no de exclusión. Cada descarte marginal
lleva ahora registrado su motivo (`_motivo_marginal`), y el
verificador las revisa según `PRIORIDAD_MOTIVO_MARGINAL`: **las
dudosas por país primero, las que no tienen ni una palabra del tema al
final de la cola**. El verificador juzga bien el país —esa pregunta es
objetiva— pero ha demostrado ser demasiado generoso con el tema. Al
prompt se le añadieron además las dos exclusiones explícitas:
seguridad pública no es seguridad social, y que un acto ocurra en un
"Centro de Seguridad Social" no convierte la fiesta en noticia.

**Efecto secundario deseado:** el sistema ahora prefiere entregar
cuatro noticias buenas antes que cinco con una mala. La presión por
llenar el cupo era la causa de fondo.

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

