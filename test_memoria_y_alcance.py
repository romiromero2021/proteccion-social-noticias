"""
PRUEBAS DE LAS CORRECCIONES DEL 9-nov-2026
==========================================
Cada prueba de este archivo corresponde a una deficiencia concreta del
reporte del 9 de noviembre de 2026, con su noticia real. No hay casos
inventados: el titular, el medio y el enlace son los que aparecieron.

Todas corren SIN RED. Lo que depende del modelo de lenguaje —la nota
que pone el editor— no se puede probar aquí; lo que sí se prueba es
todo lo que el código decide por su cuenta, que es donde están cuatro
de las cinco correcciones.

    python3 evals/test_memoria_y_alcance.py

Las cinco deficiencias:
  1. Costa Rica — un comunicado de asamblea sindical publicado, y una
     marcha por la CCSS descartada.
  2. Cuba — la nota de Vanguardia.cu del 17 de julio, en todos los
     reportes desde octubre.
  3. Guatemala — una actividad local de un portal de gobierno por
     encima de una nota nacional de un medio curado.
  4. Haití — una noticia de Francia, de France 24, publicada como
     noticia haitiana.
  5. R. Dominicana — salarios que no alcanzan para vivienda y jóvenes
     sin primer empleo, las dos con nota 1.
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import scraper  # noqa: E402
import summarizer  # noqa: E402


# ---------------------------------------------------------------------------
# 1 y 3 — ACTOS ORGÁNICOS Y ALCANCE
# ---------------------------------------------------------------------------

class TestActosOrganicos(unittest.TestCase):
    """Caso 1: la asamblea sindical de Costa Rica."""

    def test_la_asamblea_sindical_real_se_detecta(self):
        item = {
            "title": ("Comunicado: SINDICATO DE TRABAJADORAS Y TRABAJADORES "
                      "DE LA EDUCACIÓN COSTARRICENSE SEC - LVII ASAMBLEA "
                      "NACIONAL ORDINARIA"),
            "link": "https://www.larepublica.net/comunicado-sindicato-sec",
        }
        self.assertTrue(scraper._es_acto_organico(item))

    def test_la_marcha_por_la_ccss_no_es_acto_organico(self):
        """La que debería haber entrado no se marca."""
        item = {
            "title": ("Grupos marchan en San José para exigir mayor apoyo a "
                      "la CCSS y pago de deudas del Estado"),
            "link": "https://www.teletica.com/nacional/grupos-marchan-en-san-jose_420770",
        }
        self.assertFalse(scraper._es_acto_organico(item))
        self.assertFalse(scraper._es_evento_ceremonial(item))

    def test_sin_tildes_y_mayusculas(self):
        """El titular real venía en mayúsculas; la detección no depende
        de tildes ni de caja."""
        for titulo in ["JURAMENTACION de la nueva junta directiva",
                       "Juramentación de la nueva junta directiva",
                       "IGSS conmemora su aniversario número 80",
                       "Toma de posesion del nuevo director del INSS"]:
            with self.subTest(titulo=titulo):
                self.assertTrue(scraper._es_acto_organico({"title": titulo}))

    def test_una_medida_no_se_confunde_con_un_acto(self):
        for titulo in ["IGSS anuncia bono extraordinario para pensionados",
                       "Mides anuncia último pago del año de los programas "
                       "de transferencias",
                       "Deuda de pensiones llega a $11,874.74 millones"]:
            with self.subTest(titulo=titulo):
                self.assertFalse(scraper._es_acto_organico({"title": titulo}))

    def test_acto_organico_es_marginal_no_descarte_duro(self):
        """Una asamblea puede aprobar algo real: la decide el editor."""
        self.assertIn("acto_organico", scraper.PRIORIDAD_MOTIVO_MARGINAL)


# ---------------------------------------------------------------------------
# 4 — PRENSA INTERNACIONAL
# ---------------------------------------------------------------------------

class TestPrensaInternacional(unittest.TestCase):
    """Caso 4: la nota de France 24 en el reporte de Haití."""

    FRANCE24 = {
        "title": ("Conférence sociale en direct : le gouvernement annonce "
                  "une hausse du salaire minimum de 1,6"),
        "snippet": ("Le gouvernement a annoncé une hausse du salaire minimum "
                    "de 1,6 % lors de la conférence sociale."),
        "link": ("https://www.france24.com/fr/info-en-continu/20261109-"
                 "conference-sociale-en-direct"),
        "source": {"name": "France 24"},
    }

    def test_france24_sin_nombrar_haiti_es_descarte_duro(self):
        self.assertTrue(
            scraper._es_internacional_sin_el_pais(self.FRANCE24, "Haití"))

    def test_france24_nombrando_haiti_sobrevive(self):
        """Un medio internacional que SÍ cubre el país es legítimo."""
        item = dict(self.FRANCE24)
        item["title"] = "En Haïti, le gouvernement annonce une hausse du salaire minimum"
        self.assertFalse(scraper._es_internacional_sin_el_pais(item, "Haití"))

    def test_un_medio_haitiano_curado_nunca_cae_aqui(self):
        item = {
            "title": "Protection sociale : l'allocation chômage",
            "link": "https://lenouvelliste.com/article/273511/protection-sociale",
            "source": {"name": "Le Nouvelliste"},
        }
        self.assertFalse(scraper._es_internacional_sin_el_pais(item, "Haití"))

    def test_el_salvador_y_el_pais_de_espana(self):
        """El mismo agujero en español: El País cubriendo España."""
        item = {
            "title": "El Gobierno aprueba la subida del salario mínimo para 2027",
            "snippet": "El Consejo de Ministros aprobó la subida.",
            "link": "https://elpais.com/economia/2026-11-09/salario-minimo.html",
            "source": {"name": "El País"},
        }
        self.assertTrue(
            scraper._es_internacional_sin_el_pais(item, "El Salvador"))

    def test_el_filtro_duro_esta_conectado_al_flujo(self):
        """Que la función exista no basta: tiene que estar llamada."""
        import inspect
        codigo = inspect.getsource(scraper._buscar_una_vez)
        self.assertIn("_es_internacional_sin_el_pais", codigo)


class TestOrdenDeRescate(unittest.TestCase):
    """La cola de rescate ya no ofrece primero lo que no tiene evidencia."""

    def test_sin_evidencia_de_pais_va_al_final(self):
        prio = scraper.PRIORIDAD_MOTIVO_MARGINAL
        self.assertGreater(prio["sin_evidencia_de_pais"],
                           prio["tema_solo_en_extracto"])
        self.assertGreater(prio["sin_evidencia_de_pais"],
                           prio["menciona_otro_pais"])
        # Solo "tema_ausente" queda por detrás.
        self.assertEqual(
            max(prio.values()), prio["tema_ausente"])

    def test_ordenar_marginales_respeta_el_orden_nuevo(self):
        marginales = [
            {"titulo": "sin evidencia", "_motivo_marginal": "sin_evidencia_de_pais"},
            {"titulo": "tema débil", "_motivo_marginal": "tema_solo_en_extracto"},
        ]
        ordenadas = scraper.ordenar_marginales(marginales)
        self.assertEqual(ordenadas[0]["titulo"], "tema débil")


# ---------------------------------------------------------------------------
# 1, 2 y 3 — LA PROCEDENCIA PESA EN LA SELECCIÓN
# ---------------------------------------------------------------------------

class TestMedioCuradoEnLaSeleccion(unittest.TestCase):
    """
    Los tres casos donde la noticia que entró venía de un medio no
    curado y la que quedó fuera, de uno curado.
    """

    def test_reconoce_los_medios_curados_reales(self):
        casos = [
            ("https://agn.gt/mas-de-6-mil-guatemaltecos-acceden-a-empleos/", "Guatemala", True),
            ("https://guatemala.gob.gt/puerto-barrios-continua-conectando/", "Guatemala", False),
            ("https://diariodecuba.com/cuba/1794067210_69746.html", "Cuba", True),
            ("http://www.vanguardia.cu/de-cuba/37891-actualizan-salario-minimo", "Cuba", False),
            ("https://www.teletica.com/nacional/grupos-marchan-en-san-jose_420770", "Costa Rica", True),
            ("https://www.larepublica.net/comunicado-sindicato-sec", "Costa Rica", False),
            ("https://almomento.net/bajos-salarios-limitan-acceso-a-viviendas/", "República Dominicana", True),
        ]
        for link, pais, esperado in casos:
            with self.subTest(link=link):
                self.assertEqual(
                    scraper.es_de_medio_curado({"link": link}, pais), esperado)

    def test_a_igual_nota_gana_el_medio_curado(self):
        pais = "Guatemala"
        puntuadas = [
            {"titulo": "actividad local", "nota": 2,
             "link": "https://guatemala.gob.gt/puerto-barrios/"},
            {"titulo": "empleos temporales", "nota": 2,
             "link": "https://agn.gt/mas-de-6-mil-guatemaltecos/"},
        ]
        puntuadas.sort(key=lambda n: (-n["nota"],
                                      0 if scraper.es_de_medio_curado(n, pais) else 1))
        self.assertEqual(puntuadas[0]["titulo"], "empleos temporales")

    def test_una_nota_mejor_sigue_ganando_aunque_no_sea_curada(self):
        """Es un desempate, no un veto."""
        pais = "Guatemala"
        puntuadas = [
            {"titulo": "curada mediocre", "nota": 2, "link": "https://agn.gt/x/"},
            {"titulo": "no curada excelente", "nota": 3,
             "link": "https://www.infobae.com/guatemala/y/"},
        ]
        puntuadas.sort(key=lambda n: (-n["nota"],
                                      0 if scraper.es_de_medio_curado(n, pais) else 1))
        self.assertEqual(puntuadas[0]["titulo"], "no curada excelente")


# ---------------------------------------------------------------------------
# 2 — MEMORIA ENTRE CORRIDAS
# ---------------------------------------------------------------------------

class TestMemoria(unittest.TestCase):
    """Caso 2: la nota de Vanguardia.cu que vuelve cada semana."""

    VANGUARDIA = ("http://www.vanguardia.cu/de-cuba/37891-actualizan-salario-"
                  "minimo-e-incrementan-escala-salarial-del-sector-presupuestado")

    def setUp(self):
        # Cada prueba con su propia base de datos, en un archivo temporal.
        self._dir = tempfile.TemporaryDirectory()
        import memoria
        self.memoria = memoria
        self._ruta_original = memoria.DB_PATH
        memoria.DB_PATH = Path(self._dir.name) / "memoria_prueba.db"
        memoria.inicializar_db()

    def tearDown(self):
        self.memoria.DB_PATH = self._ruta_original
        self._dir.cleanup()

    def test_normaliza_http_y_https_al_mismo_enlace(self):
        """La nota llegó unas veces por http y otras por https."""
        a = self.memoria.normalizar_enlace("http://www.vanguardia.cu/de-cuba/37891-x")
        b = self.memoria.normalizar_enlace("https://vanguardia.cu/de-cuba/37891-x/")
        self.assertEqual(a, b)

    def test_quita_parametros_de_seguimiento(self):
        a = self.memoria.normalizar_enlace("https://x.com/nota?utm_source=rss")
        b = self.memoria.normalizar_enlace("https://x.com/nota")
        self.assertEqual(a, b)

    def test_la_nota_de_vanguardia_esta_vetada_de_fabrica(self):
        """El veto vive en el código, así que sobrevive a un redespliegue."""
        motivo = self.memoria.motivo_para_no_publicar({"link": self.VANGUARDIA})
        self.assertIn("vetada a mano", motivo)
        self.assertIn("17 de julio", motivo)

    def test_una_noticia_nueva_se_publica(self):
        noticia = {"link": "https://diariodecuba.com/cuba/1794067210_69746.html"}
        self.assertEqual(self.memoria.motivo_para_no_publicar(noticia), "")

    def test_no_se_repite_dentro_de_la_ventana(self):
        noticia = {"link": "https://cibercuba.com/noticias/nota-nueva",
                   "titulo": "Una nota", "fecha_verificada": True}
        self.memoria.registrar_publicadas([noticia], "Cuba", hoy="2026-11-02")
        motivo = self.memoria.motivo_para_no_publicar(noticia, hoy="2026-11-09")
        self.assertIn("ya se publicó", motivo)
        self.assertIn("2026-11-02", motivo)

    def test_regenerar_el_mismo_dia_no_cuenta_como_repeticion(self):
        """
        Encontrado simulando el flujo completo: con el botón
        «Regenerar» la memoria bloqueaba lo que se acababa de publicar
        y el reporte se llenaba con las noticias peores.
        """
        noticia = {"link": "https://teletica.com/nacional/marcha-ccss",
                   "titulo": "Marcha por la CCSS", "fecha_verificada": True}
        self.memoria.registrar_publicadas([noticia], "Costa Rica", hoy="2026-11-09")
        self.assertEqual(
            self.memoria.motivo_para_no_publicar(noticia, hoy="2026-11-09"), "")

    def test_regenerar_varias_veces_no_infla_la_cuenta(self):
        """Tres regeneraciones en una tarde son UNA aparición."""
        noticia = {"link": "https://teletica.com/nacional/marcha-ccss",
                   "titulo": "Marcha por la CCSS", "fecha_verificada": False}
        for _ in range(3):
            self.memoria.registrar_publicadas(
                [noticia], "Costa Rica", hoy="2026-11-09")
        self.assertEqual(self.memoria.historial(noticia["link"])["veces"], 1)
        # Y por tanto no se la toma por reincidente al día siguiente.
        self.assertEqual(
            self.memoria.motivo_para_no_publicar(noticia, hoy="2026-11-09"), "")

    def test_pasada_la_ventana_vuelve_a_poder_publicarse(self):
        noticia = {"link": "https://cibercuba.com/noticias/nota-nueva",
                   "titulo": "Una nota", "fecha_verificada": True}
        self.memoria.registrar_publicadas([noticia], "Cuba", hoy="2026-01-02")
        self.assertEqual(
            self.memoria.motivo_para_no_publicar(noticia, hoy="2026-11-09"), "")

    def test_reincidente_sin_verificar_deja_de_publicarse(self):
        """
        El perfil exacto de la nota de julio: vuelve siempre y nunca se
        puede comprobar. Se simulan tres corridas sin verificación.
        """
        noticia = {"link": "https://ejemplo.cu/nota-fantasma",
                   "titulo": "Nota que no se deja verificar",
                   "fecha_verificada": False}
        for dia in ("2026-10-23", "2026-10-31", "2026-11-01"):
            self.memoria.registrar_publicadas([noticia], "Cuba", hoy=dia)
        motivo = self.memoria.motivo_para_no_publicar(noticia, hoy="2026-12-20")
        self.assertIn("reincidente sin verificar", motivo)

    def test_reincidente_pero_verificada_alguna_vez_no_se_bloquea(self):
        """Una noticia que sí se pudo comprobar no cae en esta regla."""
        noticia = {"link": "https://ejemplo.cu/nota-buena",
                   "titulo": "Nota comprobable", "fecha_verificada": True}
        for dia in ("2026-06-23", "2026-07-31", "2026-08-01"):
            self.memoria.registrar_publicadas([noticia], "Cuba", hoy=dia)
        motivo = self.memoria.motivo_para_no_publicar(noticia, hoy="2026-12-20")
        self.assertEqual(motivo, "")

    def test_el_veto_manual_funciona_y_se_puede_deshacer(self):
        enlace = "https://ejemplo.cu/nota-mal-fechada"
        self.memoria.vetar(enlace, "el artículo es de marzo")
        motivo = self.memoria.motivo_para_no_publicar({"link": enlace})
        self.assertIn("el artículo es de marzo", motivo)
        self.assertTrue(self.memoria.quitar_veto(enlace))
        self.assertEqual(
            self.memoria.motivo_para_no_publicar({"link": enlace}), "")

    def test_filtrar_devuelve_las_repetidas_con_forma_de_descarte(self):
        vieja = {"link": "https://ejemplo.cu/vieja", "titulo": "Vieja",
                 "fuente": "Ejemplo", "nota": 3, "fecha_verificada": True}
        nueva = {"link": "https://ejemplo.cu/nueva", "titulo": "Nueva",
                 "fuente": "Ejemplo", "nota": 3}
        self.memoria.registrar_publicadas([vieja], "Cuba", hoy="2026-11-08")
        publicables, repetidas = self.memoria.filtrar_ya_publicadas(
            [vieja, nueva], hoy="2026-11-09")
        self.assertEqual([n["titulo"] for n in publicables], ["Nueva"])
        self.assertEqual(len(repetidas), 1)
        for clave in ("titulo", "fuente", "link", "nota", "razon"):
            self.assertIn(clave, repetidas[0])

    def test_una_noticia_sin_enlace_nunca_se_bloquea(self):
        self.assertEqual(self.memoria.motivo_para_no_publicar({"link": ""}), "")

    def test_la_memoria_no_puede_costar_una_noticia(self):
        """Si la base de datos no existe ni se puede crear, se publica."""
        self.memoria.DB_PATH = Path("/ruta/que/no/existe/memoria.db")
        self.assertEqual(
            self.memoria.motivo_para_no_publicar(
                {"link": "https://ejemplo.cu/x"}), "")

    def test_los_reincidentes_se_pueden_listar(self):
        noticia = {"link": "https://ejemplo.cu/fantasma", "titulo": "Fantasma",
                   "fecha_verificada": False}
        for dia in ("2026-10-23", "2026-10-31", "2026-11-01"):
            self.memoria.registrar_publicadas([noticia], "Cuba", hoy=dia)
        lista = self.memoria.reincidentes()
        self.assertEqual(len(lista), 1)
        self.assertEqual(lista[0]["veces"], 3)


# ---------------------------------------------------------------------------
# 5 y la rúbrica — LO QUE EL PROMPT TIENE QUE DECIR
# ---------------------------------------------------------------------------

class TestRubrica(unittest.TestCase):
    """
    No se puede probar qué nota pondrá el modelo sin llamarlo, pero sí
    que la regla está escrita en el prompt. Cada una corresponde a una
    noticia real mal puntuada.
    """

    def _prompt(self, pais="República Dominicana"):
        """
        El prompt tal y como lo RECIBE el modelo, no el código fuente.
        Leer el fuente daba falsos negativos: una frase partida entre
        dos literales adyacentes ("el primer \\n empleo") existe en el
        prompt y no en ninguna línea del archivo.
        """
        capturado = {}

        def falsa_llamada(key, prompt, temperature, max_completion_tokens):
            capturado["prompt"] = prompt
            return None, "no se llamó de verdad"

        original = summarizer._llamar_groq_con_reintentos
        summarizer._llamar_groq_con_reintentos = falsa_llamada
        try:
            summarizer._puntuar_lote(
                [{"titulo": "T", "fuente": "F", "snippet": "E"}], pais, "clave")
        finally:
            summarizer._llamar_groq_con_reintentos = original
        return capturado["prompt"]

    def test_el_prompt_se_construye_y_nombra_al_pais(self):
        p = self._prompt("Haití")
        self.assertIn("Haití", p)
        self.assertIn("numero|nota|razon", p)

    def test_acceso_al_empleo_y_primer_empleo(self):
        """Caso 5b: los jóvenes dominicanos sin primer empleo, nota 1."""
        p = self._prompt()
        self.assertIn("ACCESO AL EMPLEO", p)
        self.assertIn("primer empleo", p)
        self.assertIn("desempleo juvenil", p)

    def test_suficiencia_del_salario_para_vivienda(self):
        """Caso 5a: los bajos salarios y el acceso a la vivienda, nota 1."""
        p = self._prompt()
        self.assertIn("vivienda", p)
        self.assertIn("suficiencia", p)

    def test_actos_internos_van_con_1(self):
        """Caso 1: la asamblea sindical."""
        p = self._prompt()
        self.assertIn("ACTOS INTERNOS", p)
        self.assertIn("asamblea", p)
        self.assertIn("sindicato", p)

    def test_el_suelo_de_los_comunicados_es_solo_para_el_estado(self):
        """Caso 1: «Comunicado:» en el titular no activaba nada."""
        p = self._prompt()
        self.assertIn("COMUNICADOS OFICIALES DEL ESTADO", p)
        self.assertIn("NO tiene suelo", p)

    def test_alcance_nacional_contra_local(self):
        """Caso 3: la feria de empleo de Puerto Barrios."""
        p = self._prompt()
        self.assertIn("ALCANCE", p)
        self.assertIn("nacional", p)

    def test_la_trampa_del_medio_internacional(self):
        """Caso 4: refuerzo en el prompt del filtro de código."""
        p = self._prompt()
        self.assertIn("internacional", p)

    def test_el_conflicto_es_parte_del_tema(self):
        """
        Hallazgo de los paneles de descartadas del 9-nov: tres de los
        siete descartes de Costa Rica y el de AlterPresse en Haití
        decían lo mismo —«protesta, no anuncia medida», «demanda de
        servicio, sin política concreta», «no medida concreta»—. El
        editor exigía que alguien anunciara algo.
        """
        p = self._prompt()
        self.assertIn("CONFLICTO Y EXIGENCIA", p)
        for palabra in ("huelga", "marcha", "demanda sindical", "litigio"):
            with self.subTest(palabra=palabra):
                self.assertIn(palabra, p)
        # Las razones textuales que dio el editor quedan prohibidas.
        self.assertIn("no anuncia medida", p)
        self.assertIn("sin política concreta", p)

    def test_el_acceso_al_empleo_tiene_limite(self):
        """
        La regla de acceso al empleo que escribí por la mañana se leyó
        como «lo laboral entra» y metió el colapso vial de Costa Rica,
        el tráfico de Guatemala y la falta de personal en los
        despachos dominicanos.
        """
        p = self._prompt()
        self.assertIn("EL LÍMITE de esta regla", p)
        for palabra in ("tráfico", "productividad", "encontrar personal"):
            with self.subTest(palabra=palabra):
                self.assertIn(palabra, p)

    def test_no_suponer_que_una_institucion_desconocida_es_privada(self):
        """
        El editor puntuó con 1 una nota sobre el FAES haitiano con la
        razón «probable acción de ONG, no programa estatal». El FAES
        es el Fonds d'Assistance Économique et Sociale, del Estado.
        """
        p = self._prompt()
        self.assertIn("no supongas que es", p)
        self.assertIn("ONG", p)

    def test_faes_esta_entre_los_terminos_de_haiti(self):
        self.assertIn("FAES", scraper.TERMINOS_TEMATICOS_FRANCES)


class TestPuntuacionPorTandas(unittest.TestCase):
    """Ninguna candidata se queda sin puntuar por el tope de 14."""

    def test_se_puntuan_todas_las_candidatas(self):
        llamadas = []

        def falso_lote(candidatas, pais, key):
            llamadas.append(len(candidatas))
            return {i: {"nota": 2, "razon": "ok"} for i in range(len(candidatas))}

        original_lote = summarizer._puntuar_lote
        original_espera = summarizer.ESPERA_ENTRE_LLAMADAS_SEGUNDOS
        summarizer._puntuar_lote = falso_lote
        summarizer.ESPERA_ENTRE_LLAMADAS_SEGUNDOS = 0
        try:
            candidatas = [{"titulo": f"n{i}", "snippet": "", "fuente": ""}
                          for i in range(31)]
            notas = summarizer.puntuar_candidatas(candidatas, "Cuba", "clave")
        finally:
            summarizer._puntuar_lote = original_lote
            summarizer.ESPERA_ENTRE_LLAMADAS_SEGUNDOS = original_espera

        self.assertEqual(len(notas), 31)
        self.assertEqual(sorted(notas), list(range(31)))
        self.assertEqual(llamadas, [14, 14, 3])

    def test_con_pocas_candidatas_sigue_siendo_una_sola_llamada(self):
        llamadas = []

        def falso_lote(candidatas, pais, key):
            llamadas.append(len(candidatas))
            return {i: {"nota": 3, "razon": "ok"} for i in range(len(candidatas))}

        original = summarizer._puntuar_lote
        summarizer._puntuar_lote = falso_lote
        try:
            summarizer.puntuar_candidatas(
                [{"titulo": "a"}, {"titulo": "b"}], "Cuba", "clave")
        finally:
            summarizer._puntuar_lote = original
        self.assertEqual(llamadas, [2])


class TestVerificacionNoDejaHuecos(unittest.TestCase):
    """
    Hallazgo del panel de República Dominicana (9-nov): se
    seleccionaban cinco y DESPUÉS se verificaba, así que la noticia de
    Revista Mercado —que resultó ser del 11 de septiembre, con el
    buscador dándola como «hace 11 horas»— se llevó su plaza con ella
    y el país salió con cuatro, teniendo tres aprobadas esperando.
    """

    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        import memoria
        self.memoria = memoria
        self._ruta = memoria.DB_PATH
        memoria.DB_PATH = Path(self._dir.name) / "m.db"
        memoria.inicializar_db()

        self._lote = summarizer._puntuar_lote
        self._espera = summarizer.ESPERA_ENTRE_LLAMADAS_SEGUNDOS
        self._resumir = summarizer.resumir_noticia
        self._verificar = summarizer.verificar_noticias
        summarizer.ESPERA_ENTRE_LLAMADAS_SEGUNDOS = 0
        summarizer.resumir_noticia = lambda **kw: {
            "resumen": kw["titulo"], "error_detalle": None}

    def tearDown(self):
        self.memoria.DB_PATH = self._ruta
        self._dir.cleanup()
        summarizer._puntuar_lote = self._lote
        summarizer.ESPERA_ENTRE_LLAMADAS_SEGUNDOS = self._espera
        summarizer.resumir_noticia = self._resumir
        summarizer.verificar_noticias = self._verificar

    # Titulares deliberadamente DISTINTOS entre sí. Con títulos del
    # tipo "Noticia 1", "Noticia 2" el deduplicador los fusiona —
    # comparten la única palabra significativa— y la prueba acaba
    # midiendo el deduplicador en vez de la verificación.
    TITULARES = [
        "Copagos médicos generan diferencias entre clínicas y la seguridad social",
        "El Senado aprueba la reforma del régimen contributivo de pensiones",
        "Cuántos salarios mínimos cuesta la canasta básica este trimestre",
        "Bajos salarios limitan el acceso a viviendas de los trabajadores",
        "Jóvenes sin experiencia enfrentan barreras para su primer empleo",
        "La Tesorería reporta un alza en el número de cotizantes activos",
        "Trabajadoras del hogar exigen la cobertura del seguro familiar",
        "El Ministerio de Trabajo inspecciona empresas por incumplimiento",
    ]

    def _correr(self, n_candidatas, caducada_en, n_noticias=5):
        """Simula un país con n candidatas donde una tiene fecha falsa."""
        aceptadas = [
            {"titulo": self.TITULARES[i], "fuente": "Medio",
             "link": f"https://ejemplo.do/n{i}", "snippet": "x", "fecha": "hoy"}
            for i in range(n_candidatas)
        ]
        summarizer._puntuar_lote = lambda c, p, k: {
            i: {"nota": 3, "razon": "ok"} for i in range(len(c))}

        def verificar(noticias, dias, **kw):
            ok, fuera = [], []
            for n in noticias:
                if n["link"] == f"https://ejemplo.do/n{caducada_en}":
                    fuera.append({"titulo": n["titulo"], "fuente": "",
                                  "link": n["link"], "nota": n.get("nota"),
                                  "razon": "fecha real fuera de rango"})
                else:
                    ok.append(n)
            return ok, fuera

        summarizer.verificar_noticias = verificar
        return summarizer.procesar_pais(
            "República Dominicana",
            {"aceptadas": aceptadas, "descartadas_marginales": [],
             "error": None, "ramas": []},
            "clave", n_noticias=n_noticias)

    def test_la_plaza_se_rellena_con_la_siguiente(self):
        r = self._correr(n_candidatas=8, caducada_en=2)
        self.assertEqual(len(r["noticias"]), 5,
                         "una noticia tumbada por fecha no debe dejar hueco")
        titulos = [n["titulo"] for n in r["noticias"]]
        self.assertNotIn(self.TITULARES[2], titulos)

    def test_la_caducada_aparece_en_el_panel_una_sola_vez(self):
        r = self._correr(n_candidatas=8, caducada_en=2)
        caducadas = [d for d in r["descartadas"]
                     if d["titulo"] == self.TITULARES[2]]
        self.assertEqual(len(caducadas), 1)
        self.assertIn("fuera de rango", caducadas[0]["razon"])

    def test_si_no_hay_con_que_rellenar_no_se_inventa_nada(self):
        r = self._correr(n_candidatas=3, caducada_en=1, n_noticias=5)
        self.assertEqual(len(r["noticias"]), 2)

    def test_sin_ninguna_valida_el_pais_queda_vacio_con_motivo(self):
        r = self._correr(n_candidatas=1, caducada_en=0, n_noticias=5)
        self.assertTrue(r["sin_resultados"])
        self.assertEqual(len(r["descartadas"]), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
