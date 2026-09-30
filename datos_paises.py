"""
FICHAS DE PAÍS
==============

Datos básicos de los diez países del monitoreo, para mostrar durante
la espera del reporte (unos 20 minutos).

CRITERIO DE SELECCIÓN: **solo datos que no caducan**. Nada de
presidentes, población, PIB ni cifras coyunturales: un dato obsoleto en
pantalla es peor que ningún dato, y nadie va a acordarse de actualizar
este archivo. Capitales, fronteras, sitios históricos y la institución
rectora de protección social cambian cada varias décadas, si acaso.

La institución rectora se incluye a propósito aunque no sea trivia:
mientras la app trabaja, quien mira aprende de qué habla el reporte que
está esperando.
"""

from typing import Dict, List, Optional

FICHAS: Dict[str, Dict] = {
    "Costa Rica": {
        "capital": "San José",
        "fronteras": "Nicaragua al norte y Panamá al sureste",
        "idioma": "Español",
        "moneda": "Colón costarricense",
        "sitios": [
            "Esferas de piedra del Diquís, Patrimonio Mundial de la UNESCO: "
            "más de trescientas esferas de granito casi perfectas, talladas "
            "por la cultura chibcha, cuyo propósito sigue sin explicarse",
            "Monumento Nacional Guayabo, la mayor ciudad precolombina "
            "excavada del país, con calzadas y acueductos que aún funcionan",
        ],
        "institucion": "Caja Costarricense de Seguro Social (CCSS), creada en 1941",
        "curiosidad": "Abolió el ejército en 1948 y destinó ese presupuesto "
                      "a educación y salud. Es la decisión que explica buena "
                      "parte de sus indicadores sociales.",
    },
    "Cuba": {
        "capital": "La Habana",
        "fronteras": "Ninguna: es una isla. Su único límite terrestre es la "
                     "valla de la base naval de Guantánamo, arrendada a "
                     "Estados Unidos desde 1903",
        "idioma": "Español",
        "moneda": "Peso cubano",
        "sitios": [
            "La Habana Vieja y su sistema de fortificaciones, Patrimonio "
            "Mundial: el conjunto colonial español mejor conservado de América",
            "Trinidad y el Valle de los Ingenios, donde se ven las ruinas de "
            "las plantaciones azucareras que sostuvieron la economía esclavista",
        ],
        "institucion": "Ministerio de Trabajo y Seguridad Social (MTSS)",
        "curiosidad": "Es la isla más grande del Caribe: cabe en ella todo el "
                      "resto de las Antillas Mayores junta.",
    },
    "El Salvador": {
        "capital": "San Salvador",
        "fronteras": "Guatemala al oeste y Honduras al norte y al este",
        "idioma": "Español",
        "moneda": "Dólar estadounidense, desde 2001",
        "sitios": [
            "Joya de Cerén, Patrimonio Mundial, llamada «la Pompeya de "
            "América»: una aldea maya sepultada por ceniza volcánica hacia el "
            "año 600, con las vasijas y la comida aún en su sitio",
            "Tazumal y San Andrés, centros ceremoniales mayas del valle de "
            "Zapotitán",
        ],
        "institucion": "Instituto Salvadoreño del Seguro Social (ISSS) e "
                       "Instituto Salvadoreño de Pensiones (ISP)",
        "curiosidad": "Es el país más pequeño de Centroamérica y el único sin "
                      "costa en el Caribe. Lo llaman «el país de los "
                      "volcanes»: tiene más de veinte.",
    },
    "Guatemala": {
        "capital": "Ciudad de Guatemala",
        "fronteras": "México al norte y oeste, Belice al noreste, Honduras y "
                     "El Salvador al sureste",
        "idioma": "Español, además de 22 idiomas mayas reconocidos, más el "
                  "xinca y el garífuna",
        "moneda": "Quetzal",
        "sitios": [
            "Tikal, Patrimonio Mundial mixto —natural y cultural—: una de las "
            "mayores ciudades mayas, con templos que asoman por encima de la "
            "selva del Petén",
            "La Antigua Guatemala, Patrimonio Mundial: capital colonial "
            "abandonada tras los terremotos de 1773 y conservada casi intacta",
            "Quiriguá, con las estelas de piedra más altas del mundo maya",
        ],
        "institucion": "Instituto Guatemalteco de Seguridad Social (IGSS), "
                       "creado en 1946, y el Ministerio de Desarrollo Social",
        "curiosidad": "El nombre viene del náhuatl Quauhtlemallan, «lugar "
                      "de muchos árboles». Su moneda se llama como el "
                      "quetzal, el ave que los mayas consideraban sagrada y "
                      "cuyas plumas valían más que el oro.",
    },
    "Haití": {
        "capital": "Puerto Príncipe",
        "fronteras": "República Dominicana. Comparten La Española, la segunda "
                     "isla más grande del Caribe",
        "idioma": "Francés y criollo haitiano, ambos oficiales",
        "moneda": "Gourde",
        "sitios": [
            "La Citadelle Laferrière y el palacio de Sans-Souci, Patrimonio "
            "Mundial: la mayor fortaleza del hemisferio, levantada tras la "
            "independencia para resistir un regreso de los franceses que "
            "nunca llegó",
            "Bassin Zim y las cuevas de Dondon, con petroglifos taínos "
            "anteriores a la llegada europea",
        ],
        "institucion": "Office National d'Assurance Vieillesse (ONA) y OFATMA, "
                       "bajo el Ministerio de Asuntos Sociales y del Trabajo",
        "curiosidad": "En 1804 se convirtió en la primera república negra "
                      "independiente del mundo y en el primer país "
                      "latinoamericano en independizarse, tras la única "
                      "revuelta de personas esclavizadas que fundó un Estado.",
    },
    "Honduras": {
        "capital": "Tegucigalpa",
        "fronteras": "Guatemala al oeste, El Salvador al suroeste y Nicaragua "
                     "al sureste",
        "idioma": "Español, además de lenguas como el garífuna y el misquito",
        "moneda": "Lempira",
        "sitios": [
            "Copán, Patrimonio Mundial: la ciudad maya con la escultura más "
            "refinada del periodo clásico y la Escalinata Jeroglífica, el "
            "texto maya más largo que se conserva",
            "Fortaleza de San Fernando de Omoa, la mayor construcción militar "
            "española de Centroamérica",
        ],
        "institucion": "Instituto Hondureño de Seguridad Social (IHSS) y la "
                       "Secretaría de Desarrollo Social",
        "curiosidad": "La moneda, el lempira, lleva el nombre del cacique "
                      "lenca que resistió a los conquistadores en el siglo XVI.",
    },
    "México": {
        "capital": "Ciudad de México",
        "fronteras": "Estados Unidos al norte; Guatemala y Belice al sureste",
        "idioma": "Español, junto con 68 lenguas indígenas reconocidas como "
                  "lenguas nacionales",
        "moneda": "Peso mexicano",
        "sitios": [
            "Teotihuacán, la mayor ciudad de la América precolombina en su "
            "momento: ya estaba en ruinas y era un lugar de peregrinación "
            "cuando llegaron los mexicas",
            "Chichén Itzá y Palenque, dos de las ciudades mayas mejor "
            "conservadas",
            "Monte Albán, capital zapoteca sobre una montaña aplanada a mano",
        ],
        "institucion": "Instituto Mexicano del Seguro Social (IMSS), creado en "
                       "1943, el ISSSTE y la Secretaría de Bienestar",
        "curiosidad": "Es el país de América con más sitios inscritos en la "
                      "lista del Patrimonio Mundial de la UNESCO.",
    },
    "Nicaragua": {
        "capital": "Managua",
        "fronteras": "Honduras al norte y Costa Rica al sur",
        "idioma": "Español, además del misquito y el criollo en la costa Caribe",
        "moneda": "Córdoba",
        "sitios": [
            "Ruinas de León Viejo, Patrimonio Mundial: la primera ciudad "
            "española de la zona, sepultada por las cenizas del volcán "
            "Momotombo y abandonada en 1610",
            "Isla de Ometepe, formada por dos volcanes dentro de un lago, con "
            "petroglifos de hace más de dos mil años",
        ],
        "institucion": "Instituto Nicaragüense de Seguridad Social (INSS) y el "
                       "Ministerio de la Familia",
        "curiosidad": "Es el país más extenso de Centroamérica, y su lago "
                      "Cocibolca es el único del mundo donde viven tiburones "
                      "toro, que remontan el río San Juan desde el mar.",
    },
    "Panamá": {
        "capital": "Ciudad de Panamá",
        "fronteras": "Costa Rica al oeste y Colombia al este",
        "idioma": "Español",
        "moneda": "Balboa, a la par con el dólar estadounidense, que circula "
                  "como billete",
        "sitios": [
            "Panamá Viejo y el Casco Antiguo, Patrimonio Mundial: la primera "
            "ciudad europea en la costa del Pacífico americano, arrasada por "
            "el pirata Henry Morgan en 1671",
            "Portobelo y San Lorenzo, las fortificaciones que protegían la "
            "ruta por la que salía la plata del Perú hacia España",
        ],
        "institucion": "Caja de Seguro Social (CSS) y el Ministerio de "
                       "Desarrollo Social (MIDES)",
        "curiosidad": "Por la curva del istmo, el canal corre de noroeste a "
                      "sureste: quien lo cruza hacia el Pacífico viaja hacia "
                      "el este, al revés de lo que dice la intuición.",
    },
    "República Dominicana": {
        "capital": "Santo Domingo",
        "fronteras": "Haití. Comparten La Española",
        "idioma": "Español",
        "moneda": "Peso dominicano",
        "sitios": [
            "Ciudad Colonial de Santo Domingo, Patrimonio Mundial: el primer "
            "asentamiento europeo permanente de América, con la primera "
            "catedral, la primera universidad y el primer hospital del "
            "continente",
            "Parque Nacional Los Haitises, con cuevas que conservan "
            "pictografías taínas",
        ],
        "institucion": "Consejo Nacional de Seguridad Social (CNSS), el "
                       "Gabinete de Política Social y el programa Supérate",
        "curiosidad": "El Pico Duarte, de más de tres mil metros, es la "
                      "montaña más alta de todo el Caribe insular.",
    },
}


def ficha(pais: str) -> Optional[Dict]:
    """Ficha de un país, o None si no está."""
    return FICHAS.get(pais)


def paises_con_ficha() -> List[str]:
    return list(FICHAS)
