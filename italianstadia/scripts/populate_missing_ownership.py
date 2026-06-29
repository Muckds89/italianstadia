"""Backfill ownership for stadiums where ownership=UNKNOWN, using the same
primary + native-language Wikipedia logic the scraper uses. WRITES to the DB.

Usage:  python -X utf8 scripts/populate_missing_ownership.py            (apply)
        python -X utf8 scripts/populate_missing_ownership.py --dry-run  (report only)
"""
import sys
import time
import requests
from bs4 import BeautifulSoup

from populate_data_from_transfermrkt import (
    wiki_lang, infobox_labels, get_infobox_value, fetch_langlink,
    classify_ownership, COUNTRY_WIKI_LANG,
)
from italiastadiaapp.models import Stadium

UA = {"User-Agent": "stadiamap/1.0 (destavola.marco@gmail.com)"}


def soup_for(url):
    try:
        r = requests.get(url, headers=UA, timeout=25)
        return BeautifulSoup(r.text, "html.parser") if r.status_code == 200 else None
    except Exception:
        return None


def owner_from(url, lang):
    s = soup_for(url)
    if not s:
        return None
    return get_infobox_value(s, infobox_labels("owner", lang) + infobox_labels("operator", lang))


def main():
    dry = "--dry-run" in sys.argv
    qs = (Stadium.objects.filter(ownership="UNKNOWN")
          .exclude(wikipedia_url="").exclude(wikipedia_url__isnull=True)
          .select_related("city").order_by("id"))
    filled = still = 0
    for s in qs:
        url, lang = s.wikipedia_url, wiki_lang(s.wikipedia_url)
        country = s.city.country if s.city else ""
        native = COUNTRY_WIKI_LANG.get(country)

        owner = owner_from(url, lang)
        src = "primary"
        if not owner and native and native != lang:
            nu = fetch_langlink(url, native)
            if nu:
                owner = owner_from(nu, native)
                src = f"native:{native}"
        time.sleep(0.3)

        if owner:
            ownership = classify_ownership(owner)
            print(f"[{s.id}] {s.name[:34]:<34} {src:<11} -> {ownership:<8} ({owner[:38]})")
            if not dry:
                s.owner_raw = owner
                s.ownership = ownership
                s.save(update_fields=["owner_raw", "ownership"])
            filled += 1
        else:
            still += 1

    print(f"\n{'(dry-run) ' if dry else ''}Resolved & {'would-set' if dry else 'set'}: {filled} | "
          f"still UNKNOWN (no owner in en/native): {still}")


if __name__ == "__main__":
    main()
