"""
Shared ownership classification logic used by the scraper and management commands.

MATCHING RULE
-------------
A keyword written WITH a leading or trailing space is matched as a WHOLE WORD.
A keyword written with no spaces at all is matched as a STEM (it may be followed
by more letters), because several of the languages here inflect the noun:
Turkish "Bakanlığı", Slovene "občine", Finnish "kaupungin".

This distinction is not cosmetic. The list originally used spaces as a poor
man's word boundary and the matcher ignored them, so " stad" (Dutch for "city")
matched the word "Stadium" and "Stadion" anywhere in an owner's NAME. Sixteen
grounds were affected: "Allianz Arena München Stadion GmbH", "The Community
Stadium Limited" and "Brann Stadion AS" were all read as municipally owned.
"land " (German "Land") matched "Sunderland 100%" the same way.
"""
import re

PUBLIC_KEYWORDS = [
    # ── English ──────────────────────────────────────────────────────────
    "city of", "municipality", "municipal", "council", "government",
    "ministry",
    "region", "province", "metropolitan city", "district",
    "oblast", "krai", "raion",
    "town of", "town council",
    "city council", "county council", "district council",
    "county council", "county borough", "city and county",
    # NB: bare "county" is deliberately absent — in English it is as likely to be a
    # CLUB ("Derby County F.C.", "Notts County") as an administrative area, and it
    # classified Pride Park as publicly owned.
    " parish",                 # rural municipality in Baltic/Nordic countries (e.g. Saue Parish)
    "metropolitan borough", "london borough", "royal borough",
    "public authority", "public body", "national sports",
    "sovereign state", "state of",
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
    "gemeinde", "marktgemeinde", "ortsgemeinde", "landkreis", "freistaat", "bundesland", "kommunal",
    "freie und hansestadt", "freie hansestadt", "hansestadt",
    "landeshauptstadt", "bezirksamt", "bezirk ", "regionalverband",
    "land ",
    # ── French (France / Belgium / Switzerland) ──────────────────────────
    "commune de", "mairie", "métropole",
    "ville de ", "ville d'", "ville du ", "ville des ",
    "agglomération", "agglomeration",
    "communauté", "communaute",
    "département", "région", "conseil général", "conseil régional",
    "grand paris", "grand lyon",
    # ── Spanish ──────────────────────────────────────────────────────────
    "ayuntamiento", "municipio", "diputación", "patronato municipal",
    "generalitat", "junta de ", "comunidad de", "community of", "consell",
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
    "f.c.", "a.f.c.", "a.s.", "s.s.",
    "fc ", "ac ", "as ", "ss ", "ssc ", "us ", "club",
    "s.p.a", "srl", "s.r.l.", "ltd", "limited", "llc", "group",
    "holding", "invest ", "property", "asset",
    "gesellschaft", "s.l.", "s.a.s.",
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


def _compile(keyword: str) -> "re.Pattern":
    """Turn a keyword-list entry into a regex.

    A keyword written with a leading or trailing space was meant as a WHOLE WORD —
    the space was the author's word boundary — so it gets boundaries at both ends.
    A keyword with no outer space is a STEM and is anchored only at its start, which
    is what lets "belediye" match "Belediyesi" and "municipal" match "municipality".
    """
    whole_word = keyword != keyword.strip()
    body = re.escape(keyword.strip()).replace(r"\ ", r"\s+")
    tail = r"(?!\w)" if whole_word else ""
    return re.compile(rf"(?<!\w){body}{tail}", re.IGNORECASE | re.UNICODE)


_PUBLIC_RE = [_compile(k) for k in PUBLIC_KEYWORDS]
_PRIVATE_RE = [_compile(k) for k in PRIVATE_KEYWORDS]


def _matched(text: str, patterns) -> list:
    """The keywords that fire on `text`, as source strings — useful for auditing."""
    return [p.pattern for p in patterns if p.search(text)]


_CLUB_NOISE = re.compile(
    r"(?<!\w)(fc|afc|cf|sc|ac|as|ss|ssc|us|sv|vfl|vfb|bsc|rc|sk|fk|nk|hk|ik|if|bk|"
    r"football|club|calcio|futbol|f\.c\.|a\.f\.c\.|the)(?!\w)|[^\w\s]",
    re.IGNORECASE | re.UNICODE)


def _norm_plain(s: str) -> str:
    """Case and punctuation only. Club markers are KEPT, which is what makes this
    usable for 'is the owner field just the city name?' — _norm_entity strips "NK"
    and would collapse the club NK Varaždin onto the city Varaždin."""
    return " ".join(re.sub(r"[^\w\s]", " ", s.lower(), flags=re.UNICODE).split())


def _norm_entity(s: str) -> str:
    """Strip club prefixes/suffixes and punctuation so 'Everton' == 'Everton F.C.'."""
    return " ".join(_CLUB_NOISE.sub(" ", s.lower()).split())


def _same_entity(club: str, owner: str) -> bool:
    """True when the recorded owner IS the club, not merely a name-share.

    Substring alone is too loose: a ground owned by "City of Manchester" must not
    match the club "Manchester City". Require the normalised club name to appear as
    a whole token-run inside the normalised owner string.
    """
    c, o = _norm_entity(club), _norm_entity(owner)
    if not c or not o:
        return False
    ct, ot = c.split(), o.split()

    def run_in(needle, hay):
        return (len(needle) <= len(hay)
                and any(hay[i:i + len(needle)] == needle
                        for i in range(len(hay) - len(needle) + 1)))

    # Symmetric: the DB's club name and Wikipedia's owner field are rarely spelled
    # the same way. "Benfica" owns Estádio da Luz but the club is stored as
    # "SL Benfica"; "Everton" owns its ground and is stored as "Everton". Either
    # string may be the longer one, so test both directions.
    # The public keywords are checked BEFORE this, so a council that happens to
    # share a name with its tenant has already been classified.
    # Both directions. A bare one-word owner sitting inside a club's name is the
    # dangerous case — "Rzeszów" inside "Stal Rzeszów" is the CITY — but callers
    # that pass city_name have already had that settled by the city rule before
    # this is reached. Without a city_name this stays a genuine ambiguity, which
    # is why the audit command always passes one.
    return run_in(ct, ot) or run_in(ot, ct)


def classify_ownership(owner_raw: str, club_names=None, city_name=None) -> str:
    """
    Classify stadium ownership as PUBLIC, PRIVATE, MIXED, or UNKNOWN.

    PUBLIC   a state, municipal or other public body owns the ground
    PRIVATE  a club, holding company, trust or other private entity owns it
    MIXED    both are named — e.g. a council owns the land and the club the stand,
             or a public authority holds the freehold under a private concession
    UNKNOWN  no owner recorded, or an owner we cannot categorise from its name alone

    UNKNOWN IS A REAL ANSWER, NOT A GAP TO FILL. An earlier version returned PRIVATE
    for anything with no public keyword, and `fix_unknown_ownership` then rewrote any
    remaining UNKNOWN to PRIVATE on top of that. Between them, "Ville du Mans" and
    "Grand Troyes" — a city and an agglomeration community — were both published as
    privately owned grounds. Guessing PRIVATE is not more useful than admitting we
    do not know; it is the same claim made without evidence.
    """
    if not owner_raw or not owner_raw.strip():
        return "UNKNOWN"

    text = owner_raw.strip()
    has_public = any(p.search(text) for p in _PUBLIC_RE)
    has_private = any(p.search(text) for p in _PRIVATE_RE)

    if has_public and has_private:
        return "MIXED"
    if has_public:
        return "PUBLIC"
    if has_private:
        return "PRIVATE"

    # No keyword fired. Before giving up, check the strongest evidence we actually
    # hold: the ground's own tenants. Wikipedia records a club-owned stadium's owner
    # as the bare club name — "Everton", "Crystal Palace", "Nottingham Forest" — which
    # carries no company suffix to match on. Comparing against the clubs that play
    # there turns 200-odd of those from a guess into a fact.
    # Nothing matched a keyword. Fall back to the strongest evidence we hold: the
    # ground's own tenants and its city. Wikipedia records a club-owned stadium's
    # owner as the bare club name — "Everton", "Middlesbrough" — and a council-owned
    # one as the bare town name — "Caen", "Rzeszów". Those two look identical when
    # the club is named after its town, so the order below matters.
    clubs = [c.strip() for c in (club_names or ()) if c and len(c.strip()) >= 4]
    owner_n = _norm_entity(text)

    # 1. The owner IS a club, name for name. "Middlesbrough" owns the Riverside;
    #    "Barcelona" (i.e. FC Barcelona) owns the Camp Nou. This has to beat the
    #    city rule, or every English club named after its town becomes council-owned.
    if any(_norm_entity(c) == owner_n for c in clubs):
        return "PRIVATE"

    # 2. The owner is exactly the city's name and no club answers to it, so it is
    #    the municipality: "Rzeszów" (the club is Stal Rzeszów), "Caen" (SM Caen).
    if city_name and _norm_plain(text) == _norm_plain(city_name):
        return "PUBLIC"

    # 3. Otherwise a containment either way is good enough — "Benfica" in the owner
    #    field against the stored club "SL Benfica". Step 2 has already taken the
    #    town names out of the running, so this can no longer swallow a city.
    if any(_same_entity(c, text) for c in clubs):
        return "PRIVATE"

    return "UNKNOWN"


def explain(owner_raw: str) -> dict:
    """Why a string classified the way it did. Used by the audit command."""
    text = (owner_raw or "").strip()
    return {
        "result": classify_ownership(owner_raw),
        "public_hits": _matched(text, _PUBLIC_RE) if text else [],
        "private_hits": _matched(text, _PRIVATE_RE) if text else [],
    }
