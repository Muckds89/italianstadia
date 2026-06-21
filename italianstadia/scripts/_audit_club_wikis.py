"""Audit team AND stadium wikipedia_url values in a scrape JSON file.

Flags, per team and per stadium:
  MISSING  - wikipedia_url is empty (the scrape never found one)
  DEAD     - the article does not exist
  SUSPECT  - the article exists but is the wrong KIND of page:
               * a team link that is not a football-club article
                 (resolves to a city / region / concept page), or
               * a stadium link that is not a venue article.

Usage: python -X utf8 scripts/_audit_club_wikis.py <file.json> [...]
       add --quiet to print ONLY problems (and the per-file header).
"""
import json, sys, time, urllib.parse, requests

UA = {"User-Agent": "stadiamap/1.0 (destavola.marco@gmail.com)"}


def _api_for(url):
    """Wikipedia API endpoint for the URL's own host (en, it, …) — a link to
    it.wikipedia.org must be checked against the Italian wiki, not the English one."""
    host = urllib.parse.urlparse(url).netloc or "en.wikipedia.org"
    return f"https://{host}/w/api.php"


def page_info(title, api="https://en.wikipedia.org/w/api.php"):
    """Return (canonical_title, categories_blob, exists) following redirects."""
    title = urllib.parse.unquote(title)  # API wants decoded UTF-8, not %C3%BC
    for attempt in range(4):
        try:
            r = requests.get(api, headers=UA, params={
                "action": "query", "redirects": 1, "format": "json",
                "prop": "categories", "cllimit": "max", "titles": title,
            }, timeout=30)
            data = r.json()
            break
        except Exception:
            time.sleep(2 * (attempt + 1))
    else:
        return None, "[APIFAIL]", False
    page = next(iter(data["query"]["pages"].values()))
    if "missing" in page:
        return None, "", False
    cats = " ".join(c["title"].lower() for c in page.get("categories", []))
    return page["title"], cats, True


def last_segment(url):
    return urllib.parse.unquote(url.rsplit("/", 1)[-1])


BROWSER_UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
              "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"}


def tm_status(url):
    """HTTP-check a Transfermarkt URL. 502/503/504 are transient (TM under load) so
    retry before reporting; only a persistent non-2xx (esp. 404 = wrong verein id) is
    a real error. Returns 'OK', 'DEAD-404', 'BUSY-5xx', or 'ERR'."""
    if not url:
        return "MISSING"
    last = None
    for attempt in range(4):
        try:
            r = requests.get(url, headers=BROWSER_UA, allow_redirects=True, timeout=25)
            last = r.status_code
            if r.status_code == 200:
                return "OK"
            if r.status_code == 404:
                return "DEAD-404"
            if r.status_code in (502, 503, 504):
                time.sleep(3 * (attempt + 1))
                continue
            return f"HTTP-{r.status_code}"
        except Exception:
            time.sleep(3 * (attempt + 1))
    return "BUSY-5xx" if last in (502, 503, 504) else "ERR"


def classify(url, kind):
    """kind = 'club' or 'venue'. Returns (status, canonical_or_note)."""
    if not url or not url.strip():
        return "MISSING", "(empty)"
    api = _api_for(url)
    canon, cats, exists = page_info(url.rsplit("/", 1)[-1], api)
    if cats == "[APIFAIL]":
        return "APIFAIL", last_segment(url)
    if not exists:
        return "DEAD", last_segment(url)
    # Category names are English-specific; for other-language wikis we can only
    # confirm the page exists (avoids false "SUSPECT" on valid it/de/es articles).
    if "en.wikipedia.org" not in api:
        return "OK", (canon or last_segment(url))
    if kind == "club":
        # Accept multi-sport societies (Icelandic clubs), reserve/B teams and
        # generic "sports club" cats too — only city/region/person/concept pages
        # (which carry none of these) should fall through as SUSPECT.
        ok = any(w in cats for w in (
            "football club", "football clubs", "football teams",
            "sports club", "sports clubs", "multi-sport", "reserve team",
            "football academies", "women's football"))
    else:  # venue
        title = (canon or "").lower()
        ok = any(w in cats for w in ("stadium", "venue", "arena", "football grounds",
                                     "sports grounds")) \
            or any(w in title for w in ("stadium", "arena", "stadion", "park",
                                        "ground", "field", "estadi", "stade"))
    return ("OK" if ok else "SUSPECT"), (canon or last_segment(url))


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    quiet = "--quiet" in sys.argv
    do_tm = "--tm" in sys.argv  # also HTTP-check Transfermarkt links (slower)
    grand = 0
    for path in args:
        d = json.load(open(path, encoding="utf-8"))
        print(f"\n===== {path} =====")
        problems = 0
        for t in d["teams"]:
            ts, tinfo = classify(t.get("wikipedia_url", ""), "club")
            time.sleep(0.25)
            st = t.get("stadium") or {}
            ss, sinfo = classify(st.get("wikipedia_url", ""), "venue")
            time.sleep(0.25)
            tm = tm_status(t.get("transfermarkt_url", "")) if do_tm else "OK"
            bad = ts != "OK" or ss != "OK" or tm not in ("OK", "BUSY-5xx")
            if bad:
                problems += 1
            if bad or not quiet:
                tflag = "" if ts == "OK" else f"  <-- TEAM {ts}"
                sflag = "" if ss == "OK" else f"  <-- STADIUM {ss}"
                print(f"{t['name']:<24} team:{tinfo}{tflag}")
                print(f"{'':<24} stad:{st.get('name','?')} -> {sinfo}{sflag}")
                if do_tm and tm not in ("OK", "BUSY-5xx"):
                    print(f"{'':<24} TM:{t.get('transfermarkt_url','')}  <-- {tm}")
        print(f"  -> {problems} team(s) with a problem")
        grand += problems
    print(f"\nTOTAL teams with problems: {grand}")


if __name__ == "__main__":
    main()
