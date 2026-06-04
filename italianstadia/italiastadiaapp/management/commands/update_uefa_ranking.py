"""
Fetches the UEFA 5-year country coefficient ranking from Wikipedia and
updates Country.uefa_rank in the database.

Usage:
    python manage.py update_uefa_ranking

Run once after UEFA publish new coefficients (typically June/July each year).

Table structure (verified 2026-06):
  Row 0: header  — [Ranking (colspan 3)] [Member association] [Coefficient ...]
  Row 1: sub-hdr — [current yr] [prev yr] [Mvmt] [season cols ...]
  Row 2+: data   — cells[0]=rank  cells[1]=prev_rank  cells[2]=movement
                   cells[3]="England(L,C,LC)"  cells[4+]=season coefficients
"""
import requests
from bs4 import BeautifulSoup
from django.core.management.base import BaseCommand
from italiastadiaapp.models import Country

URL = "https://en.wikipedia.org/wiki/UEFA_coefficient"
HEADERS = {"User-Agent": "StadiaOfEurope/1.0 (learning project)"}

# Wikipedia association name → our Country.name where they differ.
NAME_MAP = {
    "Türkiye": "Turkey",
    "Bosnia & Herzegovina": "Bosnia and Herzegovina",
    "North Macedonia": "North Macedonia",
    "Kosovo": "Kosovo",
}


def _find_ranking_table(soup):
    """Find the men's current country ranking table by header signature."""
    for table in soup.find_all("table", class_="wikitable"):
        rows = table.find_all("tr")
        if not rows:
            continue
        header_text = " ".join(c.get_text(" ", strip=True) for c in rows[0].find_all(["th", "td"]))
        if "Ranking" in header_text and "Member association" in header_text and "Coefficient" in header_text:
            return table
    return None


def _parse_name(cell):
    """Extract plain country name from a cell like 'England(L,C,LC[c])'.

    Cells contain a flag <img> link (no text) followed by a text link.
    Iterate all <a> tags and return the first with non-empty text content.
    Fall back to splitting the full cell text on '(' if no text link found.
    """
    for link in cell.find_all("a"):
        name = link.get_text(strip=True)
        if name:
            return name
    return cell.get_text(strip=True).split("(")[0].strip()


class Command(BaseCommand):
    help = "Update Country.uefa_rank from the Wikipedia UEFA 5-year country coefficient table"

    def handle(self, *args, **options):
        self.stdout.write("Fetching UEFA country ranking from Wikipedia...")
        try:
            resp = requests.get(URL, headers=HEADERS, timeout=20)
            resp.raise_for_status()
        except Exception as exc:
            self.stderr.write(f"ERROR fetching page: {exc}")
            return

        soup = BeautifulSoup(resp.text, "html.parser")
        table = _find_ranking_table(soup)

        if not table:
            self.stderr.write("ERROR: Could not locate the country ranking table.")
            return

        updated = 0
        skipped = []
        rows = table.find_all("tr")

        # Skip rows 0 and 1 (main header + sub-header)
        for row in rows[2:]:
            cells = row.find_all(["td", "th"])
            if len(cells) < 4:
                continue

            rank_text = cells[0].get_text(strip=True)
            if not rank_text.isdigit():
                continue
            rank = int(rank_text)

            wiki_name = _parse_name(cells[3])
            if not wiki_name:
                continue
            db_name = NAME_MAP.get(wiki_name, wiki_name)

            try:
                country = Country.objects.get(name=db_name)
                country.uefa_rank = rank
                country.save(update_fields=["uefa_rank"])
                self.stdout.write(f"  {rank:3}. {db_name}")
                updated += 1
            except Country.DoesNotExist:
                skipped.append(f"{rank}. {wiki_name!r} (not in DB as {db_name!r})")

        self.stdout.write(self.style.SUCCESS(f"\nUpdated {updated} countries."))
        if skipped:
            self.stdout.write(self.style.WARNING("Skipped (association not in DB — add when scraped):"))
            for s in skipped:
                self.stdout.write(f"  {s}")
