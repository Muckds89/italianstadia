"""Read-only audit: for every Stadium with ownership=UNKNOWN, check whether a
re-scrape WOULD resolve the owner — first from its own Wikipedia page (localized
infobox labels), then via the native-language langlink fallback. Writes a CSV so
the wins/misses can be reviewed before committing to a full re-scrape.

Usage:  python -X utf8 scripts/audit_missing_ownership.py
        python -X utf8 scripts/audit_missing_ownership.py --limit 20   (quick sample)
No DB writes. Output: audit_missing_ownership.csv
"""
import csv
import sys
import time
import requests
from bs4 import BeautifulSoup

# Reuse the exact extraction logic the scraper uses, so the audit predicts the
# real re-scrape result (django.setup runs on import).
from populate_data_from_transfermrkt import (
    wiki_lang, infobox_labels, get_infobox_value, fetch_langlink,
    classify_ownership, COUNTRY_WIKI_LANG,
)
from italiastadiaapp.models import Stadium

UA = {"User-Agent": "stadiamap/1.0 (destavola.marco@gmail.com)"}


def soup_for(url):
    try:
        r = requests.get(url, headers=UA, timeout=25)
        if r.status_code != 200:
            return None
        return BeautifulSoup(r.text, "html.parser")
    except Exception:
        return None


def owner_from(url, lang):
    soup = soup_for(url)
    if not soup:
        return None
    return get_infobox_value(soup, infobox_labels("owner", lang) + infobox_labels("operator", lang))


def main():
    limit = None
    if "--limit" in sys.argv:
        limit = int(sys.argv[sys.argv.index("--limit") + 1])

    qs = (Stadium.objects.filter(ownership="UNKNOWN")
          .exclude(wikipedia_url="").exclude(wikipedia_url__isnull=True)
          .select_related("city").order_by("id"))
    if limit:
        qs = qs[:limit]

    rows = []
    n_primary = n_native = n_still = 0
    for s in qs:
        url = s.wikipedia_url
        lang = wiki_lang(url)
        country = s.city.country if s.city else ""
        native_lang = COUNTRY_WIKI_LANG.get(country)

        owner = owner_from(url, lang)
        source = "primary" if owner else ""
        native_url = ""

        if not owner and native_lang and native_lang != lang:
            native_url = fetch_langlink(url, native_lang) or ""
            if native_url:
                owner = owner_from(native_url, native_lang)
                if owner:
                    source = f"native:{native_lang}"
        time.sleep(0.3)

        ownership = classify_ownership(owner) if owner else "UNKNOWN"
        if source == "primary":
            n_primary += 1
        elif source.startswith("native"):
            n_native += 1
        else:
            n_still += 1

        rows.append({
            "id": s.id, "name": s.name, "country": country,
            "page_lang": lang, "native_lang": native_lang or "",
            "owner_found": owner or "", "source": source or "none",
            "would_be": ownership, "native_url": native_url,
            "wikipedia_url": url,
        })
        print(f"[{s.id}] {s.name[:34]:<34} {source or 'STILL UNKNOWN':<12} "
              f"-> {ownership}  {('('+owner[:40]+')') if owner else ''}")

    out = "audit_missing_ownership.csv"
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()) if rows else [])
        w.writeheader()
        w.writerows(rows)

    total = len(rows)
    print("\n==== SUMMARY ====")
    print(f"Audited: {total} UNKNOWN-ownership stadiums with a wiki link")
    print(f"  resolved from PRIMARY page : {n_primary}")
    print(f"  resolved from NATIVE page  : {n_native}")
    print(f"  still UNKNOWN              : {n_still}")
    print(f"Written -> {out}")


if __name__ == "__main__":
    main()
