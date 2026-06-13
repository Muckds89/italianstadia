"""
Shared ownership classification logic used by the scraper and management commands.
"""

PUBLIC_KEYWORDS = [
    # ── English ──────────────────────────────────────────────────────────
    "city of", "municipality", "municipal", "council", "government",
    "ministry",
    "region", "province", "metropolitan city", "district",
    "town of", "town council",
    "city council", "county council", "district council",
    " county",                 # administrative county (e.g. Klaipėda County, County Dublin)
    " parish",                 # rural municipality in Baltic/Nordic countries (e.g. Saue Parish)
    "metropolitan borough", "london borough", "royal borough",
    "public authority", "public body", "national sports",
    "sports authority", "stadium authority",
    "sports organ",
    "sport organ",
    "olympic committee",
    "agglomeration",
    # ── Italian ──────────────────────────────────────────────────────────
    "comune di", "comune", "comunale", "provincia", "città metropolitana",
    "regione ", "ministero", "ente pubblico",
    "sport e salute",
    "commune of", "commune di",
    # ── German (Germany / Austria / Switzerland) ─────────────────────────
    "stadt ", "stadtwerke", "stadtverwaltung", "stadtgemeinde",
    "gemeinde", "landkreis", "freistaat", "bundesland", "kommunal",
    "freie und hansestadt", "freie hansestadt", "hansestadt",
    "landeshauptstadt", "bezirksamt", "bezirk ", "regionalverband",
    "land ",
    # ── French (France / Belgium / Switzerland) ──────────────────────────
    "commune de", "mairie", "métropole",
    "ville de ", "ville d'",
    "agglomération", "agglomeration",
    "communauté", "communaute",
    "département", "région", "conseil général", "conseil régional",
    "grand paris", "grand lyon",
    # ── Spanish ──────────────────────────────────────────────────────────
    "ayuntamiento", "municipio", "diputación", "patronato municipal",
    "generalitat", "junta de ", "comunidad de", "consell",
    "consejo municipal",
    "concello ",
    "cabildo ",
    # ── Portuguese ───────────────────────────────────────────────────────
    "município", "câmara municipal", "câmara ", "câmara de",
    "junta de freguesia", "autarquia",
    "governo regional", "região autónoma",
    # ── Polish ───────────────────────────────────────────────────────────
    "miasto ",
    "miasto stołeczne",
    "gmina ",
    "urząd miejski",
    "województwo",
    "powiat ",
    "skarb państwa",
    # ── Dutch / Belgian (Flemish) ────────────────────────────────────────
    "gemeente ",
    "stad ",
    " stad",
    "stadsbestuur", "stadsgewest", "stadseigendom",
    "provinciaal", "provincie ",
    "gewest ",
    # ── Turkish ──────────────────────────────────────────────────────────
    "belediye",
    "büyükşehir",
    "il özel idaresi",
    "devlet ",
    "bakanlı",
    # ── Nordic: Norwegian / Danish ───────────────────────────────────────
    "kommune",
    "fylke",
    "amt ",
    # ── Swedish ──────────────────────────────────────────────────────────
    "stadsförvaltning", "stadsfastigheter",
    "landstinget", "landsting",
    "stockholms stad", "göteborgs stad", "malmö stad",
    # ── Finnish ──────────────────────────────────────────────────────────
    "kaupunki",
    "kunta ",
    # ── Czech / Slovak ───────────────────────────────────────────────────
    "město ",
    "statutární město",
    "obec ",
    "kraj ",
    "krajský",
    "ministerstvo",
    # ── Romanian ─────────────────────────────────────────────────────────
    "primăria", "primărie",
    "consiliu local",
    "județ",
    "municipiu",
    "ministerul",
    # ── Croatian / Serbian / Bosnian ─────────────────────────────────────
    "grad ",
    "gradska ",
    "općina ",
    "skupština",
    "kantona",
    # ── Slovenian ────────────────────────────────────────────────────────
    "mestna občina",
    "občina ",
    "javni zavod",
    # ── Hungarian ────────────────────────────────────────────────────────
    "város ",
    "önkormányzat",
    "fővárosi",
    # ── Greek (transliterated) ───────────────────────────────────────────
    "dimos ",
    "dimou",
    # ── Lithuanian ───────────────────────────────────────────────────────
    "savivaldybė",             # municipality (e.g. Šiaulių miesto savivaldybė)
    "savivaldybes",            # genitive form
    "miesto savivaldybė",      # city municipality
    "rajono savivaldybė",      # district municipality
    # ── Albanian ─────────────────────────────────────────────────────────
    "bashkia ",                # municipality (Bashkia Vlorë, Bashkia Tiranë …)
    "bashkie",                 # genitive / other forms
    "komuna ",                 # commune / municipality
]

PRIVATE_KEYWORDS = [
    "football club", "fussball", "fußball", "calcio",
    "fc ", "ac ", "as ", "ss ", "ssc ", "us ", "club",
    "s.p.a", "srl", "s.r.l.", "ltd", "llc", "group",
    "holding", "invest ", "property", "asset",
    "gmbh", "g.m.b.h", " ag,", "e.v.", "e. v.",
    "s.a.", "sarl",
    "s.a.d.", " sad,", "sociedad anónima",
    " lda.", " lda,",
    "sp. z o.o.", "spółka akcyjna",
    " b.v.", " n.v.", " b.v,", " n.v,",
    " ab ", " ab,", " oy ", " oy,", " a/s", " asa ",
    " a.s.", " s.r.o.",
    " bvba", " cvba",
]


def classify_ownership(owner_raw: str) -> str:
    """
    Classify stadium ownership as PUBLIC, PRIVATE, MIXED, or UNKNOWN.

    UNKNOWN is returned only when owner_raw is empty/None.
    Any owner_raw with no public keyword → PRIVATE (clubs, holding companies, etc.).
    """
    if not owner_raw:
        return "UNKNOWN"

    text = owner_raw.lower()
    has_public = any(kw in text for kw in PUBLIC_KEYWORDS)

    if has_public:
        has_private = any(kw in text for kw in PRIVATE_KEYWORDS)
        return "MIXED" if has_private else "PUBLIC"

    return "PRIVATE"
