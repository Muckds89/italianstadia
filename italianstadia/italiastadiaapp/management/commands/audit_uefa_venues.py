"""
audit_uefa_venues
=================
Read the UEFA season articles and report every club whose EUROPEAN home ground is
not the ground we publish for it.

WHY THIS EXISTS. A club's domestic ground and its European ground are two
different facts, and until readers pointed it out nothing in this project knew
that. AGF Aarhus went out on a Conference League map at Ceres Park Vejlby -- a
temporary modular ground that is not licensed for UEFA matches -- and Mjallby at
Strandvallen, 147km from the Olympia in Helsingborg where they actually host.
Both were reported by readers on r/MapPorn within hours of each other.

No existing check could have caught either. `check_stadium_renames` asks whether
a ground's NAME has changed; `audit_stadium_names` asks whether a name matches
its own article. Neither asks the question that matters here, which is whether
this club plays European football at this ground at all.

WHERE THE ANSWER LIVES. The Wikipedia article for each season's LEAGUE PHASE
carries an explicit footnote for every relocation, in a fixed form:

    X will play their home matches at A, City, instead of their regular stadium,
    B, City, which does not meet UEFA requirements.

plus the standing notes for clubs barred from hosting at home at all (Ukrainian
clubs since the Russian invasion, Israeli clubs since the Gaza war), which name
the neutral venue the same way. That is the authoritative list, it is maintained
by editors through the season, and reading it costs three HTTP requests.

    python -X utf8 manage.py audit_uefa_venues
    python -X utf8 manage.py audit_uefa_venues --season 2027-28
    python -X utf8 manage.py audit_uefa_venues --json out.json

Reports; it does not write. Applying a relocation needs a Stadium row for the
replacement ground, which often does not exist yet because the host club plays in
a division we do not cover -- Olympia had to be created from scratch for Mjallby.

RUN THIS BEFORE PUBLISHING ANY CONTINENTAL MAP.
"""
import json
import re
import unicodedata
import urllib.parse

import requests
from django.core.management.base import BaseCommand

from italiastadiaapp.models import Team
# The venue-name vocabulary is the same problem `check_stadium_renames` already
# solved: "stadium", "arena", "park" and their equivalents in every European
# language carry no identity. Comparing venue names WITH them made every pair
# overlap on the word "stadium" alone, so this audit's first run reported
# Ararat-Armenia's "Yerevan Football Academy Stadium" as agreeing with "Vazgen
# Sargsyan Republican Stadium" -- four wrong grounds hidden behind one shared noun.
from italiastadiaapp.management.commands.check_stadium_renames import (
    _tokens as venue_tokens,
)

UA = {"User-Agent": "stadiamap/1.0 (destavola.marco@gmail.com)"}

# The en-dash is the one Wikipedia uses in season titles; a hyphen 404s.
ARTICLES = {
    "UCL": "{season} UEFA Champions League league phase",
    "UEL": "{season} UEFA Europa League league phase",
    "UECL": "{season} UEFA Conference League league phase",
}

# "... will play their home matches at VENUE, CITY, instead of their regular
# stadium, OLD, CITY, which does not meet UEFA requirements."
#
# `had scheduled` is deliberately NOT matched. The Union Saint-Gilloise note
# appears twice in the 2026-27 Europa League article: once as the live
# relocation, and once in the past tense recording that Leuven then banned one
# specific fixture. Matching both would report the club twice and invite
# "corrections" to a venue that applies to a single match.
#
# `(?P<country>...)` is OPTIONAL and is the whole reason the standing bans are
# caught. A domestic relocation names two parts ("Olympia, Helsingborg, instead
# of ..."); a club exiled abroad names three ("Stamford Bridge, London, England,
# instead of ..."). Without the optional third part the pattern cannot reach the
# "instead of" clause, and the audit silently missed BOTH clubs that were moved
# to another country -- Shakhtar Donetsk and Hapoel Be'er Sheva -- which are the
# most wrong markers on the whole map.
RELOC = re.compile(
    r"(?P<club>[^.]{2,60}?)\s+will play (?:their|its) home matches at\s+"
    r"(?P<venue>[^,]{2,60}?),\s*(?P<city>[^,]{2,40}?),\s*"
    r"(?:(?P<country>[^,]{2,40}?),\s*)?"
    r"instead of (?:their|its) regular stadium,\s*"
    r"(?P<old>[^,]{2,60}?),\s*(?P<oldcity>[^,.]{2,40}?)\s*[,.]\s*"
    r"(?:(?:which|due to)\s*(?P<why>[^.]{0,80}))?", re.U)


def _fold(s):
    s = unicodedata.normalize("NFKD", (s or "").lower())
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


