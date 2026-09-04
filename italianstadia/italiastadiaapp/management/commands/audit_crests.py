"""
audit_crests
============
Ask every club's own Wikipedia INFOBOX which badge it wears, and compare that to
the badge we actually ship. Reports; ``--fix`` re-points the ones it is sure about.

WHY THIS EXISTS. `refresh_dead_crests` only looks at clubs whose crest URL is
DEAD. A crest that downloads perfectly and shows the WRONG badge is invisible to
it -- and that is the common failure, not the rare one. Most crests in the
database were chosen by the last-resort ARTICLE SCAN, the one CLAUDE.md
documents as carrying two traps: MediaWiki returns an article's images in
alphabetical order, so a club that documents its crest history gets its OLDEST
badge; and a filename that dates itself is a retired badge. The infobox is the
authoritative source and was consulted for only a minority of them.

A reader on r/MapPorn asked "why is the KAA Gent badge their original?". It was
sourced from `K.A.A.GentOldLogo(ARAG).png` -- a filename that says "OldLogo" in
so many words. `is_historic` missed it because its pattern requires a separator
("old-logo", "old_logo"), and this one is camelCase. One reader caught one club;
this command asks the same question of all of them.

    python -X utf8 manage.py audit_crests                      # every club
    python -X utf8 manage.py audit_crests --uefa               # only clubs in Europe
    python -X utf8 manage.py audit_crests --league "Serie A"
    python -X utf8 manage.py audit_crests --json out.json      # machine-readable

VERDICTS, and what each is worth:

  OK          the shipped file and the infobox file are the same image
  HISTORIC    the shipped filename says it is a RETIRED badge -- always wrong
  MISMATCH    the infobox shows a DIFFERENT file. Usually wrong, but not always:
              an en-wiki fair-use upload and a Commons file can be two copies of
              one badge under different names, so this is a flag for a human to
              look at, not a verdict
  NO-INFOBOX  the article has no image parameter we can read; nothing to compare
  NO-CREST    we ship no badge for this club at all (it renders as a bare dot)

Only OK and HISTORIC are conclusions. The point of keeping MISMATCH separate is
that this project's recurring mistake is treating a heuristic as an answer.
"""
import io
import json
import os
import re
import unicodedata
import urllib.parse

import requests
from django.conf import settings
from django.core.management.base import BaseCommand

from italiastadiaapp.models import Team
from italiastadiaapp.management.commands.refresh_dead_crests import (
    is_historic, chunks,
)

UA = {"User-Agent": "stadiamap/1.0 (destavola.marco@gmail.com)"}
BATCH = 50

# camelCase retirement markers. `is_historic` in refresh_dead_crests requires a
# separator before the word ("old-logo", "old_logo", "old logo"), so a filename
# that runs the words together slips through -- which is exactly how
# `K.A.A.GentOldLogo(ARAG).png` shipped as KAA Gent's current crest.
#
# Case-SENSITIVE on purpose: the capital O is what makes this a word boundary in
# a camelCase name. Matching case-insensitively would fire on "GoldLogo".
_CAMEL_RETIRED = re.compile(
    r"Old(?:Logo|Crest|Badge|Emblem)|(?:Logo|Crest|Badge)Old|"
    r"Former(?:Logo|Crest|Badge|Emblem)|Historic(?:al)?(?:Logo|Crest|Badge)")


def looks_historic(fname):
    """is_historic(), plus the camelCase forms it cannot see."""
    fname = fname or ""
    return bool(is_historic(fname) or _CAMEL_RETIRED.search(fname))


def norm_file(name):
    """Compare filenames by identity, not by punctuation.

    'K.A.A.GentOldLogo(ARAG).png' and 'KAA Gent logo.svg' must come out
    different; 'KAA_Gent_logo.svg' and 'KAA Gent logo.svg' must come out the
    same. The extension is dropped because the same badge is routinely stored as
    both .svg and .png.
    """
    name = urllib.parse.unquote(name or "")
    name = name.rsplit("/", 1)[-1]
    name = re.sub(r"\.(svg|png|jpe?g|gif|webp)$", "", name, flags=re.I)
    name = unicodedata.normalize("NFKD", name.lower())
    return "".join(c for c in name if c.isalnum())


def title_of(url):
    """(wiki host, article/file title) for a Wikipedia or upload URL."""
    if not url:
        return None, None
    p = urllib.parse.urlparse(url)
    title = urllib.parse.unquote(p.path.rsplit("/", 1)[-1]).replace("_", " ")
    return p.netloc, (title or None)


