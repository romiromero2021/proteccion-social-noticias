"""
LO QUE ENSEÑARON LOS PANELES DE DESCARTADAS DEL 10-nov-2026
===========================================================
Tres paneles, tres diagnósticos distintos. Vale la pena anotarlo
porque la conclusión fácil —«las reglas nuevas cortan demasiado»— era
falsa en dos de los tres países.

  CUBA      7 candidatas, 4 descartes, los 4 correctos.
  GUATEMALA 11 candidatas, 9 descartes, los 9 correctos. Cinco de las
            once venían de igssgt.org o guatemala.gob.gt.
  HONDURAS  10 candidatas, 8 descartes, TRES mal.

En Cuba y Guatemala el editor acertó en todo: esos países salieron
cortos por lo que la búsqueda trae, no por cómo se juzga. En Honduras
el editor tiró tres noticias que la propia rúbrica nombra:

  1. «SEDESOL agilizará firma de convenios de becas con nueva
     herramienta digital» — razón: "Becas, educación no es protección
     social". La rúbrica lista las becas entre lo que SÍ entra.
  2. «Honduras prepara envío de 2,000 trabajadores a España» — razón:
     "Envío de trabajadores al exterior, no protección".
  3. «Honduras buscará enviar trabajadores agrícolas a España» —
     razón: "Programa envío trabajadores agrícolas, no protección
     directa". La rúbrica lista "migración laboral y programas de
     empleo temporal".

La prueba de que es incoherencia y no criterio: en LA MISMA CORRIDA,
Guatemala publicó «Más de 6 mil guatemaltecos acceden a empleos
temporales fuera del país». La misma categoría, decisiones opuestas.

El patrón de fondo: el editor lee el título del bloque —"EDUCACIÓN Y
SALUD — el límite", "EL LÍMITE de esta regla"— y se queda con la
exclusión; la lista de lo que SÍ entra, que viene después, no le llega.
Por eso los arreglos citan ahora la razón textual que dio el editor,
que es lo que funcionó con CONFLICTO Y EXIGENCIA.

Y una regla que pidió la analista mirando el reporte: el caso
individual no es noticia.

    python3 evals/test_paneles_10nov.py
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import summarizer  # noqa: E402


def _prompt(pais="Honduras"):
    capturado = {}

    def falsa(key, prompt, temperature, max_completion_tokens):
        capturado["p"] = prompt
        return None, "no se llamó"

    original = summarizer._llamar_groq_con_reintentos
    summarizer._llamar_groq_con_reintentos = falsa
    try:
        summarizer._puntuar_lote(
            [{"titulo": "T", "fuente": "F", "snippet": "E"}], pais, "k")
    finally:
        summarizer._llamar_groq_con_reintentos = original
    return capturado["p"]


class TestLasBecasSonProteccionSocial(unittest.TestCase):

    def test_la_razon_que_dio_el_editor_queda_prohibida(self):
        self.assertIn("«Becas, educación no es protección social» NO es "
                      "un motivo válido de descarte", _prompt())

    def test_dice_por_que_la_beca_no_es_educacion(self):
        p = _prompt()
        self.assertIn("ventanilla", p)
        self.assertIn("comedor escolar", p)
        self.assertIn("transferencia condicionada", p)

    def test_el_ministerio_de_desarrollo_social_zanja_la_duda(self):
        p = _prompt()
        for sigla in ("SEDESOL", "MIDES", "MIDIS"):
            with self.subTest(sigla=sigla):
                self.assertIn(sigla, p)

    def test_no_se_llevo_consigo_el_limite_de_educacion(self):
        """
        El arreglo no puede convertir el boletín en uno de educación:
        el presupuesto educativo y la rentrée siguen fuera.
        """
        p = _prompt()
        self.assertIn("presupuesto educativo", p)
        self.assertIn("rentrée escolar", p)


class TestTrabajoEnElExterior(unittest.TestCase):

    def test_las_dos_razones_textuales_quedan_prohibidas(self):
        p = _prompt()
        self.assertIn("Envío de trabajadores al exterior, no protección", p)
        self.assertIn("no protección directa", p)

    def test_nombra_lo_que_entra(self):
        p = _prompt()
        bloque = p.split("LOS PROGRAMAS DE TRABAJO EN EL EXTERIOR")[1][:800]
        for palabra in ("convenios", "agrícola", "temporal"):
            with self.subTest(palabra=palabra):
                self.assertIn(palabra, bloque)

    def test_distingue_la_gestion_consular_que_sigue_fuera(self):
        """
        Sin este límite, el arreglo mete las deportaciones y la visita
        de la embajada a Segovia, que Guatemala descartó bien.
        """
        p = _prompt()
        bloque = p.split("LOS PROGRAMAS DE TRABAJO EN EL EXTERIOR")[1][:800]
        for palabra in ("deportaciones", "visados", "embajada"):
            with self.subTest(palabra=palabra):
                self.assertIn(palabra, bloque)


class TestElCasoIndividual(unittest.TestCase):

    def test_la_regla_existe_con_sus_dos_casos(self):
        p = _prompt("Guatemala")
        self.assertIn("EL CASO INDIVIDUAL NO ES NOTICIA", p)
        self.assertIn("Kleiderson", p)
        self.assertIn("Don Juanito", p)

    def test_dice_que_vale_aunque_el_programa_sea_del_tema(self):
        """
        Es la parte que importa: la beca entra (regla de arriba) pero
        la historia de un becario no. Sin esta frase, las dos reglas
        nuevas se contradicen.
        """
        p = _prompt("Guatemala")
        bloque = p.split("EL CASO INDIVIDUAL NO ES NOTICIA")[1][:600]
        self.assertIn("aunque el programa", bloque)

    def test_deja_la_puerta_abierta_al_caso_con_cifra(self):
        p = _prompt("Guatemala")
        bloque = p.split("EL CASO INDIVIDUAL NO ES NOTICIA")[1][:600]
        self.assertIn("40 000 estudiantes", bloque)


class TestLasReglasNoSePisan(unittest.TestCase):
    """
    Cada regla nueva de hoy entró para admitir o excluir algo. Ninguna
    puede haber borrado a la anterior: ya pasó dos veces en dos días.
    """

    def test_siguen_en_pie_todas_las_reglas_del_dia(self):
        p = _prompt()
        for marca in ("LA MISMA FUENTE DE DATOS TAMBIÉN ES REPETICIÓN",
                      "EL SUELO NO CUBRE LA AUTOPROMOCIÓN",
                      "SALUD Y CONDICIONES DE TRABAJO",
                      "La productividad SOLA",
                      "EL CASO INDIVIDUAL NO ES NOTICIA",
                      "LOS PROGRAMAS DE TRABAJO EN EL EXTERIOR ENTRAN",
                      "CONFLICTO Y EXIGENCIA",
                      "LA PREGUNTA QUE DECIDE",
                      "EL LÍMITE de esta regla",
                      "Puerto Barrios"):
            with self.subTest(marca=marca):
                self.assertIn(marca, p)

    def test_el_traslado_sigue_fuera_en_las_dos_reglas(self):
        """Guatemala descartó bien las dos notas de tráfico. Que siga."""
        p = _prompt("Guatemala")
        limite = p.split("EL LÍMITE de esta regla")[1].split("SALUD Y")[0]
        self.assertIn("tráfico", limite)
        salud = p.split("SALUD Y CONDICIONES DE TRABAJO")[1].split("CONFLICTO Y")[0]
        self.assertIn("traslado", salud)

    def test_el_prompt_no_se_desbocó(self):
        """
        Cada regla cuesta fichas en CADA llamada de puntuación, y el
        límite de Groq es por minuto. Si esto se dispara, la corrida
        deja de caber.
        """
        largo = len(_prompt())
        self.assertLess(
            largo, 17000,
            f"el prompt del editor va por {largo} caracteres: toca "
            f"condensar antes de seguir agregando reglas")


if __name__ == "__main__":
    unittest.main(verbosity=2)