_STOP = {"fc", "afc", "cf", "sc", "sk", "fk", "ac", "as", "cd", "ss", "us",
         "club", "the", "de", "of"}


def _tokens(s):
    return {t for t in _fold(s).split() if t and t not in _STOP}


def _notes(txt):
    """Every {{refn|group=note|...}} body, brace-balanced.

    A regex cannot do this: the notes contain nested templates ({{cite web}},
    {{lang}}) and a lazy match to the first '}}' truncates half of them.
    """
    out = []
    for m in re.finditer(r"\{\{refn\|group=note\|", txt):
        i, depth, start = m.end(), 2, m.end()
        while i < len(txt) and depth:
            if txt.startswith("{{", i):
                depth += 2
                i += 2
            elif txt.startswith("}}", i):
                depth -= 2
                i += 2
            else:
                i += 1
        out.append(txt[start:i - 2])
    return out


def _clean(s):
    """Wikitext -> readable prose: drop refs and templates, unwrap links."""
    s = re.sub(r"<ref[^>]*>.*?</ref>", "", s, flags=re.S)
    s = re.sub(r"<ref[^>]*/>", "", s)
    s = re.sub(r"\{\{[^{}]*\}\}", "", s)
    s = re.sub(r"\[\[(?:[^\]|]*\|)?([^\]|]*)\]\]", r"\1", s)
    s = re.sub(r"'{2,}", "", s)
    return re.sub(r"\s+", " ", s).strip()


