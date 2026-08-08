"""
refresh_dead_crests
===================
Re-source club crests whose stored URL no longer loads.

Almost every crest points at Transfermarkt's CDN (tmssl.akamaized.net). Individual
assets there return a persistent 503 — Corum, AGF, Randers, SonderjyskE and Poli
Iasi all did — and the map then draws a bare coloured dot where a badge should be,
which is only ever noticed by eye, usually after publishing.

Resolution order, best licence first:
  1. Wikidata P154 (logo image)  -> Wikimedia Commons, freely licensed
  2. The club's Wikipedia article -> a local crest file, usually fair use

Both are checked against the club's OWN article, so a crest can't be borrowed from
a different club — the failure mode that once put a German crest on a Maltese side.

Usage:
    python -X utf8 manage.py refresh_dead_crests                 # report only
    python -X utf8 manage.py refresh_dead_crests --fix
    python -X utf8 manage.py refresh_dead_crests --league "SuperLiga" --fix
"""
import re
import time

import requests
from django.core.management.base import BaseCommand

from italiastadiaapp.models import Team

# Wikimedia asks for a descriptive agent with contact details; a generic one gets
# rate-limited once several crests are fetched in a burst.
UA = {"User-Agent": "stadiamap/1.0 (destavola.marco@gmail.com)"}
WD_API = "https://www.wikidata.org/w/api.php"
CROP_HINTS = ("logo", "crest", "badge", "emblem", "sigla", "wappen", "stemma")


class Command(BaseCommand):
    help = "Replace dead Transfermarkt crest URLs with Wikidata/Wikipedia ones."

    def add_arguments(self, p):
        p.add_argument("--fix", action="store_true", help="write changes")
        p.add_argument("--league", default="", help="limit to one league name")
        p.add_argument("--sleep", type=float, default=1.0,
                       help="pause between remote calls (Wikimedia rate limits bursts)")

    # ── helpers ──────────────────────────────────────────────────────────────
    def _alive(self, url):
        """A crest counts as alive only if the response is actually an image.

        Transfermarkt's CDN soft-blocks by returning HTTP 200 with a zero-byte
        body, so a status-code check calls a blocked crest healthy and the map
        still renders a bare dot. Size is the honest test.
        """
        if not url:
            return False
        try:
            r = requests.get(url, timeout=12, headers=UA)
            return r.status_code == 200 and len(r.content or b"") >= 100
        except Exception:
            return False

    def _wiki_host_title(self, team):
        """('en.wikipedia.org', 'FC Politehnica Iasi (2010)') from the team's URL."""
        m = re.match(r"https?://([^/]+)/wiki/(.+)$", team.wikipedia_url or "")
        if not m:
            return None, None
        from urllib.parse import unquote
        return m.group(1), unquote(m.group(2)).replace("_", " ")

    def _file_url(self, host, file_title):
        r = requests.get(f"https://{host}/w/api.php", timeout=25, headers=UA, params={
            "action": "query", "format": "json", "titles": file_title,
            "prop": "imageinfo", "iiprop": "url"}).json()
        for p in r.get("query", {}).get("pages", {}).values():
            u = (p.get("imageinfo") or [{}])[0].get("url")
            if u:
                return u.split("?")[0]
        return None

    def _from_wikidata(self, host, title):
        """P154 on the item the club's own article is linked to."""
        r = requests.get(f"https://{host}/w/api.php", timeout=25, headers=UA, params={
            "action": "query", "format": "json", "redirects": 1, "titles": title,
            "prop": "pageprops", "ppprop": "wikibase_item"}).json()
        qid = None
        for p in r.get("query", {}).get("pages", {}).values():
            qid = (p.get("pageprops") or {}).get("wikibase_item")
        if not qid:
            return None
        c = requests.get(WD_API, timeout=25, headers=UA, params={
            "action": "wbgetclaims", "entity": qid, "property": "P154",
            "format": "json"}).json()
        for cl in c.get("claims", {}).get("P154", []):
            try:
                fname = cl["mainsnak"]["datavalue"]["value"]
            except Exception:
                continue
            return self._file_url("commons.wikimedia.org", "File:" + fname)
        return None

    def _from_article(self, host, title):
        """A crest-looking image on the club's own article.

        Least reliable of the three and always reported for review: an article
        often carries HISTORICAL logos alongside the current one, and the images
        list is not ordered by prominence. On Poli Iasi this returned the club's
        2016 badge rather than the one actually in the infobox.
        """
        r = requests.get(f"https://{host}/w/api.php", timeout=25, headers=UA, params={
            "action": "query", "format": "json", "redirects": 1, "titles": title,
            "prop": "images", "imlimit": "max"}).json()
        for p in r.get("query", {}).get("pages", {}).values():
            for im in p.get("images", []):
                t = im["title"]
                low = t.lower()
                if any(k in low for k in CROP_HINTS) and "commons-logo" not in low \
                        and "wikidata" not in low and "kit " not in low:
                    return self._file_url(host, t)
        return None

    # ── main ─────────────────────────────────────────────────────────────────
    def handle(self, *a, **o):
        qs = Team.objects.select_related("league").exclude(is_national=True)
        if o["league"]:
            qs = qs.filter(league__name=o["league"])
        qs = qs.order_by("name")

        dead, fixed, unresolved = [], [], []
        self.stdout.write(f"Checking {qs.count()} clubs...")
        for t in qs:
            if self._alive(t.image_url):
                continue
            dead.append(t)
            host, title = self._wiki_host_title(t)
            if not host:
                unresolved.append((t, "no wikipedia_url"))
                continue
            url = None
            try:
                url = self._from_wikidata(host, title) or self._from_article(host, title)
            except Exception as e:
                unresolved.append((t, f"lookup failed: {e}"))
                continue
            time.sleep(o["sleep"])
            if not url:
                unresolved.append((t, "no crest on Wikidata or the article"))
                continue
            from_wikidata = "commons" in url
            src = "Commons (P154)" if from_wikidata else "Wikipedia article scan"
            style = self.style.SUCCESS if from_wikidata else self.style.WARNING
            note = "" if from_wikidata else "  <- CHECK: may be a historical logo"
            self.stdout.write(style(
                f"  {t.name}: {url.split('/')[-1]}  [{src}]{note}"))
            if o["fix"]:
                t.image_url = url
                t.image_credit = f"Crest via {src}; Transfermarkt copy unavailable."
                t.save(update_fields=["image_url", "image_credit"])
            fixed.append(t)

        self.stdout.write("")
        self.stdout.write(f"dead: {len(dead)}   resolved: {len(fixed)}   "
                          f"unresolved: {len(unresolved)}")
        for t, why in unresolved:
            self.stdout.write(self.style.WARNING(f"  UNRESOLVED {t.name} — {why}"))
        if fixed and not o["fix"]:
            self.stdout.write(self.style.WARNING("\nDry run. Re-run with --fix to write."))
        elif o["fix"]:
            self.stdout.write(self.style.WARNING(
                "\nRe-dump the fixture so this reaches production."))
