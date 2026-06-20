"""
audit_team_links
================
Detect teams pointing at the WRONG Transfermarkt club. The scraper sometimes stored
a foreign club's Transfermarkt verein ID (e.g. Hibernians FC → /verein/4174, which is
actually "BSC Rehberge"), which also poisons the crest (image_url = wappen/<id>.png).

Rule (embed in scrape QA): fetch the Transfermarkt page <title> (the real club name)
and compare its significant tokens to the stored team name. Zero overlap ⇒ wrong link.
The Wikipedia link is checked the cheap way (team name vs URL slug tokens).

Because the crest is derived from the same (wrong) ID, `--fix` clears BOTH the bad
Transfermarkt URL and the TM-derived crest so users are never sent to / shown the wrong
club. Correct IDs must then be re-sourced (separate task).

Usage:
    python -X utf8 manage.py audit_team_links --country Malta
    python -X utf8 manage.py audit_team_links --country Malta --fix
"""
import re
import time
import unicodedata
import urllib.parse

import requests
from django.core.management.base import BaseCommand

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120 Safari/537.36")
# club-type noise words to ignore when comparing names
NOISE = {"fc", "f", "c", "sc", "sv", "bsc", "ac", "as", "ssc", "cf", "club",
         "united", "city", "town", "calcio", "spartans", "wanderers", "lions",
         "rainbows", "the", "de", "of"}


# Letters NFKD won't decompose — transliterate so same-club names match
# (e.g. Icelandic "Breiðablik" == TM "Breidablik", "Hafnarfjörður" == "Hafnarfjördur").
_TRANSLIT = str.maketrans({
    "ð": "d", "Ð": "d", "þ": "th", "Þ": "th", "ø": "o", "Ø": "o",
    "æ": "ae", "Æ": "ae", "ß": "ss", "ł": "l", "Ł": "l", "đ": "d", "Đ": "d",
    "ı": "i", "İ": "i",  # Turkish dotless/dotted i (NFKD won't fold ı)
})


def _sig(text):
    text = text.translate(_TRANSLIT)
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    text = re.sub(r"[^a-zA-Z0-9 ]", " ", text).lower()
    return {w for w in text.split() if w not in NOISE and len(w) > 2}


def _related(a, b):
    """True if the two name token-sets plausibly refer to the same club.
    Matches exact tokens OR substring/prefix pairs (handles abbreviations like
    'KuPS Kuopio' vs 'Kuopion Palloseura' and genitive forms 'Vaasa'/'Vaasan')."""
    for x in a:
        for y in b:
            if x == y or (len(x) >= 4 and len(y) >= 4 and (x in y or y in x)):
                return True
    return False


def _tm_club_name(url):
    """Fetch the Transfermarkt page and return the real club name from <title>.
    Returns "__404__" for a dead link, or None if unreachable after retries.
    Retries on timeouts / 5xx (TM rate-limits under load)."""
    last = None
    for attempt in range(4):
        try:
            r = requests.get(url, headers={"User-Agent": UA}, timeout=30)
            if r.status_code == 404:
                return "__404__"
            if r.status_code in (429, 502, 503, 504):
                last = f"HTTP {r.status_code}"
                time.sleep(6 + attempt * 6)
                continue
            r.raise_for_status()
            m = re.search(r"<title>(.*?)</title>", r.text, re.S)
            if not m:
                return None
            # "BSC Rehberge - Club profile | Transfermarkt" -> "BSC Rehberge"
            return re.split(r"\s[-|]\s", m.group(1).strip())[0].strip()
        except requests.exceptions.RequestException as e:
            last = str(e)[:50]
            time.sleep(6 + attempt * 6)
    raise RuntimeError(last or "unreachable")


class Command(BaseCommand):
    help = "Audit team Transfermarkt/Wikipedia links against the real club name."

    def add_arguments(self, parser):
        parser.add_argument("--country", default="", help="Limit to one league country.")
        parser.add_argument("--fix", action="store_true",
                            help="Clear the wrong Transfermarkt URL + TM-derived crest.")
        parser.add_argument("--delay", type=float, default=1.5)

    def handle(self, *args, **opts):
        from italiastadiaapp.models import Team

        qs = Team.objects.select_related("league__country").exclude(
            transfermarkt_url=""
        ).exclude(transfermarkt_url=None)
        if opts["country"]:
            qs = qs.filter(league__country__name=opts["country"])

        bad = []
        total = qs.count()
        for i, t in enumerate(qs, 1):
            if i % 25 == 0:
                self.stdout.write(f"  …{i}/{total} checked, {len(bad)} wrong so far")
            name_sig = _sig(t.name)
            try:
                real = _tm_club_name(t.transfermarkt_url)
            except Exception as e:
                self.stdout.write(f"  [unreachable] {t.name}: {e}  ({t.transfermarkt_url})")
                continue
            time.sleep(opts["delay"])
            if real == "__404__":
                bad.append((t, "dead 404"))
                self.stdout.write(self.style.ERROR(
                    f"  WRONG (404): {t.name}  ({t.transfermarkt_url})"))
                continue
            if not real:
                continue
            if name_sig and _sig(real) and not _related(name_sig, _sig(real)):
                bad.append((t, real))
                self.stdout.write(self.style.ERROR(
                    f"  WRONG: {t.name}  ->  TM shows '{real}'  ({t.transfermarkt_url})"))

        self.stdout.write(self.style.WARNING(f"\nWrong Transfermarkt links: {len(bad)} / {total}"))

        if opts["fix"]:
            for t, _real in bad:
                t.transfermarkt_url = ""
                # crest derived from the same wrong verein id → clear it too
                if t.image_url and "tmssl" in t.image_url:
                    t.image_url = ""
                t.save(update_fields=["transfermarkt_url", "image_url"])
            self.stdout.write(self.style.SUCCESS(
                f"Cleared {len(bad)} wrong TM links (+ TM-derived crests). "
                "Re-source correct IDs separately."))
        elif bad:
            self.stdout.write("(dry run — re-run with --fix to clear the wrong links)")
