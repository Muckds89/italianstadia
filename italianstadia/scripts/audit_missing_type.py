"""Read-only audit: for every Stadium with no stadium_type, scan its Wikipedia
page (primary + native-language langlink) for roof signals and PROPOSE
OPEN / CLOSED / RETRACTABLE, for the roof-based insight.

Heuristic (conservative — only positive evidence changes the default):
  RETRACTABLE : "retractable roof", "convertible roof", "sliding roof", "açılır çatı",
                "раздвижн" (ru), "ausfahrbar" (de) …
  CLOSED      : "domed", "dome", "fully enclosed", "indoor", "fully covered roof" …
  OPEN        : default for a normal football ground (no enclosing-roof signal).
The point of the audit is to surface the RARE roofed/retractable grounds; the
rest are proposed OPEN with low confidence for review.

Usage:  python -X utf8 scripts/audit_missing_type.py [--limit N]
No DB writes. Output: audit_missing_type.csv
"""
import csv
import sys
import time
import requests
from bs4 import BeautifulSoup

from populate_data_from_transfermrkt import wiki_lang, fetch_langlink, COUNTRY_WIKI_LANG
from italiastadiaapp.models import Stadium
from django.db.models import Q

UA = {"User-Agent": "stadiamap/1.0 (destavola.marco@gmail.com)"}

RETRACTABLE = ("retractable roof", "convertible roof", "sliding roof", "movable roof",
               "açılır kapanır çatı", "açılır çatı", "ausfahrbares dach", "раздвижн",
               "tetto retrattile", "techo retráctil", "toit rétractable")
CLOSED = ("domed stadium", "geodesic dome", "fully enclosed", "fully-enclosed", "indoor arena",
          "indoor stadium", "fixed closed roof", "enclosed roof", "куполь", "kapalı stadyum",
          "estadio cubierto", "stadio coperto")


def page_text(url):
    try:
        r = requests.get(url, headers=UA, timeout=25)
        if r.status_code != 200:
            return ""
        soup = BeautifulSoup(r.text, "html.parser")
        ib = soup.find("table", class_="infobox") or soup.find("table", class_="vcard")
        intro = " ".join(p.get_text(" ", strip=True) for p in soup.select("div.mw-parser-output > p")[:4])
        return ((ib.get_text(" ", strip=True) if ib else "") + " " + intro).lower()
    except Exception:
        return ""


def classify_type(text):
    if not text:
        return None, ""
    if any(w in text for w in RETRACTABLE):
        return "RETRACTABLE", next(w for w in RETRACTABLE if w in text)
    if any(w in text for w in CLOSED):
        return "CLOSED", next(w for w in CLOSED if w in text)
    return None, ""


def main():
    limit = int(sys.argv[sys.argv.index("--limit") + 1]) if "--limit" in sys.argv else None
    qs = (Stadium.objects.filter(Q(stadium_type="") | Q(stadium_type__isnull=True))
          .exclude(wikipedia_url="").exclude(wikipedia_url__isnull=True)
          .select_related("city").order_by("id"))
    if limit:
        qs = qs[:limit]

    rows = []
    counts = {"RETRACTABLE": 0, "CLOSED": 0, "OPEN(default)": 0}
    for s in qs:
        url = s.wikipedia_url
        lang = wiki_lang(url)
        country = s.city.country if s.city else ""
        native_lang = COUNTRY_WIKI_LANG.get(country)

        text = page_text(url)
        typ, evidence = classify_type(text)
        source = "primary" if typ else ""

        if not typ and native_lang and native_lang != lang:
            nu = fetch_langlink(url, native_lang)
            if nu:
                typ, evidence = classify_type(page_text(nu))
                if typ:
                    source = f"native:{native_lang}"
        time.sleep(0.3)

        proposed = typ or "OPEN"
        key = typ if typ else "OPEN(default)"
        counts[key] = counts.get(key, 0) + 1
        rows.append({
            "id": s.id, "name": s.name, "country": country,
            "proposed_type": proposed, "confidence": "high" if typ else "low(default)",
            "evidence": evidence, "source": source or "default",
            "wikipedia_url": url,
        })
        if typ:
            print(f"[{s.id}] {s.name[:40]:<40} -> {proposed}  ({evidence}) [{source}]")

    with open("audit_missing_type.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()) if rows else [])
        w.writeheader()
        w.writerows(rows)

    print("\n==== SUMMARY ====")
    print(f"Audited: {len(rows)} stadiums with no roof type")
    for k, v in counts.items():
        print(f"  {k}: {v}")
    print("Roofed/retractable candidates are 'high' confidence; the rest default to OPEN "
          "(review audit_missing_type.csv before any write).")


if __name__ == "__main__":
    main()
