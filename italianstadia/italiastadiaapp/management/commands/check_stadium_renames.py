"""
check_stadium_renames
=====================
Re-read each ground's Wikipedia lead and flag the ones whose STORED NAME no longer
appears in it — the signature of a naming-rights change we never picked up.

WHY THIS EXISTS. Stadium names are captured once, when a league is scraped, and
nothing looks at them again. A season update re-reads which clubs are in a division;
it does not re-read their grounds. So a sponsor change lands silently, and the map
keeps publishing the old name until a reader complains — which is exactly how the
Stade Vélodrome went out as "Orange Vélodrome" three weeks after it became the
CEPAC Vélodrome on 2 July 2026.

`audit_stadium_names` does NOT catch this. It flags names sharing no word with the
Wikipedia title, which finds bad scrapes but not renames: "Orange Vélodrome" and
"Cepac Vélodrome" both share "Vélodrome" with the title "Stade Vélodrome", so it
looked healthy the whole time.

    python -X utf8 manage.py check_stadium_renames --league "Ligue 1"
    python -X utf8 manage.py check_stadium_renames --country France
    python -X utf8 manage.py check_stadium_renames            # every ground, slow

Reports only. Renames are applied by hand after checking the effective date —
a sponsor announced is not a sponsor in use.
"""
import re
import time
import unicodedata
import urllib.parse

import requests
from django.core.management.base import BaseCommand

from italiastadiaapp.models import Stadium

UA = {"User-Agent": "stadiamap/1.0 (destavola.marco@gmail.com)"}
BATCH = 20          # exlimit caps extracts at 20 titles per call

# "known as the CEPAC Vélodrome for sponsorship reasons"
SPONSOR_RE = re.compile(
    r"(?:known|referred to|branded)\s+as\s+(?:the\s+)?"
    r"([A-Z0-9ÀÁÂÄÅÇÈÉÊËÌÍÎÏÑÒÓÔÖÙÚÛÜŠŽ][^,.;:()\[\]]{2,45}?)"
    r"\s+(?:for\s+sponsorship|due\s+to\s+sponsorship|under\s+a\s+sponsorship)",
    re.UNICODE)


def _fold(s: str) -> str:
    """Casefold and strip diacritics so 'Vélodrome' matches 'Velodrome'."""
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()


# Words carrying no identity: the word "stadium" itself, a civic qualifier, or a
# grammatical particle, in whichever language the article happens to be written in.
# Comparing the WHOLE stored name against the lead flagged 220 of 975 grounds, because
# an English stored name can never appear verbatim inside a Turkish or Russian lead —
# yet "Van Atatürk Stadium" and "Van Atatürk Stadyumu" are plainly the same ground.
GENERIC = {
    "stadium", "stadion", "stadionul", "stadyumu", "stadi", "stadio", "stade",
    "estadio", "estadi", "stadions", "stadionas", "stadionu", "stadt", "stadion",
    "arena", "park", "parc", "ground", "field", "complex", "complexul", "sportiv",
    "sports", "sport", "kompleksi", "spor", "imeni",
    "municipal", "municipality", "miejski", "gradski", "belediyesi", "belediye",
    "city", "district", "ilce", "sehir", "town",
    "new", "yeni", "nuovo", "nou", "noi",
    "the", "of", "de", "del", "di", "da", "do", "dos", "das", "la", "le", "les",
    "el", "und", "and", "im", "in", "w", "na", "at", "a",
}


def _tokens(s: str) -> set:
    """The words of a name that actually identify it."""
    return {t for t in _fold(s).split() if t and t not in GENERIC}


# "…, currently known as SNP Arena and previously as PreZero Arena, is a stadium…"
# A rename usually LEAVES the old name in the lead, introduced like this. Plain
# containment therefore reports the name as healthy while the ground has already
# been renamed — which is exactly how Hoffenheim's PreZero Arena passed this check
# on the day it was published as the SNP Arena, and a reader caught it instead.
FORMER_RE = re.compile(
    r"(?:previously|formerly|förmals|ehemals|früher|until\s+\d{4}|bis\s+\d{4})"
    r"[\s,]+(?:also\s+)?(?:known\s+)?(?:as\s+)?(?:the\s+)?"
    r"([^,.;:()\[\]]{2,60})",
    re.IGNORECASE | re.UNICODE)


def _stored_name_is_marked_former(lead: str, want: set) -> bool:
    """True when the lead introduces the STORED name as a former one.

    Only fires when the old name sits inside a "previously/formerly …" clause, so a
    lead that merely mentions the current name in passing is untouched.
    """
    for m in FORMER_RE.finditer(lead):
        # EQUALITY, not containment. When a sponsor prefix is DROPPED the former name
        # contains the current one — the Goffertstadion was "formerly McDOS
        # Goffertstadion", so a containment test flags the correct current name as
        # stale. Equality flags only a name that IS the former one, whole.
        if want and want == _tokens(m.group(1)):
            return True
    return False


