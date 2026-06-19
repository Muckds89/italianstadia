"""
audit_stadium_names
===================
Find stadiums whose stored `name` shares NO significant word with their own
Wikipedia page title. The Wikipedia URL is the reliable anchor of a scrape, so a
zero-overlap name is almost always one of:

  * SPONSOR  — a legit current sponsor name (e.g. "Signal Iduna Park" vs
               "Westfalenstadion"). Both names fit the country. NOT an error.
  * SUSPECT  — the name is in a language foreign to the stadium's country
               (e.g. German "Stadion Rehberge" stored for a Maltese ground).
               This is a bad scrape; the Wikipedia title is the correct name.

Heuristic to embed in the scrape QA step: after scraping, if the name shares no
token with the Wikipedia title AND the name carries a structural word native to a
DIFFERENT language than the country, trust the Wikipedia title.

Usage:
    python -X utf8 manage.py audit_stadium_names            # report only
    python -X utf8 manage.py audit_stadium_names --fix      # adopt wiki titles for SUSPECTs
"""
import re
import unicodedata
import urllib.parse

from django.core.management.base import BaseCommand

STOP = {
    "stadio", "stadium", "stade", "estadio", "stadion", "estadi", "arena", "park",
    "ground", "field", "de", "del", "di", "la", "el", "of", "the", "und", "and",
    "stadionul", "stadyumu", "citta", "city", "new", "nuovo", "nou", "das", "dos",
}

# Structural stadium words that imply a specific language/region. If one appears in
# a name whose country is NOT in that language's home set, the name is foreign.
FOREIGN_MARKERS = {
    # German (DE/AT/CH)
    "sportplatz": "DE", "waldstadion": "DE", "lokstadion": "DE", "sportanlage": "DE",
    "strasse": "DE", "strae": "DE", "glashutte": "DE", "wildpark": "DE",
    "muritz": "DE", "anlage": "DE", "stadion": None,  # 'stadion' alone is shared — ignore
    # Danish / Dutch / French / Portuguese / Vietnamese fragments seen in bad scrapes
    "anlaeg": "DK", "anlg": "DK", "sportpark": "NL", "communal": "FR",
    "bessa": "PT", "seculo": "PT", "binh": "XX", "duong": "XX",
}
LANG_HOME = {
    "DE": {"Germany", "Austria", "Switzerland", "Liechtenstein"},
    "DK": {"Denmark"},
    "NL": {"Netherlands", "Belgium"},
    "FR": {"France", "Belgium", "Luxembourg", "Switzerland", "Monaco"},
    "PT": {"Portugal"},
    "XX": set(),
}


def _norm_words(text):
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    text = re.sub(r"\(.*?\)", "", text)
    text = re.sub(r"[^a-zA-Z0-9 ]", " ", text).lower()
    return [w for w in text.split() if w]


def _wiki_title(url):
    if not url:
        return ""
    return urllib.parse.unquote(url.rstrip("/").split("/wiki/")[-1]).replace("_", " ")


def classify(name, country, wiki_title):
    """Return (status, corrected_name) where status in NONE/SPONSOR/SUSPECT."""
    nwords = _norm_words(name)
    twords = _norm_words(wiki_title)
    nset = {w for w in nwords if w not in STOP and len(w) > 2}
    tset = {w for w in twords if w not in STOP and len(w) > 2}
    if not nset or not tset or (nset & tset):
        return "NONE", None
    # zero overlap → check for a foreign structural marker
    for w in nwords:
        lang = FOREIGN_MARKERS.get(w)
        if lang and country not in LANG_HOME.get(lang, set()):
            return "SUSPECT", wiki_title.strip()
    return "SPONSOR", None


class Command(BaseCommand):
    help = "Audit stadium names against their Wikipedia page titles (scrape QA)."

    def add_arguments(self, parser):
        parser.add_argument("--fix", action="store_true",
                            help="Adopt the Wikipedia title as the name for SUSPECT rows.")

    def handle(self, *args, **opts):
        from italiastadiaapp.models import Stadium

        suspects, sponsors = [], 0
        qs = Stadium.objects.select_related("city").exclude(
            wikipedia_url=""
        ).exclude(wikipedia_url=None)
        for s in qs:
            country = s.city.country if s.city else "?"
            status, corrected = classify(s.name, country, _wiki_title(s.wikipedia_url))
            if status == "SPONSOR":
                sponsors += 1
            elif status == "SUSPECT":
                suspects.append((s, country, corrected))

        self.stdout.write(self.style.WARNING(
            f"\nSUSPECT (foreign-language name, wiki title is the fix): {len(suspects)}"))
        for s, country, corrected in sorted(suspects, key=lambda x: x[1]):
            self.stdout.write(f"  {country[:16]:16} | {s.name[:30]:30} -> {corrected}")
        self.stdout.write(f"\nSPONSOR renames (ignored, not errors): {sponsors}")

        if opts["fix"]:
            for s, _country, corrected in suspects:
                s.name = corrected
                s.save(update_fields=["name", "slug"] if not s.slug else ["name"])
            self.stdout.write(self.style.SUCCESS(
                f"\nFixed {len(suspects)} stadium names (adopted Wikipedia titles)."))
        else:
            self.stdout.write("\n(dry run — re-run with --fix to apply)")