class Command(BaseCommand):
    help = "Report clubs whose European home ground differs from the one we publish."

    def add_arguments(self, p):
        p.add_argument("--season", default="2026-27",
                       help="season as it appears in the article title (2026-27)")
        p.add_argument("--json", dest="json_out")

    def _wikitext(self, title):
        try:
            r = requests.get("https://en.wikipedia.org/w/api.php", params={
                "action": "query", "format": "json", "formatversion": "2",
                "redirects": 1, "titles": title, "prop": "revisions",
                "rvprop": "content", "rvslots": "main"}, headers=UA, timeout=60)
            pg = r.json()["query"]["pages"][0]
        except Exception as e:                                   # noqa: BLE001
            self.stderr.write(f"  {title}: {e}")
            return None
        if pg.get("missing"):
            self.stderr.write(f"  {title}: no such article")
            return None
        return pg["revisions"][0]["slots"]["main"]["content"]

    def handle(self, *a, **o):
        season = o["season"].replace("-", "–")   # en-dash, as Wikipedia writes it
        found, fetch_failures = [], 0

        for comp, tmpl in ARTICLES.items():
            title = tmpl.format(season=season)
            txt = self._wikitext(title)
            if txt is None:
                fetch_failures += 1
                continue
            seen = set()
            for body in _notes(txt):
                body = re.sub(r"^name=[^|]+\|", "", body)
                prose = _clean(body)
                if not prose or prose in seen:
                    continue
                seen.add(prose)
                if "had scheduled" in prose:
                    continue
                m = RELOC.search(prose)
                if not m:
                    continue
                d = m.groupdict()
                # A standing ban states the reason in a preceding sentence ("Due
                # to the Gaza war, Israeli teams are required to play at neutral
                # venues. Therefore, Hapoel Be'er Sheva will play ..."), so the
                # club group picks up the connective.
                club = re.split(r"\bTherefore,\s*", d["club"])[-1].strip()
                found.append({
                    "competition": comp, "article": title,
                    "club_in_article": club,
                    "venue": d["venue"].strip(),
                    "venue_city": d["city"].strip(),
                    "venue_country": (d["country"] or "").strip(),
                    "regular": d["old"].strip(),
                    "regular_city": d["oldcity"].strip(),
                    "reason": (d["why"] or prose.split(".")[0]).strip()[:90],
                })

        self.stdout.write(f"\n{len(found)} relocation(s) recorded across "
                          f"{len(ARTICLES) - fetch_failures} article(s)")
        if fetch_failures:
            self.stdout.write(self.style.ERROR(
                f"{fetch_failures} article(s) could not be READ. Their clubs are "
                f"missing from this report -- that is a fetch failure, not a clean "
                f"result. Re-run before trusting it."))

        # Match each footnote to a club we hold, by distinctive tokens. Article
        # names are short forms ("AGF", "KuPS", "Pafos") and ours are long
        # ("Aarhus Gymnastikforening", "KuPS Kuopio", "Pafos FC"), so equality
        # would match almost nothing.
        clubs = list(Team.objects.filter(is_national=False)
                     .exclude(european_competition="")
                     .select_related("stadium", "uefa_stadium"))
        agree, drift, unmatched = [], [], []

        for f in found:
            want = _tokens(f["club_in_article"])
            pool = [t for t in clubs if t.european_competition == f["competition"]]
            hits = [t for t in pool
                    if want and (want <= _tokens(t.name) or _tokens(t.name) <= want)]

            # Articles use the short form and we store the long one, so token
            # matching alone loses the abbreviations: "AGF" shares no word with
            # "Aarhus Gymnastikforening", "KuPS" none with "KuPS Kuopio" once
            # folded. Fall back to the CITY the footnote names as the club's
            # regular home, which the article always gives and we always hold.
            if len(hits) != 1:
                city = _tokens(f["regular_city"])
                hits = [t for t in pool
                        if city and t.city and city & _tokens(t.city.name)]
            if len(hits) != 1:
                f["candidates"] = sorted(t.name for t in hits)
                unmatched.append(f)
                continue

            t = hits[0]
            venue = t.uefa_stadium or t.stadium
            f["club"] = t.name
            f["id"] = t.pk
            f["we_publish"] = venue.name if venue else None
            f["uefa_stadium_set"] = bool(t.uefa_stadium_id)

            # Compare on the ground's IDENTITY, not just the label we happen to
            # store. A ground routinely has three names -- the article title, a
            # sponsor's, and a sponsor-free one UEFA insists on -- and we may hold
            # any of them. Pafos' ground is stored as "Limassol Arena", the article
            # calls it "Alphamega Stadium" and UEFA calls it "Limassol Stadium";
            # all three are the same place, and its stored wikipedia_url says so.
            # Without this, a correct row reads as drift and invites a "fix" that
            # would break it.
            ours = venue_tokens(f["we_publish"] or "")
            if venue and venue.wikipedia_url:
                slug = urllib.parse.unquote(
                    venue.wikipedia_url.rstrip("/").rsplit("/", 1)[-1]
                ).replace("_", " ")
                ours |= venue_tokens(slug)
            # venue_tokens, not _tokens: identity words only, or the shared word
            # "stadium" declares two different grounds to be the same one.
            theirs = venue_tokens(f["venue"])
            (agree if (ours and ours & theirs) else drift).append(f)

        if drift:
            self.stdout.write(self.style.ERROR(
                f"\n=== {len(drift)} club(s) DRIFTED: we publish the wrong ground ==="))
            for f in drift:
                self.stdout.write(f"\n  [{f['competition']}] {f['club']} (id={f['id']})")
                self.stdout.write(self.style.ERROR(
                    f"      we publish:  {f['we_publish']}"))
                self.stdout.write(self.style.SUCCESS(
                    f"      Europe at:   {f['venue']}, {f['venue_city']}"
                    + (f", {f['venue_country']}" if f.get("venue_country") else "")))
                self.stdout.write(f"      because:     {f['reason']}")

        if agree:
            self.stdout.write(self.style.SUCCESS(
                f"\n{len(agree)} relocation(s) already recorded correctly: "
                + ", ".join(f["club"] for f in agree)))

        if unmatched:
            self.stdout.write(self.style.WARNING(
                f"\n{len(unmatched)} footnote(s) could not be matched to a club we "
                f"hold in that competition -- check these BY HAND, a miss here looks "
                f"exactly like a clean result:"))
            for f in unmatched:
                self.stdout.write(
                    f"  [{f['competition']}] {f['club_in_article']!r} -> "
                    f"{f['venue']}, {f['venue_city']}"
                    + (f"   candidates: {f['candidates']}" if f["candidates"] else ""))

        # A club we have marked as displaced that the article does NOT mention is
        # the opposite error, and just as publishable: a stale relocation from a
        # previous season keeps the club in the wrong city all year.
        named = {f.get("id") for f in agree + drift}
        stale = [t for t in clubs if t.uefa_stadium_id and t.pk not in named]
        if stale:
            self.stdout.write(self.style.WARNING(
                f"\n{len(stale)} club(s) carry a uefa_stadium that this season's "
                f"article does not mention. Confirm they are still displaced:"))
            for t in stale:
                self.stdout.write(f"  {t.name} -> {t.uefa_stadium.name}")

        if o["json_out"]:
            with open(o["json_out"], "w", encoding="utf-8") as fh:
                json.dump({"drift": drift, "agree": agree,
                           "unmatched": unmatched,
                           "stale": [{"id": t.pk, "club": t.name,
                                      "uefa_stadium": t.uefa_stadium.name}
                                     for t in stale]},
                          fh, ensure_ascii=False, indent=1)
            self.stdout.write(f"\nwrote {o['json_out']}")

        if not drift and not unmatched:
            self.stdout.write(self.style.SUCCESS(
                "\nEvery relocation in the season articles is recorded."))