class Command(BaseCommand):
    help = "Flag stadiums whose stored name is absent from their Wikipedia lead."

    def add_arguments(self, p):
        p.add_argument("--league", help="restrict to one league name")
        p.add_argument("--country", help="restrict to one country name")
        p.add_argument("--sleep", type=float, default=0.3)

    def handle(self, *a, **o):
        qs = (Stadium.objects.exclude(wikipedia_url__isnull=True)
              .exclude(wikipedia_url="").prefetch_related("teams"))
        if o["league"]:
            qs = qs.filter(teams__league__name=o["league"])
        if o["country"]:
            qs = qs.filter(teams__league__country__name=o["country"])
        qs = qs.distinct()

        # group by wiki host, since a few grounds are only on a local-language wiki
        by_host = {}
        for s in qs:
            parsed = urllib.parse.urlparse(s.wikipedia_url)
            title = urllib.parse.unquote(parsed.path.rsplit("/", 1)[-1]).replace("_", " ")
            if title:
                by_host.setdefault(parsed.netloc, {})[title] = s

        flagged, checked, noleads = [], 0, []
        for host, titles in by_host.items():
            names = list(titles)
            for i in range(0, len(names), BATCH):
                batch = names[i:i + BATCH]
                try:
                    r = requests.get(
                        f"https://{host}/w/api.php",
                        params={"action": "query", "format": "json",
                                "formatversion": "2", "redirects": 1,
                                "prop": "extracts", "exintro": 1, "explaintext": 1,
                                "exlimit": BATCH, "titles": "|".join(batch)},
                        headers=UA, timeout=40)
                    time.sleep(o["sleep"])
                    data = r.json()
                except Exception as e:
                    self.stderr.write(f"  {host} batch failed: {e}")
                    continue

                q = data.get("query", {})
                alias = {m["from"]: m["to"] for k in ("normalized", "redirects")
                         for m in q.get(k, [])}
                pages = {p.get("title"): p for p in q.get("pages", [])}

                for src in batch:
                    dst = alias.get(src, src)
                    while dst in alias:
                        dst = alias[dst]
                    page = pages.get(dst) or pages.get(src)
                    stadium = titles[src]
                    lead = (page or {}).get("extract") or ""
                    if not lead:
                        noleads.append(stadium)
                        continue
                    checked += 1
                    want = _tokens(stadium.name)

                    # FIRST: is the stored name introduced as a FORMER one? This has to
                    # be asked before containment, because a renamed ground keeps its old
                    # name in the lead and would otherwise sail through as healthy.
                    if _stored_name_is_marked_former(lead, want):
                        m = SPONSOR_RE.search(lead)
                        flagged.append((stadium, m.group(1).strip() if m else None,
                                        lead[:180].replace("\n", " ")))
                        continue

                    # Otherwise: does every DISTINCTIVE word of the stored name still
                    # turn up in the lead? If so the name is alive in the article and
                    # there is nothing to report — even when the article ALSO mentions
                    # some other sponsored title. The MKM Stadium's article names "Hull
                    # City Stadium" (the version UEFA requires) further down; the stored
                    # name is not stale.
                    if not want or want <= _tokens(lead):
                        continue

                    # It is missing, so the name has moved on. If the lead spells out a
                    # sponsored title, offer it as the likely replacement.
                    m = SPONSOR_RE.search(lead)
                    flagged.append((stadium, m.group(1).strip() if m else None,
                                    lead[:180].replace("\n", " ")))

        self.stdout.write(f"\nchecked {checked} ground(s); "
                          f"{len(noleads)} had no lead text")
        if not flagged:
            self.stdout.write(self.style.SUCCESS(
                "every stored name still appears in its article's lead"))
            return

        self.stdout.write(self.style.ERROR(
            f"\n{len(flagged)} stored name(s) absent from the article lead:"))
        for s, sponsor, lead in flagged:
            clubs = ", ".join(t.name for t in s.teams.all()[:2]) or "-"
            self.stdout.write(f"\n  {s.name!r}  [{clubs}]")
            if sponsor:
                self.stdout.write(self.style.WARNING(
                    f"    article's sponsored name: {sponsor!r}"))
            self.stdout.write(f"    lead: {lead}...")
        self.stdout.write(self.style.WARNING(
            "\nCheck the effective date before renaming — an announced deal is not "
            "yet a name in use."))
