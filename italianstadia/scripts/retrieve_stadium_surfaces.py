"""
Usage:
python scripts/retrieve_stadium_surfaces.py stadiums_missing_surface.csv stadium_surface_import.csv
"""

import csv
import re
import sys
import time
from dataclasses import dataclass

import requests
from bs4 import BeautifulSoup


SURFACE_MAP = {
    "natural grass": "GRASS",
    "grass": "GRASS",
    "artificial grass": "ARTIFICIAL",
    "artificial turf": "ARTIFICIAL",
    "synthetic turf": "ARTIFICIAL",
    "synthetic grass": "ARTIFICIAL",
    "astroturf": "ARTIFICIAL",
    "hybrid grass": "HYBRID",
    "hybrid turf": "HYBRID",
    "hybrid": "HYBRID",
}


BAD_SURFACE_PATTERNS = [
    "metres", "meters", "meter", "ft", "feet",
    "105 by", "105m", "68m", "x 68", "x68",
    "pitch size", "dimensions",
]


HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0 Safari/537.36"
    )
}


@dataclass
class SurfaceResult:
    surface: str = ""
    raw: str = ""
    source_url: str = ""
    notes: str = ""


def clean_text(value: str) -> str:
    if not value:
        return ""
    return re.sub(r"\s+", " ", value).strip()


def map_surface(raw: str):
    if not raw:
        return "", "surface not found"

    value = clean_text(raw).lower()

    if any(p in value for p in BAD_SURFACE_PATTERNS):
        return "", "ignored pitch size, not surface"

    for key, mapped in SURFACE_MAP.items():
        if key in value:
            return mapped, "surface mapped"

    return "", "surface found but not mapped"


def load_input(path: str):
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)

        for row in reader:
            yield (
                row.get("id") or row.get("stadium_id"),
                row.get("name") or row.get("stadium_name"),
                row.get("wikipedia_url", ""),
                row.get("transfermarkt_url", ""),
            )


def get_soup(url: str):
    response = requests.get(url, headers=HEADERS, timeout=20)
    response.raise_for_status()
    return BeautifulSoup(response.text, "html.parser")


def extract_from_transfermarkt(url: str) -> SurfaceResult:
    try:
        soup = get_soup(url)
        text = clean_text(soup.get_text(" "))

        # Strong Transfermarkt pattern:
        # Surface: Natural grass
        match = re.search(
            r"Surface:\s*([A-Za-z ]+?)(?:\s+Pitch size:|\s+Name of stadium:|\s+Total capacity:|\s+Undersoil heating:|\s+Running track:|$)",
            text,
            flags=re.IGNORECASE,
        )

        if match:
            raw = clean_text(match.group(1))
            surface, notes = map_surface(raw)
            return SurfaceResult(
                surface=surface,
                raw=raw,
                source_url=url,
                notes=f"transfermarkt: {notes}",
            )

        # Fallback: find literal Surface label in page text
        idx = text.lower().find("surface:")
        if idx != -1:
            raw_chunk = text[idx + len("surface:"): idx + len("surface:") + 80]
            raw = clean_text(raw_chunk.split("Pitch size:")[0])
            surface, notes = map_surface(raw)
            return SurfaceResult(
                surface=surface,
                raw=raw,
                source_url=url,
                notes=f"transfermarkt fallback: {notes}",
            )

        return SurfaceResult(source_url=url, notes="transfermarkt: surface not found")

    except Exception as e:
        return SurfaceResult(source_url=url, notes=f"transfermarkt error: {e}")


def extract_from_wikipedia(url: str) -> SurfaceResult:
    try:
        soup = get_soup(url)

        infobox = soup.find("table", class_="infobox")
        if not infobox:
            return SurfaceResult(source_url=url, notes="wikipedia: no infobox")

        for row in infobox.find_all("tr"):
            header = row.find("th")
            data = row.find("td")

            if not header or not data:
                continue

            label = clean_text(header.get_text(" ")).lower()
            value = clean_text(data.get_text(" "))

            # Avoid matching "field size", "dimensions", etc.
            if label in ["surface", "field surface", "pitch surface"]:
                surface, notes = map_surface(value)
                return SurfaceResult(
                    surface=surface,
                    raw=value,
                    source_url=url,
                    notes=f"wikipedia: {notes}",
                )

        return SurfaceResult(source_url=url, notes="wikipedia: surface not found")

    except Exception as e:
        return SurfaceResult(source_url=url, notes=f"wikipedia error: {e}")


def main(inp: str, out: str):
    rows = list(load_input(inp))

    with open(out, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            "stadium_id",
            "stadium_name",
            "surface",
            "surface_raw",
            "source_url",
            "wikipedia_url",
            "transfermarkt_url",
            "notes",
        ])

        for i, (sid, name, wiki, tm) in enumerate(rows, 1):
            result = SurfaceResult(notes="not found")

            # Prefer Transfermarkt because it has an explicit Surface field
            if tm:
                result = extract_from_transfermarkt(tm)
                time.sleep(0.4)

            # Fallback to Wikipedia only if TM did not return mapped surface
            if not result.surface and wiki:
                wiki_result = extract_from_wikipedia(wiki)

                # Keep Wikipedia result if it maps, or if TM found nothing useful
                if wiki_result.surface or not result.raw:
                    result = wiki_result

                time.sleep(0.2)

            writer.writerow([
                sid,
                name,
                result.surface,
                result.raw,
                result.source_url,
                wiki,
                tm,
                result.notes,
            ])

            print(
                f"{i}/{len(rows)} {sid} {name}: "
                f"{result.surface or 'UNKNOWN'} ({result.raw}) - {result.notes}"
            )


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python retrieve_stadium_surfaces.py input.csv output.csv")
        sys.exit(1)

    main(sys.argv[1], sys.argv[2])