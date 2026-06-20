"""Static country -> coordinate lookup used to place artist origins on the map.

No external service exposes decimal coordinates for an artist's origin: the data
clients only give a country *name* (TheAudioDB ``strCountry``, full names) or an
ISO alpha-2 *code* (MusicBrainz ``country``). This module converts either form
into approximate coordinates (country centroid / capital) so the geography map
can render without asking the LLM to invent coordinates.

``resolve_coordinates`` is tolerant: it accepts ISO codes, full names and common
aliases ("USA", "UK", "England", ...), and returns ``(None, None)`` when the
origin is unknown so the caller can simply skip that marker.
"""
from __future__ import annotations

# ISO alpha-2 code -> (latitude, longitude). Approximate country centroids.
COUNTRY_COORDS: dict[str, tuple[float, float]] = {
    "AR": (-38.42, -63.62),
    "AT": (47.52, 14.55),
    "AU": (-25.27, 133.78),
    "BD": (23.68, 90.36),
    "BE": (50.50, 4.47),
    "BG": (42.73, 25.49),
    "BR": (-14.24, -51.93),
    "CA": (56.13, -106.35),
    "CH": (46.82, 8.23),
    "CL": (-35.68, -71.54),
    "CN": (35.86, 104.20),
    "CO": (4.57, -74.30),
    "CR": (9.75, -83.75),
    "CU": (21.52, -77.78),
    "CZ": (49.82, 15.47),
    "DE": (51.17, 10.45),
    "DK": (56.26, 9.50),
    "DO": (18.74, -70.16),
    "DZ": (28.03, 1.66),
    "EC": (-1.83, -78.18),
    "EE": (58.60, 25.01),
    "EG": (26.82, 30.80),
    "ES": (40.46, -3.75),
    "ET": (9.15, 40.49),
    "FI": (61.92, 25.75),
    "FR": (46.23, 2.21),
    "GB": (55.38, -3.44),
    "GR": (39.07, 21.82),
    "HR": (45.10, 15.20),
    "HU": (47.16, 19.50),
    "ID": (-0.79, 113.92),
    "IE": (53.41, -8.24),
    "IL": (31.05, 34.85),
    "IN": (20.59, 78.96),
    "IS": (64.96, -19.02),
    "IT": (41.87, 12.57),
    "JM": (18.11, -77.30),
    "JP": (36.20, 138.25),
    "KE": (-0.02, 37.91),
    "KR": (35.91, 127.77),
    "LB": (33.85, 35.86),
    "LT": (55.17, 23.88),
    "LU": (49.82, 6.13),
    "LV": (56.88, 24.60),
    "MA": (31.79, -7.09),
    "MX": (23.63, -102.55),
    "MY": (4.21, 101.98),
    "NG": (9.08, 8.68),
    "NL": (52.13, 5.29),
    "NO": (60.47, 8.47),
    "NZ": (-40.90, 174.89),
    "PA": (8.54, -80.78),
    "PE": (-9.19, -75.02),
    "PH": (12.88, 121.77),
    "PK": (30.38, 69.35),
    "PL": (51.92, 19.15),
    "PR": (18.22, -66.59),
    "PT": (39.40, -8.22),
    "RO": (45.94, 24.97),
    "RS": (44.02, 21.01),
    "RU": (61.52, 105.32),
    "SE": (60.13, 18.64),
    "SG": (1.35, 103.82),
    "SI": (46.15, 14.99),
    "SK": (48.67, 19.70),
    "TH": (15.87, 100.99),
    "TR": (38.96, 35.24),
    "TW": (23.70, 120.96),
    "UA": (48.38, 31.17),
    "US": (37.09, -95.71),
    "UY": (-32.52, -55.77),
    "VE": (6.42, -66.59),
    "VN": (14.06, 108.28),
    "ZA": (-30.56, 22.94),
}

