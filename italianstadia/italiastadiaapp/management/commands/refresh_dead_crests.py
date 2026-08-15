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

# A crest filename that encodes a date RANGE ("Anderlecht 1933-1959"), calls
# itself former, or is a centenary mark ("Feyenoord logo 100 years") describes a
# badge the club NO LONGER USES.
#
# This matters because MediaWiki returns an article's images in ALPHABETICAL
# order and the picker used to take the first keyword match. Big clubs document
# their crest history, and those files sort early: "Athletic Club crest 1901.png"
# beat "Club Athletic Bilbao logo.svg", which was sitting in the same list at
# position 6. That is a systematic bias toward the OLDEST badge, not bad luck --
# it put a 1902 logo on MSV Duisburg and a 1933 one on Anderlecht.
#
# A CLOSED range is historic; an OPEN one ("2015-heden", "2021-", "2025-") is
# the badge in use today, so the closing year is what disqualifies a range.
_YEAR = r"(?:1[89]\d\d|20[0-2]\d)"
_DASH = "[-‐‑‒–—―]"
_CLOSED = _YEAR + r"\s*" + _DASH + r"\s*(?:" + _YEAR + r"|\d\d)(?!\d)"
_OPEN = _YEAR + r"\s*" + _DASH + r"\s*(?!\d)"
# "old logo"/"old crest" carry no date at all, so the range test never saw
# them: Newcastle United was on "NUFC - Old Crest - Magpie.png" and West
# Bromwich on "West-Bromwich-Albion-F.C.-old-logo.png".
_RETIRED_WORD = (r"former[_ ]logo|logo[_ ]avant|avant[_ ]1|jahre"
                 r"|old[_ -](?:logo|crest|badge|emblem)"
                 r"|(?:logo|crest|badge)[_ -]old")
_CENTENARY = r"[_ ]100[_ ](?:years|jaar|lat|anni)|[_ ]100[_ ]\d"
HISTORIC = re.compile("|".join((_CLOSED, _RETIRED_WORD, _CENTENARY)), re.I)
_HAS_OPEN = re.compile(_OPEN)
_HAS_WORD = re.compile("|".join((_RETIRED_WORD, _CENTENARY)), re.I)


