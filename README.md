# Resumen Diario: Programas de Protección Social (México, CA + Caribe)

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
summarizer.py    -> AGENTE 2: resume con Groq (Llama 3.3 70B) + genera el .docx
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
   ```
5. Deploy. Te dará una URL pública tipo `https://tu-app.streamlit.app`
   que puedes compartir o usar a diario.

## Notas sobre cuotas (para no quedarte sin crédito)

- **SerpAPI free tier:** ~100 búsquedas/mes. Con el caché diario, en el
  mejor caso (1 sola persona usando la app, 1 vez al día) consumes
  ~10 búsquedas/día = ~300/mes, lo cual **sigue excediendo** el free
  tier si lo corres todos los días. El caché ayuda principalmente
  cuando **varios usuarios** comparten la misma app el mismo día (todos
  se benefician de la primera búsqueda), no reduce el consumo si solo
  hay un usuario corriéndolo diariamente. Para uso diario sostenido,
  considera el plan de pago más económico de SerpAPI.
- **Groq (llama-3.3-70b-versatile), free tier:** 30 solicitudes/minuto,
  1,000 solicitudes/día, 12,000 tokens/minuto. Con **5 noticias por
  país × 10 países = 50 llamadas por ejecución**, el límite diario
  (1,000 RPD) sobra de lejos, pero el límite **por minuto (30 RPM)**
  sí puede alcanzarse si las 50 llamadas se disparan muy rápido — el
  código ya maneja esto con reintentos automáticos y espera progresiva
  (2s, 4s, 8s) cuando Groq responde "demasiadas peticiones", así que la
  ejecución simplemente tarda un poco más en esos casos en vez de fallar.
  Si notas que muchos países muestran "⚠️ ver detalle técnico" con error
  429, es buena señal de que estás chocando contra el límite por minuto;
  no es un problema grave, solo toma más tiempo terminar.

## Posibles mejoras futuras

- Exportar también a PDF además de Word.
- Guardar histórico de reportes generados (por fecha) en Google Drive
  o una base de datos persistente fuera del contenedor (ej. Supabase),
  ya que SQLite local se pierde en cada redeploy de Streamlit Cloud.
- Programar la ejecución automática diaria (ej. con un cron job o
  GitHub Actions) que llene el caché una vez al día, para que los
  usuarios siempre encuentren el reporte ya listo sin esperar.
- Agregar una pequeña espera entre llamadas consecutivas a Groq (ej.
  1-2 segundos) para repartir las 50 llamadas dentro del límite de 30
  RPM sin depender tanto de los reintentos.