# Lowercased country name / alias -> ISO alpha-2 code.
NAME_TO_ISO: dict[str, str] = {
    "argentina": "AR",
    "austria": "AT",
    "australia": "AU",
    "bangladesh": "BD",
    "belgium": "BE",
    "bulgaria": "BG",
    "brazil": "BR",
    "brasil": "BR",
    "canada": "CA",
    "switzerland": "CH",
    "chile": "CL",
    "china": "CN",
    "colombia": "CO",
    "costa rica": "CR",
    "cuba": "CU",
    "czech republic": "CZ",
    "czechia": "CZ",
    "germany": "DE",
    "deutschland": "DE",
    "denmark": "DK",
    "dominican republic": "DO",
    "algeria": "DZ",
    "ecuador": "EC",
    "estonia": "EE",
    "egypt": "EG",
    "spain": "ES",
    "españa": "ES",
    "ethiopia": "ET",
    "finland": "FI",
    "france": "FR",
    "united kingdom": "GB",
    "uk": "GB",
    "great britain": "GB",
    "england": "GB",
    "scotland": "GB",
    "wales": "GB",
    "northern ireland": "GB",
    "greece": "GR",
    "croatia": "HR",
    "hungary": "HU",
    "indonesia": "ID",
    "ireland": "IE",
    "israel": "IL",
    "india": "IN",
    "iceland": "IS",
    "italy": "IT",
    "italia": "IT",
    "jamaica": "JM",
    "japan": "JP",
    "kenya": "KE",
    "south korea": "KR",
    "korea": "KR",
    "korea, republic of": "KR",
    "lebanon": "LB",
    "lithuania": "LT",
    "luxembourg": "LU",
    "latvia": "LV",
    "morocco": "MA",
    "mexico": "MX",
    "méxico": "MX",
    "malaysia": "MY",
    "nigeria": "NG",
    "netherlands": "NL",
    "the netherlands": "NL",
    "holland": "NL",
    "norway": "NO",
    "new zealand": "NZ",
    "panama": "PA",
    "peru": "PE",
    "philippines": "PH",
    "pakistan": "PK",
    "poland": "PL",
    "puerto rico": "PR",
    "portugal": "PT",
    "romania": "RO",
    "serbia": "RS",
    "russia": "RU",
    "russian federation": "RU",
    "sweden": "SE",
    "singapore": "SG",
    "slovenia": "SI",
    "slovakia": "SK",
    "thailand": "TH",
    "turkey": "TR",
    "türkiye": "TR",
    "taiwan": "TW",
    "ukraine": "UA",
    "united states": "US",
    "united states of america": "US",
    "usa": "US",
    "u.s.a.": "US",
    "u.s.": "US",
    "america": "US",
    "uruguay": "UY",
    "venezuela": "VE",
    "vietnam": "VN",
    "viet nam": "VN",
    "south africa": "ZA",
}


# ISO alpha-2 code -> readable English country name. Usato per mostrare un'etichetta
# leggibile a livello PAESE quando l'unica origine disponibile e' un codice ISO (es.
# MusicBrainz restituisce "GB", non "United Kingdom"). I nomi provengono da Natural
# Earth (la stessa fonte del GeoJSON usato per colorare gli stati sulla mappa), con
# alcuni ritocchi per le forme piu' comuni.
ISO_TO_NAME: dict[str, str] = {
    "AE": "United Arab Emirates",
    "AF": "Afghanistan",
    "AL": "Albania",
    "AM": "Armenia",
    "AO": "Angola",
    "AR": "Argentina",
    "AT": "Austria",
    "AU": "Australia",
    "AZ": "Azerbaijan",
    "BA": "Bosnia and Herzegovina",
    "BD": "Bangladesh",
    "BE": "Belgium",
    "BF": "Burkina Faso",
    "BG": "Bulgaria",
    "BI": "Burundi",
    "BJ": "Benin",
    "BN": "Brunei",
    "BO": "Bolivia",
    "BR": "Brazil",
    "BS": "Bahamas",
    "BT": "Bhutan",
    "BW": "Botswana",
    "BY": "Belarus",
    "BZ": "Belize",
    "CA": "Canada",
    "CD": "Dem. Rep. Congo",
    "CF": "Central African Rep.",
    "CG": "Congo",
    "CH": "Switzerland",
    "CI": "Côte d'Ivoire",
    "CL": "Chile",
    "CM": "Cameroon",
    "CN": "China",
    "CO": "Colombia",
    "CR": "Costa Rica",
    "CU": "Cuba",
    "CY": "Cyprus",
    "CZ": "Czechia",
    "DE": "Germany",
    "DJ": "Djibouti",
    "DK": "Denmark",
    "DO": "Dominican Republic",
    "DZ": "Algeria",
    "EC": "Ecuador",
    "EE": "Estonia",
    "EG": "Egypt",
    "ER": "Eritrea",
    "ES": "Spain",
    "ET": "Ethiopia",
    "FI": "Finland",
    "FJ": "Fiji",
    "FR": "France",
    "GA": "Gabon",
    "GB": "United Kingdom",
    "GE": "Georgia",
    "GH": "Ghana",
    "GL": "Greenland",
    "GM": "Gambia",
    "GN": "Guinea",
    "GQ": "Eq. Guinea",
    "GR": "Greece",
    "GT": "Guatemala",
    "GW": "Guinea-Bissau",
    "GY": "Guyana",
    "HN": "Honduras",
    "HR": "Croatia",
    "HT": "Haiti",
    "HU": "Hungary",
    "ID": "Indonesia",
    "IE": "Ireland",
    "IL": "Israel",
    "IN": "India",
    "IQ": "Iraq",
    "IR": "Iran",
    "IS": "Iceland",
    "IT": "Italy",
    "JM": "Jamaica",
    "JO": "Jordan",
    "JP": "Japan",
    "KE": "Kenya",
    "KG": "Kyrgyzstan",
    "KH": "Cambodia",
    "KP": "North Korea",
    "KR": "South Korea",
    "KW": "Kuwait",
    "KZ": "Kazakhstan",
    "LA": "Laos",
    "LB": "Lebanon",
    "LK": "Sri Lanka",
    "LR": "Liberia",
    "LS": "Lesotho",
    "LT": "Lithuania",
    "LU": "Luxembourg",
    "LV": "Latvia",
    "LY": "Libya",
    "MA": "Morocco",
    "MD": "Moldova",
    "ME": "Montenegro",
    "MG": "Madagascar",
    "MK": "North Macedonia",
    "ML": "Mali",
    "MM": "Myanmar",
    "MN": "Mongolia",
    "MR": "Mauritania",
    "MW": "Malawi",
    "MX": "Mexico",
    "MY": "Malaysia",
    "MZ": "Mozambique",
    "NA": "Namibia",
    "NC": "New Caledonia",
    "NE": "Niger",
    "NG": "Nigeria",
    "NI": "Nicaragua",
    "NL": "Netherlands",
    "NO": "Norway",
    "NP": "Nepal",
    "NZ": "New Zealand",
    "OM": "Oman",
    "PA": "Panama",
    "PE": "Peru",
    "PG": "Papua New Guinea",
    "PH": "Philippines",
    "PK": "Pakistan",
    "PL": "Poland",
    "PR": "Puerto Rico",
    "PS": "Palestine",
    "PT": "Portugal",
    "PY": "Paraguay",
    "QA": "Qatar",
    "RO": "Romania",
    "RS": "Serbia",
    "RU": "Russia",
    "RW": "Rwanda",
    "SA": "Saudi Arabia",
    "SD": "Sudan",
    "SE": "Sweden",
    "SI": "Slovenia",
    "SK": "Slovakia",
    "SL": "Sierra Leone",
    "SN": "Senegal",
    "SO": "Somalia",
    "SR": "Suriname",
    "SS": "S. Sudan",
    "SV": "El Salvador",
    "SY": "Syria",
    "SZ": "eSwatini",
    "TD": "Chad",
    "TG": "Togo",
    "TH": "Thailand",
    "TJ": "Tajikistan",
    "TL": "Timor-Leste",
    "TM": "Turkmenistan",
    "TN": "Tunisia",
    "TR": "Turkey",
    "TT": "Trinidad and Tobago",
    "TW": "Taiwan",
    "TZ": "Tanzania",
    "UA": "Ukraine",
    "UG": "Uganda",
    "US": "United States",
    "UY": "Uruguay",
    "UZ": "Uzbekistan",
    "VE": "Venezuela",
    "VN": "Vietnam",
    "VU": "Vanuatu",
    "XK": "Kosovo",
    "YE": "Yemen",
    "ZA": "South Africa",
    "ZM": "Zambia",
    "ZW": "Zimbabwe",
}