def is_historic(fname):
    """True when the filename says this badge is RETIRED.

    Ajax readopted a 1928 badge in 2025 and the file records both spans
    ("1928-1991, 2025-"). A closed range next to an open one is a RETURN to the
    old badge, not a retirement of it, so the open span wins -- unless the name
    also says "former"/"avant", which is unambiguous.
    """
    fname = fname or ""
    if _HAS_WORD.search(fname):
        return True
    if not HISTORIC.search(fname):
        return False
    return not _HAS_OPEN.search(fname)


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

    # ── infobox: the club's own answer ───────────────────────────────────────
    # The value must START with a non-space: "| image = " with nothing after it is
    # a blank parameter, and a lazy group would otherwise capture the pad space and
    # report an empty filename as a successful read.
    _INFOBOX_IMG = re.compile(
        r"^\s*\|\s*(?:image|logo|crest)\s*=\s*(?:\[\[)?(?:File:|Image:)?"
        r"([^|\]\n{}\s][^|\]\n{}]*?)\s*$", re.I | re.M)

    def _infobox_files(self, host, titles, sleep):
        """Map article title -> the file its infobox displays as the club crest.

        This is the AUTHORITATIVE source and is tried before Wikidata and before
        any keyword scan. Wikidata P154 is simply absent for a lot of big clubs --
        Real Madrid and Athletic Club both lack it -- which is what pushed them
        onto the article scan and its alphabetical-first bug in the first place.
        The infobox is never absent, is what the article itself renders, and is
        kept current by editors, so it answered all 15 clubs correctly on the
        first attempt where P154 answered none.

        Only section 0 is requested: the infobox is in the lead, and full article
        wikitext for 50 clubs is megabytes of payload for one parameter.
        """
        out = {}
        for batch in chunks(titles, BATCH):
            data, err = self._api(host, {
                "action": "query", "redirects": 1, "formatversion": "2",
                "titles": "|".join(batch), "prop": "revisions",
                "rvprop": "content", "rvslots": "main", "rvsection": "0"}, sleep)
            if err:
                continue
            q = data.get("query", {})
            alias = {}
            for k in ("normalized", "redirects"):
                for m in q.get(k, []):
                    alias[m["from"]] = m["to"]
            for page in q.get("pages", []):
                try:
                    txt = page["revisions"][0]["slots"]["main"]["content"]
                except Exception:
                    continue
                m = self._INFOBOX_IMG.search(txt)
                if not m:
                    continue
                fname = m.group(1).strip()
                # "image = " with an empty value, or a template call, is not a file
                if not fname or "." not in fname or is_historic(fname):
                    continue
                out[page.get("title")] = fname
            for src in batch:
                dst = alias.get(src)
                while dst and dst in alias:
                    dst = alias[dst]
                if dst and dst in out:
                    out[src] = out[dst]
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

        Passing those two tests is still not enough to pick a WINNER. This used to
        return keyworded[0], and MediaWiki returns images in ALPHABETICAL order, so
        the first hint match on a club that documents its crest history is its
        oldest badge: Anderlecht got its 1933 crest, MSV Duisburg its 1902 one, and
        Athletic Club its 1901 one while "Club Athletic Bilbao logo.svg" sat in the
        same list unpicked. Candidates are therefore SCORED, retired badges are
        dropped outright, and alphabetical position decides nothing.
        """
        want = norm(title)
        scored = []
        for t in images:
            low = t.lower()
            if any(bad in low for bad in NOT_CREST):
                continue
            ext = low.rsplit(".", 1)[-1] if "." in low else ""
            if ext not in ("svg", "png"):
                continue
            base = t.split(":", 1)[-1]
            if is_historic(base):
                continue
            stem = norm(base.rsplit(".", 1)[0])
            name_match = stem and (
                stem == want or (len(stem) > 8 and stem in want)
                or (len(want) > 8 and want in stem))
            keyworded = any(k in low for k in CREST_HINTS)
            if not keyworded and not (name_match and ext == "svg"):
                continue
            score = 0
            score += 4 if keyworded else 0
            score += 3 if name_match else 0
            score += 2 if ext == "svg" else 0        # vector = the club's own mark
            # A bare year with no range ("Escudo Real Madrid 1908") is a dated
            # badge even though it names no end date.
            score -= 5 if re.search(r"(?:1[89]\d\d|20[01]\d)(?!\d)", base) else 0
            scored.append((score, t))
        if not scored:
            return None
        # sort by score only; ties keep MediaWiki order, which is arbitrary but
        # stable, so a re-run cannot silently swap one club's crest for another.
        scored.sort(key=lambda s: -s[0])
        return scored[0][1]

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

        # A crest deliberately cleared as WRONG must not be re-picked from the same
        # article on the next run. Acerbis (a kit manufacturer) and Doosan (a
        # sponsor) were cleared once and silently came back, because the article
        # scan has no memory of a human decision. image_credit carries that memory.
        held = [t for t in targets if (t.image_credit or "").startswith("No verified crest")]
        if held:
            targets = [t for t in targets if t not in held]
            self.stdout.write(self.style.WARNING(
                f"holding {len(held)} club(s) previously cleared as wrong: "
                + ", ".join(sorted(t.name for t in held)[:8])))
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

            # 2. the club article's own infobox -- the authoritative answer
            infobox = self._infobox_files(host, titles, sleep)

            # 3. Wikidata P154 in batches, then Commons file -> URL in batches
            fname_of_qid = self._p154(sorted(set(qid_of.values())), sleep)
            commons_urls = self._file_urls(
                COMMONS, sorted({"File:" + f for f in fname_of_qid.values()}), sleep)

            # 4. whatever the first two could not answer falls back to the images
            local_pick = {}
            for team, title in pairs:
                ib = infobox.get(title)
                if ib:
                    local_pick[team.pk] = "File:" + ib
                    continue
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
