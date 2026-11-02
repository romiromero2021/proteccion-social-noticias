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
        "curiosidad": "Es el país más poblado de Centroamérica y el de mayor "
                      "proporción de población indígena de la subregión.",
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


FICHAS_EN: Dict[str, Dict] = {
    "Costa Rica": {
        "capital": "San José",
        "fronteras": "Nicaragua to the north and Panama to the southeast",
        "idioma": "Spanish",
        "moneda": "Costa Rican colón",
        "sitios": [
            "The Diquís stone spheres, a UNESCO World Heritage Site: more "
            "than three hundred near-perfect granite spheres carved by the "
            "Chibchan culture, whose purpose remains unexplained",
            "Guayabo National Monument, the largest pre-Columbian city "
            "excavated in the country, with causeways and aqueducts that "
            "still work",
        ],
        "institucion": "Costa Rican Social Security Fund (CCSS), founded in 1941",
        "curiosidad": "It abolished its army in 1948 and redirected that "
                      "budget to education and health. That single decision "
                      "explains much of its social performance.",
    },
    "Cuba": {
        "capital": "Havana",
        "fronteras": "None: it is an island. Its only land boundary is the "
                     "fence around the Guantánamo naval base, leased to the "
                     "United States since 1903",
        "idioma": "Spanish",
        "moneda": "Cuban peso",
        "sitios": [
            "Old Havana and its fortifications, a World Heritage Site: the "
            "best-preserved Spanish colonial ensemble in the Americas",
            "Trinidad and the Valley of the Sugar Mills, where the ruins of "
            "the plantations that sustained the slave economy still stand",
        ],
        "institucion": "Ministry of Labour and Social Security (MTSS)",
        "curiosidad": "It is the largest island in the Caribbean: all the "
                      "other Greater Antilles together would fit inside it.",
    },
    "El Salvador": {
        "capital": "San Salvador",
        "fronteras": "Guatemala to the west, Honduras to the north and east",
        "idioma": "Spanish",
        "moneda": "United States dollar, since 2001",
        "sitios": [
            "Joya de Cerén, a World Heritage Site known as «the Pompeii of "
            "the Americas»: a Maya village buried by volcanic ash around the "
            "year 600, with the pots and the food still in place",
            "Tazumal and San Andrés, Maya ceremonial centres in the "
            "Zapotitán valley",
        ],
        "institucion": "Salvadoran Social Security Institute (ISSS) and "
                       "Salvadoran Pension Institute (ISP)",
        "curiosidad": "It is the smallest country in Central America and the "
                      "only one with no Caribbean coast. It is called «the "
                      "land of volcanoes»: it has more than twenty.",
    },
    "Guatemala": {
        "capital": "Guatemala City",
        "fronteras": "Mexico to the north and west, Belize to the northeast, "
                     "Honduras and El Salvador to the southeast",
        "idioma": "Spanish, alongside 22 recognised Mayan languages, plus "
                  "Xinca and Garifuna",
        "moneda": "Quetzal",
        "sitios": [
            "Tikal, a mixed World Heritage Site — natural and cultural: one "
            "of the largest Maya cities, with temples rising above the Petén "
            "rainforest",
            "Antigua Guatemala, a World Heritage Site: a colonial capital "
            "abandoned after the 1773 earthquakes and preserved almost intact",
            "Quiriguá, home to the tallest carved stelae in the Maya world",
        ],
        "institucion": "Guatemalan Social Security Institute (IGSS), founded "
                       "in 1946, and the Ministry of Social Development",
        "curiosidad": "The name comes from the Nahuatl Quauhtlemallan, "
                      "«place of many trees». Its currency is named after "
                      "the quetzal, the bird the Maya held sacred and whose "
                      "feathers were worth more than gold.",
    },
    "Haití": {
        "capital": "Port-au-Prince",
        "fronteras": "The Dominican Republic. They share Hispaniola, the "
                     "second largest island in the Caribbean",
        "idioma": "French and Haitian Creole, both official",
        "moneda": "Gourde",
        "sitios": [
            "The Citadelle Laferrière and the Sans-Souci palace, a World "
            "Heritage Site: the largest fortress in the hemisphere, built "
            "after independence to resist a French return that never came",
            "Bassin Zim and the caves of Dondon, with Taíno petroglyphs "
            "predating the European arrival",
        ],
        "institucion": "Office National d'Assurance Vieillesse (ONA) and "
                       "OFATMA, under the Ministry of Social Affairs and Labour",
        "curiosidad": "In 1804 it became the world's first independent Black "
                      "republic and the first Latin American country to win "
                      "independence, after the only revolt of enslaved people "
                      "that founded a state.",
    },
    "Honduras": {
        "capital": "Tegucigalpa",
        "fronteras": "Guatemala to the west, El Salvador to the southwest "
                     "and Nicaragua to the southeast",
        "idioma": "Spanish, alongside languages such as Garifuna and Miskito",
        "moneda": "Lempira",
        "sitios": [
            "Copán, a World Heritage Site: the Maya city with the finest "
            "sculpture of the Classic period and the Hieroglyphic Stairway, "
            "the longest surviving Maya text",
            "The fortress of San Fernando de Omoa, the largest Spanish "
            "military structure in Central America",
        ],
        "institucion": "Honduran Social Security Institute (IHSS) and the "
                       "Secretariat of Social Development",
        "curiosidad": "The currency, the lempira, is named after the Lenca "
                      "chief who resisted the conquistadors in the 16th century.",
    },
    "México": {
        "capital": "Mexico City",
        "fronteras": "The United States to the north; Guatemala and Belize "
                     "to the southeast",
        "idioma": "Spanish, together with 68 Indigenous languages recognised "
                  "as national languages",
        "moneda": "Mexican peso",
        "sitios": [
            "Teotihuacan, the largest city in pre-Columbian America in its "
            "day: it was already in ruins and a place of pilgrimage when the "
            "Mexica arrived",
            "Chichén Itzá and Palenque, two of the best-preserved Maya cities",
            "Monte Albán, the Zapotec capital on a mountain levelled by hand",
        ],
        "institucion": "Mexican Social Security Institute (IMSS), founded in "
                       "1943, the ISSSTE and the Ministry of Welfare",
        "curiosidad": "It is the country in the Americas with the most sites "
                      "inscribed on the UNESCO World Heritage List.",
    },
    "Nicaragua": {
        "capital": "Managua",
        "fronteras": "Honduras to the north and Costa Rica to the south",
        "idioma": "Spanish, alongside Miskito and Creole on the Caribbean coast",
        "moneda": "Córdoba",
        "sitios": [
            "The ruins of León Viejo, a World Heritage Site: the first "
            "Spanish city in the area, buried by ash from the Momotombo "
            "volcano and abandoned in 1610",
            "Ometepe Island, formed by two volcanoes inside a lake, with "
            "petroglyphs more than two thousand years old",
        ],
        "institucion": "Nicaraguan Social Security Institute (INSS) and the "
                       "Ministry of the Family",
        "curiosidad": "It is the largest country in Central America, and its "
                      "Lake Cocibolca is the only lake in the world inhabited "
                      "by bull sharks, which swim up the San Juan river from "
                      "the sea.",
    },
    "Panamá": {
        "capital": "Panama City",
        "fronteras": "Costa Rica to the west and Colombia to the east",
        "idioma": "Spanish",
        "moneda": "Balboa, at par with the United States dollar, which "
                  "circulates as banknotes",
        "sitios": [
            "Panamá Viejo and the Casco Antiguo, a World Heritage Site: the "
            "first European city on the American Pacific coast, sacked by "
            "the privateer Henry Morgan in 1671",
            "Portobelo and San Lorenzo, the fortifications that guarded the "
            "route by which Peruvian silver left for Spain",
        ],
        "institucion": "Social Security Fund (CSS) and the Ministry of "
                       "Social Development (MIDES)",
        "curiosidad": "Because of the curve of the isthmus, the canal runs "
                      "northwest to southeast: crossing it towards the "
                      "Pacific means travelling east, the opposite of what "
                      "intuition suggests.",
    },
    "República Dominicana": {
        "capital": "Santo Domingo",
        "fronteras": "Haiti. They share Hispaniola",
        "idioma": "Spanish",
        "moneda": "Dominican peso",
        "sitios": [
            "The Colonial City of Santo Domingo, a World Heritage Site: the "
            "first permanent European settlement in the Americas, with the "
            "continent's first cathedral, first university and first hospital",
            "Los Haitises National Park, whose caves preserve Taíno "
            "pictographs",
        ],
        "institucion": "National Social Security Council (CNSS), the Social "
                       "Policy Cabinet and the Supérate programme",
        "curiosidad": "Pico Duarte, over three thousand metres high, is the "
                      "tallest mountain in the entire insular Caribbean.",
    },
}

