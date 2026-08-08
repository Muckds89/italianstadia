"""
refresh_dead_crests
===================
Re-source club crests whose stored URL no longer serves an image.

Transfermarkt's CDN hosts 999 of our 1,034 crests and is currently soft-blocking
us: it answers HTTP 200 with a ZERO-BYTE body rather than an error status, so a
status-code check calls every crest healthy while the map draws bare dots.

Resolution order, best licence first:
  1. Wikidata P154 (logo image)   -> Wikimedia Commons, freely licensed
  2. The club's Wikipedia article -> a local crest file, usually fair use

Both are keyed off the club's OWN article, so a crest can never be borrowed from a
different club -- the failure that once put a German crest on a Maltese side.

EVERYTHING IS BATCHED. The first version of this command issued three requests per
club; across ~1,000 clubs Wikimedia rate-limited it and 927 of 976 lookups came
back as unparseable HTML ("Expecting value: line 1 column 1"). The MediaWiki and
Wikidata APIs both accept 50 titles or ids per call, which turns ~3,000 requests
into roughly 80. Never go back to per-club requests here.

Usage:
    python -X utf8 manage.py refresh_dead_crests                       # dry run
    python -X utf8 manage.py refresh_dead_crests --fix
    python -X utf8 manage.py refresh_dead_crests --league "SuperLiga" --fix
    python -X utf8 manage.py refresh_dead_crests --probe --fix   # re-test TM first
"""
import re
import time
import unicodedata
from collections import defaultdict
from urllib.parse import unquote

import requests
from django.core.management.base import BaseCommand

from italiastadiaapp.models import Team

UA = {"User-Agent": "stadiamap/1.0 (destavola.marco@gmail.com)"}
WD_API = "https://www.wikidata.org/w/api.php"
COMMONS = "commons.wikimedia.org"
BATCH = 50
CREST_HINTS = ("logo", "crest", "badge", "emblem", "sigla", "wappen", "stemma", "escudo")
NOT_CREST = ("commons-logo", "wikidata", "kit ", "kit_", "flag of", "icon",
             "edit-ltr", "symbol", "soccerball", "medal", "performance")


def norm(s):
    s = unicodedata.normalize("NFKD", (s or "").lower())
    return "".join(c for c in s if c.isalnum())


def chunks(seq, n):
    seq = list(seq)
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


