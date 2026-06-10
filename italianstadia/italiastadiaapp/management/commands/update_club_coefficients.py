"""
Fetch UEFA 5-year club coefficients from Wikipedia and update Team.uefa_coefficient.

Usage:
    python manage.py update_club_coefficients

Run once after UEFA publish new coefficients (typically June/July each year).
Only clubs that have played in CL/EL/Conference League in the past 5 seasons
receive a coefficient — all others stay NULL, which is the correct representation.

Table structure (Wikipedia "UEFA coefficient" page, "Club coefficients" section):
  Rows contain: rank | club name link | country flag | coefficient (points) | ...
"""
import requests
from bs4 import BeautifulSoup
from django.core.management.base import BaseCommand
from italiastadiaapp.models import Team

URL = "https://en.wikipedia.org/wiki/UEFA_coefficient"
HEADERS = {"User-Agent": "StadiaOfEurope/1.0 (learning project)"}


def _find_club_table(soup):
    """Find the club coefficient table (second major wikitable after the country one)."""
    tables = soup.find_all("table", class_="wikitable")
    # The club table has headers: Rank | Club | Association | Points
    for table in tables:
        rows = table.find_all("tr")
        if not rows:
            continue
        header_text = " ".join(c.get_text(" ", strip=True) for c in rows[0].find_all(["th", "td"]))
        if "Club" in header_text and ("Points" in header_text or "Coefficient" in header_text):
            return table
    return None


def _parse_club_name(cell):
    """Extract plain club name from a cell that may contain links and superscript notes."""
    for link in cell.find_all("a"):
        name = link.get_text(strip=True)
        if name:
            return name
    return cell.get_text(strip=True)


class Command(BaseCommand):
    help = "Update Team.uefa_coefficient from the Wikipedia UEFA 5-year club coefficient table"

    def handle(self, *args, **options):
        self.stdout.write("Fetching UEFA club coefficients from Wikipedia...")
        try:
            resp = requests.get(URL, headers=HEADERS, timeout=20)
            resp.raise_for_status()
        except Exception as exc:
            self.stderr.write(f"ERROR fetching page: {exc}")
            return

        soup = BeautifulSoup(resp.text, "html.parser")
        table = _find_club_table(soup)

        if not table:
            self.stderr.write("ERROR: Could not locate the club coefficient table.")
            return

        updated = 0
        skipped = []
        rows = table.find_all("tr")

        for row in rows[1:]:  # skip header row
            cells = row.find_all(["td", "th"])
            if len(cells) < 4:
                continue

            rank_text = cells[0].get_text(strip=True)
            if not rank_text.isdigit():
                continue

            club_name = _parse_club_name(cells[1])
            if not club_name:
                continue

            # Coefficient is the 4th column (index 3)
            coeff_text = cells[3].get_text(strip=True).replace(",", ".")
            try:
                coefficient = float(coeff_text)
            except ValueError:
                continue

            qs = Team.objects.filter(name__iexact=club_name)
            if not qs.exists():
                skipped.append(f"{rank_text}. {club_name!r}")
                continue

            count = qs.update(uefa_coefficient=coefficient)
            self.stdout.write(f"  {rank_text:>3}. {club_name} → {coefficient}")
            updated += count

        self.stdout.write(self.style.SUCCESS(f"\nUpdated {updated} teams."))
        if skipped:
            self.stdout.write(self.style.WARNING(
                f"Skipped {len(skipped)} clubs not found in DB (not yet scraped):"
            ))
            for s in skipped[:20]:
                self.stdout.write(f"  {s}")
            if len(skipped) > 20:
                self.stdout.write(f"  ... and {len(skipped) - 20} more")
