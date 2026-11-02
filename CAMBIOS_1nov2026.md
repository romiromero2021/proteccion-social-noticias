# Correcciones del 1 de noviembre de 2026

Tres averías detectadas leyendo los reportes del 23-oct, 31-oct y 1-nov.
Todo lo que sigue está probado: `python -m pytest evals/ -q` da
**120 pasan, 4 fallan a propósito** (las cuatro del hueco de
saneamiento, que sigue sin aplicarse adrede).

## Archivos

| Archivo | Qué cambió |
|---|---|
| `scraper.py` | fechas relativas, enlaces redirectores, registro de ramas |
| `verificacion.py` | **nuevo** — contrasta fecha y enlace contra la página del medio |
| `summarizer.py` | llama a la verificación antes de resumir; arrastra las ramas |
| `app.py` | muestra en cada país qué ramas se tomaron |
| `evals/test_fechas_y_enlaces.py` | **nuevo** — 53 pruebas, ninguna toca la red |

## 1. El filtro de fecha no filtraba

`_parsear_fecha_serpapi` devolvía `datetime.now()` para **cualquier**
texto que contuviera «hace» o «ago», sin leer la cantidad ni la unidad.

- «hace 2 semanas» se trataba como «ahora» → así entró la nota de la
  OIT sobre Honduras el 1-nov, con doce días y el límite en diez.
- «Il y a 2 jours» no casaba con ningún término de la lista → devolvía
  `None` → y, por la regla de `_dentro_del_rango`, también pasaba.
  **Haití llevaba meses sin filtro de fecha efectivo.**

En la práctica el límite de diez días solo se aplicaba cuando la fecha
venía incrustada en la URL o en formato absoluto.

Ahora hay `_parsear_fecha_relativa`, que entiende cantidad y unidad en
español, inglés y francés (minutos, horas, días, semanas, meses, años,
«ayer», «hier», «yesterday»).

**Efecto medido sobre el reporte del 1-nov: se descarta exactamente una
noticia**, la de la OIT. Ninguna otra cambia.

## 2. Enlaces envueltos en el redirector de Google

De 0 de 44 enlaces el 23-oct a 23 de 38 el 31-oct y 20 de 37 el 1-nov.
No cambió el código: cambió lo que devuelve el proveedor.

El daño no era estético. Seis filtros razonan sobre el dominio y con un
enlace `google.com/goto?url=CAES…` se quedaban ciegos a la vez: la
fecha incrustada en la URL (la fuente de fecha **más** fiable), el
reconocimiento de medios curados, la protección contra noticias de otro
país y la corroboración de `_es_pagina_indice`.

Tres defensas, en orden de coste:

1. `url_real_sin_red()` — recupera la URL del medio de la propia ficha:
   del parámetro `url=`/`q=` cuando viene en claro, o del favicon de la
   fuente, que suele llevar el dominio. Sin red y sin coste.
2. `_fuente_casa_con_dominio()` — si no hay URL, reconoce al medio
   curado por su **nombre** («Prensa Libre» ↔ prensalibre.com).
3. `verificacion.py` — para lo que sí se publica, resuelve el
   redirector con una petición y guarda la URL final en el documento.

El token `CAES…` va cifrado y no contiene la URL: hay una prueba que lo
deja anotado para que nadie vuelva a intentar descifrarlo.

## 3. Fechas falsas en origen

La misma nota de Vanguardia.cu salió «Hace 6 días» (23-oct), «Hace 2
días» (31-oct) y «hace 13 horas» (1-nov). El artículo es del **17 de
julio**. No se desvía: rejuvenece en cada corrida. Otra (GatoEncerrado)
repitió «hace 3 días» en dos reportes seguidos; una tercera
(Guananoticias) avanzó bien de 3 a 4 días, que es el control.

Ningún filtro podía atrapar esto, porque el dato era falso antes de
entrar. `verificacion.py` lee la fecha que **publica el propio medio**
en su página (`datePublished`, `article:published_time`, `<time>`, o
«17 de julio de 2026» en el cuerpo) y:

- si está dentro del rango, **corrige la fecha** que verá quien lea el
  reporte: en vez de «hace 13 horas», «17 jul 2026»;
- si está fuera, la manda al panel de descartadas con el motivo
  escrito, comparando las dos fechas;
- ante cualquier fallo —red, tiempo agotado, HTML raro— deja la noticia
  **exactamente como estaba**. Verificar no puede ser una forma nueva
  de perder noticias.

Se aplica solo a lo ya seleccionado (cinco como mucho por país), en
paralelo, con 8 segundos de tope por petición. No se usa
`dateModified`: una nota de julio reeditada en octubre sigue siendo de
julio, y usarla reproduciría el error que esto corrige.

Se puede apagar con `PS_VERIFICAR_FECHAS=0` sin tocar el código.

## 4. Las cuatro ramas ya dejan rastro

Era la pieza que faltaba para poder diagnosticar: al mirar el reporte
del 1-nov no había forma de saber si Honduras traía dos noticias porque
esa semana hubo poco o porque una consulta se amplió, se recortó o se
cayó.

Cada reporte lleva ahora una lista `ramas` con las que se tomaron, y la
pestaña del país la muestra en una línea:

- la lista de medios no bastó: se buscó también en abierto
- una consulta volvió vacía: se amplió la ventana a dos semanas
- el buscador se colgó: se reintentó con una consulta más corta
- ⚠ el editor no respondió: se publicó SIN revisión del modelo

No cambia ninguna decisión. Solo deja constancia.

## Lo que NO se tocó, a propósito

- **El saneamiento de los titulares.** Las cuatro pruebas adversariales
  siguen fallando a propósito, como hueco conocido. Era una decisión
  tuya y el taller es en tres días.
- **Los resúmenes que repiten el titular** (Honduras #1 y México #5 del
  23-oct). El resumidor solo ve el titular y 280 caracteres; cuando el
  extracto no añade nada, parafrasea. Es el modo de fallo correcto: no
  inventa. Ahora que `verificacion.py` ya descarga la página de las
  noticias publicadas, se le podría pasar el primer párrafo real del
  artículo y el problema desaparecería de raíz — pero eso cambia lo que
  ve el resumidor, que es justo lo que describe la presentación. Para
  después del 4 de noviembre.
- **El catálogo de incidentes** sigue en 18. Las entradas 19, 20 y 21
  están redactadas y listas para pegar, pero subirlo a 21 obliga a
  cambiar las láminas.