# Same parameter grammar as refresh_dead_crests._INFOBOX_IMG. Duplicated rather
# than imported because that one is a private attribute on the other Command
# class, and reaching into it would couple two commands through a private name.
#
# `File\s*:` and the trailing `\s*` are not decoration. Editors write
# "| image = File: Logo FH Hafnarfjordur.svg" with a space after the colon, and
# a pattern that only accepts "File:" captures the literal text "File: Logo FH
# Hafnarfjordur.svg" as the filename -- which then resolves to nothing and is
# reported as a missing file rather than as a parse failure.
_INFOBOX_IMG = re.compile(
    r"^\s*\|\s*(?:image|logo|crest)\s*=\s*(?:\[\[)?(?:File\s*:|Image\s*:)?\s*"
    r"([^|\]\n{}\s][^|\]\n{}]*?)\s*(?:\|[^\]\n]*)?(?:\]\])?\s*$", re.I | re.M)


class Command(BaseCommand):
    help = "Compare every shipped club crest against its Wikipedia infobox."

    def add_arguments(self, p):
        p.add_argument("--league")
        p.add_argument("--country")
        p.add_argument("--uefa", action="store_true",
                       help="only clubs in a UEFA competition this season")
        p.add_argument("--json", dest="json_out")
        p.add_argument("--sleep", type=float, default=0.2)

    # -- wiki ---------------------------------------------------------------
    def _api(self, host, params):
        """One MediaWiki call.

        `format` is set HERE rather than by each caller. Omitting it makes the
        API answer in HTML, `r.json()` raises, and every club in the batch comes
        back with no infobox -- which this command then reports as NO-INFOBOX,
        i.e. a total fetch failure wearing the costume of a clean result. That
        is why `_fetch_failures` is counted and printed as an error below.
        """
        try:
            r = requests.get(f"https://{host}/w/api.php",
                             params={"format": "json", **params},
                             headers=UA, timeout=45)
            return r.json(), None
        except Exception as e:                                   # noqa: BLE001
            return {}, str(e)

    def _infobox(self, host, titles):
        """title -> the filename the article's own infobox renders as its crest.

        Unlike refresh_dead_crests this does NOT discard a historic answer. If
        the infobox itself points at a dated file we want to SEE that, rather
        than fall through and report the club as having no infobox crest.
        """
        out = {}
        for batch in chunks(titles, BATCH):
            data, err = self._api(host, {
                "action": "query", "redirects": 1, "formatversion": "2",
                "titles": "|".join(batch), "prop": "revisions",
                "rvprop": "content", "rvslots": "main", "rvsection": "0"})
            if err:
                self._fetch_failures += len(batch)
                self.stderr.write(f"  {host}: {err}")
                continue
            q = data.get("query", {})
            alias = {m["from"]: m["to"] for k in ("normalized", "redirects")
                     for m in q.get(k, [])}
            for page in q.get("pages", []):
                try:
                    txt = page["revisions"][0]["slots"]["main"]["content"]
                except Exception:                                # noqa: BLE001
                    continue
                m = _INFOBOX_IMG.search(txt)
                if not m:
                    continue
                fname = m.group(1).strip()
                if not fname or "." not in fname:
                    continue
                out[page.get("title")] = fname
            for src in batch:
                dst = alias.get(src)
                while dst and dst in alias:
                    dst = alias[dst]
                if dst and dst in out:
                    out[src] = out[dst]
        return out

    # -- local file ---------------------------------------------------------
    @staticmethod
    def _inspect(path):
        """Bytes, pixels and transparency of the badge we actually ship.

        Transparency is the cheap tell that a PHOTOGRAPH was installed instead of
        a crest: the Di Stefano portrait that once shipped as Real Madrid's badge
        was 0.0% transparent, and every genuine crest is comfortably above 10%.
        """
        try:
            from PIL import Image
            with open(path, "rb") as fh:
                raw = fh.read()
            im = Image.open(io.BytesIO(raw))
            w, h = im.size
            alpha = None
            if im.mode in ("RGBA", "LA") or "transparency" in im.info:
                a = im.convert("RGBA").getchannel("A")
                hist = a.histogram()
                alpha = round(100.0 * sum(hist[:200]) / float(w * h), 1)
            return {"bytes": len(raw), "w": w, "h": h, "transparent_pct": alpha}
        except Exception as e:                                   # noqa: BLE001
            return {"error": str(e)}

    def handle(self, *a, **o):
        qs = (Team.objects.filter(is_national=False)
              .select_related("league__country").order_by("name"))
        if o["league"]:
            qs = qs.filter(league__name=o["league"])
        if o["country"]:
            qs = qs.filter(league__country__name=o["country"])
        if o["uefa"]:
            qs = qs.exclude(european_competition="")
        teams = list(qs)
        self._fetch_failures = 0
        self.stdout.write(f"auditing {len(teams)} club(s)\n")

        # Group article titles by wiki host. A few clubs are only on their
        # native-language wiki, and Borussia-Park proved the English article can
        # simply not know about a change the German one records.
        by_host = {}
        for t in teams:
            host, title = title_of(t.wikipedia_url)
            if host and title:
                by_host.setdefault(host, {}).setdefault(title, []).append(t)

        infobox = {}
        for host, titles in by_host.items():
            self.stdout.write(f"  {host}: {len(titles)} article(s)")
            for title, fname in self._infobox(host, list(titles)).items():
                infobox[(host, title)] = fname

        crest_dir = os.path.join(settings.BASE_DIR, "italiastadiaapp",
                                 "static", "crests")
        if not os.path.isdir(crest_dir):
            crest_dir = os.path.join(settings.BASE_DIR, "static", "crests")

        rows = []
        for t in teams:
            host, title = title_of(t.wikipedia_url)
            ib = infobox.get((host, title))
            src_name = title_of(t.image_url)[1] if t.image_url else None
            shipped = t.crest_file or ""
            path = os.path.join(crest_dir, shipped) if shipped else ""

            if not shipped or not os.path.isfile(path):
                verdict = "NO-CREST"
            elif looks_historic(src_name or "") or looks_historic(shipped):
                verdict = "HISTORIC"
            elif ib and src_name and norm_file(ib) == norm_file(src_name):
                verdict = "OK"
            elif not ib:
                verdict = "NO-INFOBOX"
            else:
                verdict = "MISMATCH"

            rows.append({
                "id": t.pk, "club": t.name,
                "country": (t.league.country.name
                            if t.league and t.league.country else ""),
                "league": t.league.name if t.league else "",
                "uefa": t.european_competition or "",
                "verdict": verdict,
                "shipped_file": shipped,
                "source_file": src_name or "",
                "infobox_file": ib or "",
                "image_url": t.image_url or "",
                "wikipedia_url": t.wikipedia_url or "",
                "credit": (t.image_credit or "")[:140],
                "file": self._inspect(path) if path and os.path.isfile(path) else {},
            })

        order = ["HISTORIC", "NO-CREST", "MISMATCH", "NO-INFOBOX", "OK"]
        counts = {v: sum(1 for r in rows if r["verdict"] == v) for v in order}
        self.stdout.write("\n=== verdicts ===")
        for v in order:
            self.stdout.write(f"  {v:12} {counts[v]:5}")

        # A dead API looks EXACTLY like a clean run whose articles all lack an
        # infobox, so say so out loud. The first run of this command reported
        # 107 of 108 clubs as NO-INFOBOX because `format=json` was missing and
        # every response was HTML.
        if self._fetch_failures:
            self.stdout.write(self.style.ERROR(
                f"\n{self._fetch_failures} article(s) could not be FETCHED. Their "
                "NO-INFOBOX verdict means the wiki call failed, NOT that the "
                "article has no crest. Re-run before trusting this report."))

        for v in ("HISTORIC", "NO-CREST", "MISMATCH"):
            hits = [r for r in rows if r["verdict"] == v]
            if not hits:
                continue
            self.stdout.write(self.style.ERROR(f"\n--- {v} ({len(hits)}) ---"))
            for r in hits:
                tag = f"[{r['uefa']}] " if r["uefa"] else ""
                self.stdout.write(f"  {tag}{r['club']} ({r['country']})")
                self.stdout.write(
                    f"      ships:   {r['source_file'] or r['shipped_file']}")
                if r["infobox_file"]:
                    self.stdout.write(self.style.WARNING(
                        f"      infobox: {r['infobox_file']}"))

        if o["json_out"]:
            with open(o["json_out"], "w", encoding="utf-8") as fh:
                json.dump(rows, fh, ensure_ascii=False, indent=1)
            self.stdout.write(f"\nwrote {o['json_out']}")

        self.stdout.write(self.style.WARNING(
            "\nMISMATCH is a FLAG, not a verdict: a Commons file and an en-wiki "
            "fair-use upload can be the same badge under two names. Look at the "
            "images before changing anything."))