# Nombre de cada país PARA MOSTRAR. La clave sigue siendo siempre el
# nombre en español: es la que usan SITIOS_PAIS, el caché, el scraper y
# el documento Word. Traducir la clave rompería las tres cosas.
NOMBRE_PAIS: Dict[str, Dict[str, str]] = {
    "Costa Rica": {"es": "Costa Rica", "en": "Costa Rica"},
    "Cuba": {"es": "Cuba", "en": "Cuba"},
    "El Salvador": {"es": "El Salvador", "en": "El Salvador"},
    "Guatemala": {"es": "Guatemala", "en": "Guatemala"},
    "Haití": {"es": "Haití", "en": "Haiti"},
    "Honduras": {"es": "Honduras", "en": "Honduras"},
    "México": {"es": "México", "en": "Mexico"},
    "Nicaragua": {"es": "Nicaragua", "en": "Nicaragua"},
    "Panamá": {"es": "Panamá", "en": "Panama"},
    "República Dominicana": {"es": "República Dominicana",
                             "en": "Dominican Republic"},
}

_FICHAS_POR_IDIOMA = {"es": FICHAS, "en": FICHAS_EN}


def ficha(pais: str, idioma: str = "es") -> Optional[Dict]:
    """Ficha de un país en el idioma pedido, o None si no está."""
    return _FICHAS_POR_IDIOMA.get(idioma, FICHAS).get(pais)


def nombre_pais(pais: str, idioma: str = "es") -> str:
    """
    Nombre del país para MOSTRAR en pantalla.

    Solo para la vista. La clave interna no cambia nunca: si se
    tradujera, el caché buscaría "Mexico" donde guardó "México", y
    SITIOS_PAIS y el documento Word dejarían de encontrar el país.
    """
    return NOMBRE_PAIS.get(pais, {}).get(idioma, pais)


def paises_con_ficha() -> List[str]:
    return list(FICHAS)