def country_name(origin: str) -> str:
    """Restituisce un nome di paese leggibile a partire da un codice ISO2/nome/alias.

    Se l'input e' gia' un nome leggibile (non un codice ISO2 noto) viene restituito
    invariato. Serve a evitare che sulla mappa compaia "GB" invece di "United Kingdom".
    """
    if not origin:
        return ""
    key = origin.strip()
    if not key:
        return ""
    code = key.upper()
    if len(code) == 2 and code in ISO_TO_NAME:
        return ISO_TO_NAME[code]
    iso = NAME_TO_ISO.get(key.lower())
    if iso and iso in ISO_TO_NAME:
        return ISO_TO_NAME[iso]
    return key


def to_iso2(origin: str) -> str:
    """Restituisce il codice ISO2 di un'origine (codice/nome/alias) o "" se ignota.

    Serve a garantire che ``origin_code`` sia sempre valorizzato: la mappa colora i
    poligoni dei paesi confrontando l'ISO2, quindi un'origine con solo nome leggibile
    deve poter risalire al codice.
    """
    if not origin:
        return ""
    key = origin.strip()
    if not key:
        return ""
    code = key.upper()
    if len(code) == 2 and code in ISO_TO_NAME:
        return code
    return NAME_TO_ISO.get(key.lower(), "")


def resolve_coordinates(origin: str) -> tuple[float | None, float | None]:
    """Map an origin (ISO code, full name or alias) to ``(lat, lng)``.

    Returns ``(None, None)`` when the origin is empty or unrecognised.
    """
    if not origin:
        return None, None
    key = origin.strip()
    if not key:
        return None, None

    # Direct ISO alpha-2 code (e.g. MusicBrainz "IT", "GB").
    code = key.upper()
    if len(code) == 2 and code in COUNTRY_COORDS:
        return COUNTRY_COORDS[code]

    # Full name / alias (e.g. TheAudioDB "United Kingdom", "USA").
    iso = NAME_TO_ISO.get(key.lower())
    if iso and iso in COUNTRY_COORDS:
        return COUNTRY_COORDS[iso]

    return None, None