class Command(BaseCommand):
    help = "Replace dead Transfermarkt crest URLs with Wikidata/Wikipedia ones."

    def add_arguments(self, p):
        p.add_argument("--fix", action="store_true", help="write changes")
        p.add_argument("--league", default="", help="limit to one league name")
        p.add_argument("--probe", action="store_true",
                       help="HTTP-test each stored crest first (slow; skip while a "
                            "host is known to be blocking)")
        p.add_argument("--sleep", type=float, default=0.3,
                       help="pause between BATCH calls, not per club")

    # ── batched API helpers ──────────────────────────────────────────────────
    def _api(self, host, params, sleep):
        params = dict(params, format="json", formatversion="2")
        try:
            r = requests.get(f"https://{host}/w/api.php", params=params,
                             headers=UA, timeout=40)
            time.sleep(sleep)
            if r.status_code != 200:
                return {}, f"HTTP {r.status_code}"
            return r.json(), None
        except ValueError:
            # Non-JSON means we are being throttled; the caller must back off
            # rather than record 50 clubs as "no crest found".
            return {}, "throttled (non-JSON response)"
        except Exception as e:
            return {}, f"{type(e).__name__}: {e}"

    def _pages(self, host, titles, props, sleep, extra=None):
        """Batched query over up to 50 titles, following continuation.

        `imlimit` is a per-QUERY cap, not per-page: ask for 15 articles' images in
        one call and the later pages come back with their image lists truncated or
        empty. That silently reported five Eredivisie clubs as having no crest when
        every one of them has a "<club> logo.svg". MediaWiki signals the shortfall
        with a `continue` token, so the only correct handling is to follow it and
        merge, which is what this loop does.
        """
        out, errs = {}, []
        for batch in chunks(titles, BATCH):
            params = {"action": "query", "redirects": 1, "prop": props,
                      "titles": "|".join(batch)}
            params.update(extra or {})
            cont, guard = {}, 0
            while True:
                data, err = self._api(host, dict(params, **cont), sleep)
                if err:
                    errs.append(err)
                    break
                q = data.get("query", {})
                alias = {}
                for k in ("normalized", "redirects"):
                    for m in q.get(k, []):
                        alias[m["from"]] = m["to"]
                for page in q.get("pages", []):
                    title = page.get("title")
                    prev = out.get(title)
                    if prev is None:
                        out[title] = page
                    else:
                        # merge the continued slice into what we already have
                        prev.setdefault("images", []).extend(page.get("images") or [])
                        if page.get("pageprops"):
                            prev["pageprops"] = page["pageprops"]
                for src in batch:
                    dst = alias.get(src)
                    while dst and dst in alias:
                        dst = alias[dst]
                    if dst and dst in out:
                        out[src] = out[dst]
                cont = data.get("continue") or {}
                guard += 1
                if not cont or guard > 25:
                    break
        return out, errs

    def _file_urls(self, host, file_titles, sleep):
        """Batched File: -> direct URL."""
        out = {}
        for batch in chunks(file_titles, BATCH):
            data, err = self._api(host, {
                "action": "query", "titles": "|".join(batch),
                "prop": "imageinfo", "iiprop": "url"}, sleep)
            if err:
                continue
            for page in data.get("query", {}).get("pages", []):
                ii = (page.get("imageinfo") or [{}])[0]
                if ii.get("url"):
                    out[page["title"]] = ii["url"].split("?")[0]
        return out

    def _p154(self, qids, sleep):
        """Batched Wikidata -> logo filename."""
        out = {}
        for batch in chunks(qids, BATCH):
            try:
                r = requests.get(WD_API, headers=UA, timeout=40, params={
                    "action": "wbgetentities", "ids": "|".join(batch),
                    "props": "claims", "format": "json"})
                time.sleep(sleep)
                data = r.json()
            except Exception:
                continue
            for qid, ent in (data.get("entities") or {}).items():
                for cl in (ent.get("claims") or {}).get("P154", []):
                    try:
                        out[qid] = cl["mainsnak"]["datavalue"]["value"]
                        break
                    except Exception:
                        pass
        return out

    @staticmethod
    def _pick_article_image(images, title):
        """Choose the likeliest crest from an article's image list.

        Matching on the club name ALONE is not safe. A club's article is full of
        files named after it that are not crests: an earlier version of this
        command wrote a golf-tournament photo as Eintracht Frankfurt's badge,
        graffiti as Gornik Zabrze's, a 1960 team photo as Newcastle's, and a
        pronunciation recording (De-FC_Augsburg.ogg) as Augsburg's. 109 clubs got
        photographs instead of crests.

        So a candidate must be BOTH plausibly a logo file and plausibly this club:
          * extension must be svg or png -- a crest is vector or flat art; jpg and
            gif on a club article are overwhelmingly photographs
          * and either the filename says logo/crest/..., or the stem matches the
            club name AND the file is an SVG (a photo is essentially never SVG)
        Anything weaker is left unresolved for a human, which is the safe failure.
        """
        want = norm(title)
        named_svg, keyworded = [], []
        for t in images:
            low = t.lower()
            if any(bad in low for bad in NOT_CREST):
                continue
            ext = low.rsplit(".", 1)[-1] if "." in low else ""
            if ext not in ("svg", "png"):
                continue
            stem = norm(t.split(":", 1)[-1].rsplit(".", 1)[0])
            name_match = stem and (
                stem == want or (len(stem) > 8 and stem in want)
                or (len(want) > 8 and want in stem))
            if any(k in low for k in CREST_HINTS):
                keyworded.append(t)
            elif name_match and ext == "svg":
                named_svg.append(t)
        return (keyworded or named_svg or [None])[0]

    # ── main ─────────────────────────────────────────────────────────────────
    def handle(self, *a, **o):
        sleep = o["sleep"]
        qs = Team.objects.select_related("league").exclude(is_national=True)
        if o["league"]:
            qs = qs.filter(league__name=o["league"])
        qs = list(qs.order_by("name"))

        if o["probe"]:
            self.stdout.write(f"Probing {len(qs)} stored crests...")
            targets = [t for t in qs if not self._alive(t.image_url)]
        else:
            # Suspect = not on Wikimedia at all, OR written by an earlier run of
            # this command in a form that cannot be a crest (a photo or an audio
            # file). jpg/gif/ogg on a club article are not badges.
            def suspect(t):
                u = (t.image_url or "").split("?")[0].lower()
                if not u:
                    return True
                if "wikimedia.org" not in u:
                    return True
                return not u.endswith((".svg", ".png"))
            targets = [t for t in qs if suspect(t)]
        self.stdout.write(f"{len(targets)} crests to re-source "
                          f"(of {len(qs)} clubs)\n")

        by_host = defaultdict(list)
        skipped = []
        for t in targets:
            m = re.match(r"https?://([^/]+)/wiki/(.+)$", t.wikipedia_url or "")
            if not m:
                skipped.append((t, "no wikipedia_url"))
                continue
            by_host[m.group(1)].append((t, unquote(m.group(2)).replace("_", " ")))

        resolved, unresolved, throttled = {}, [], []

        for host, pairs in by_host.items():
            titles = [p[1] for p in pairs]
            self.stdout.write(f"-- {host}: {len(titles)} articles")

            # 1. one batched pass gets BOTH the Wikidata id and the image list
            pages, errs = self._pages(host, titles, "pageprops|images", sleep,
                                      extra={"ppprop": "wikibase_item",
                                             "imlimit": "max"})
            if errs:
                throttled.extend(errs)

            qid_of, images_of = {}, {}
            for team, title in pairs:
                page = pages.get(title) or {}
                qid = (page.get("pageprops") or {}).get("wikibase_item")
                if qid:
                    qid_of[team.pk] = qid
                images_of[team.pk] = [i["title"] for i in (page.get("images") or [])]

            # 2. Wikidata P154 in batches, then Commons file -> URL in batches
            fname_of_qid = self._p154(sorted(set(qid_of.values())), sleep)
            commons_urls = self._file_urls(
                COMMONS, sorted({"File:" + f for f in fname_of_qid.values()}), sleep)

            # 3. whatever P154 could not answer falls back to the article images
            local_pick = {}
            for team, title in pairs:
                qid = qid_of.get(team.pk)
                fname = fname_of_qid.get(qid) if qid else None
                if fname and ("File:" + fname) in commons_urls:
                    resolved[team.pk] = (commons_urls["File:" + fname], "Commons (P154)")
                    continue
                pick = self._pick_article_image(images_of.get(team.pk, []), title)
                if pick:
                    local_pick[team.pk] = pick
            local_urls = self._file_urls(host, sorted(set(local_pick.values())), sleep)
            for pk, ftitle in local_pick.items():
                if ftitle in local_urls:
                    resolved[pk] = (local_urls[ftitle], "Wikipedia article scan")

        # ── report + write ───────────────────────────────────────────────────
        wrote = 0
        for t in targets:
            if t.pk in resolved:
                url, src = resolved[t.pk]
                if o["fix"]:
                    t.image_url = url
                    t.image_credit = f"Crest via {src}; Transfermarkt copy unavailable."
                    t.save(update_fields=["image_url", "image_credit"])
                    wrote += 1
            else:
                unresolved.append((t, "no crest on Wikidata or the article"))
        unresolved.extend(skipped)

        self.stdout.write("")
        self.stdout.write(f"resolved: {len(resolved)}   unresolved: {len(unresolved)}"
                          f"   written: {wrote}")
        if throttled:
            self.stdout.write(self.style.ERROR(
                f"\n{len(throttled)} batch(es) FAILED — results are incomplete, "
                f"re-run. First: {throttled[0]}"))
        by_reason = defaultdict(list)
        for t, why in unresolved:
            by_reason[why].append(t.name)
        for why, names in by_reason.items():
            self.stdout.write(self.style.WARNING(f"\n{len(names)} — {why}:"))
            self.stdout.write("  " + ", ".join(sorted(names)[:40])
                              + (" ..." if len(names) > 40 else ""))
        if resolved and not o["fix"]:
            self.stdout.write(self.style.WARNING("\nDry run. Re-run with --fix."))
        elif wrote:
            self.stdout.write(self.style.WARNING(
                "\nRe-dump the fixture so this reaches production."))

    def _alive(self, url):
        """Alive only if the response is actually an image: Transfermarkt
        soft-blocks with 200 + zero bytes, which a status check calls healthy."""
        if not url:
            return False
        try:
            r = requests.get(url, timeout=12, headers=UA)
            return r.status_code == 200 and len(r.content or b"") >= 100
        except Exception:
            return False
