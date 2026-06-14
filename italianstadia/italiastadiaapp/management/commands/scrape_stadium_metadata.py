"""
Scrape architect, surface, and stadium_type from Wikipedia infoboxes.

Usage:
    python manage.py scrape_stadium_metadata
    python manage.py scrape_stadium_metadata --dry-run
    python manage.py scrape_stadium_metadata --force          # overwrite existing values
    python manage.py scrape_stadium_metadata --limit 50
    python manage.py scrape_stadium_metadata --stadium-id 12
"""
import io
import re
import sys
import time
from urllib.parse import unquote, urlparse

import requests
from django.core.management.base import BaseCommand
from django.db.models import Q

from italiastadiaapp.models import Stadium

# ── Surface keyword -> choice ─────────────────────────────────────────────────
# HYBRID before GRASS (GrassMaster / Desso are hybrid grass systems)
SURFACE_MAP = [
    (["desso", "hybrid", "ibrido", "ibrida", "grassmaster"], "HYBRID"),
    (["artificial", "astroturf", "polytan", "sintetico", "sintetica",
      "3g turf", "4g turf", "fieldturf", "matrix turf", "mondo turf",
      "erba sintetica", "synthetic", "mondo sport"], "ARTIFICIAL"),
    (["grass", "natural", "erba", "turf"], "GRASS"),
]

# ── Roof keyword -> stadium_type choice ──────────────────────────────────────
TYPE_MAP = [
    (["retractable"], "RETRACTABLE"),
    (["indoor", "dome", "domed", "enclosed", "fully covered",
      "full roof", "closed roof", "copertura chiusa"], "CLOSED"),
    (["none", "no roof", "open", "aperto", "nessuna", "nessun"], "OPEN"),
]

# Italian Wikipedia infobox field names
IT_FIELD_ALIASES = {
    "superficie": "surface",
    "copertura": "roof",
    "architetto": "architect",
}


class Command(BaseCommand):
    help = "Populate architect, surface, stadium_type from Wikipedia infoboxes."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true",
                            help="Show what would be updated without saving.")
        parser.add_argument("--force", action="store_true",
                            help="Overwrite fields that already have a value.")
        parser.add_argument("--limit", type=int, default=0,
                            help="Stop after N stadiums (0 = no limit).")
        parser.add_argument("--stadium-id", type=int, default=0,
                            help="Process only this stadium pk.")
        parser.add_argument("--delay", type=float, default=1.0,
                            help="Seconds between Wikipedia API requests (default: 1.0).")

    def handle(self, *args, **options):
        # Force UTF-8 output on Windows to handle non-ASCII stadium names
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")

        dry_run  = options["dry_run"]
        force    = options["force"]
        limit    = options["limit"]
        delay    = options["delay"]
        stad_id  = options["stadium_id"]

        qs = Stadium.objects.exclude(
            wikipedia_url__isnull=True
        ).exclude(wikipedia_url="")

        if stad_id:
            qs = qs.filter(pk=stad_id)
        elif not force:
            qs = qs.filter(
                Q(architect__isnull=True) | Q(architect="") |
                Q(surface__isnull=True)   | Q(surface="")  |
                Q(stadium_type__isnull=True) | Q(stadium_type="")
            )

        if limit:
            qs = qs[:limit]

        total = qs.count()
        self.stdout.write(f"Stadiums to process: {total}")
        if dry_run:
            self.stdout.write(self.style.WARNING("DRY-RUN - nothing will be saved."))

        counts = {"architect": 0, "surface": 0, "stadium_type": 0,
                  "skipped": 0, "errors": 0}

        session = requests.Session()
        session.headers["User-Agent"] = (
            "ItalianStadiaBot/1.0 "
            "(https://italianstadia.onrender.com; destavola.marco@gmail.com)"
        )

        for idx, stadium in enumerate(qs, 1):
            self.stdout.write(f"[{idx}/{total}] {stadium.name}", ending=" ... ")

            try:
                lang, title = _parse_wikipedia_url(stadium.wikipedia_url)
            except ValueError as exc:
                self.stdout.write(self.style.ERROR(f"bad URL: {exc}"))
                counts["errors"] += 1
                continue

            try:
                wikitext = _fetch_wikitext(session, lang, title)
            except Exception as exc:
                self.stdout.write(self.style.ERROR(f"fetch error: {exc}"))
                counts["errors"] += 1
                time.sleep(delay)
                continue

            if not wikitext:
                self.stdout.write(self.style.WARNING("no wikitext"))
                counts["skipped"] += 1
                time.sleep(delay)
                continue

            fields = _extract_infobox_fields(wikitext, lang)
            updates = {}

            # -- Architect ---------------------------------------------------
            if (force or not stadium.architect) and fields.get("architect"):
                raw = _clean_architect(fields["architect"])
                if raw:
                    updates["architect"] = raw[:255]

            # -- Surface -----------------------------------------------------
            if (force or not stadium.surface) and fields.get("surface"):
                raw = _clean_wikitext(fields["surface"])
                mapped = _map_surface(raw)
                if mapped:
                    updates["surface"] = mapped

            # -- Stadium type (from roof field) ------------------------------
            if force or not stadium.stadium_type:
                if fields.get("roof"):
                    raw = _clean_wikitext(fields["roof"])
                    mapped = _map_type(raw)
                    if mapped:
                        updates["stadium_type"] = mapped
                elif fields:
                    # Infobox parsed OK but no roof field → open-air stadium
                    updates["stadium_type"] = "OPEN"

            if updates:
                parts = []
                for field, val in updates.items():
                    if field in ("surface", "stadium_type"):
                        parts.append(f"{field}={val}")
                    else:
                        parts.append(f"{field}='{val[:50]}'")
                    counts[field] += 1
                self.stdout.write(self.style.SUCCESS(", ".join(parts)))
                if not dry_run:
                    for field, val in updates.items():
                        setattr(stadium, field, val)
                    stadium.save(update_fields=list(updates.keys()))
            else:
                self.stdout.write("nothing new")
                counts["skipped"] += 1

            time.sleep(delay)

        self.stdout.write("")
        self.stdout.write("-" * 60)
        self.stdout.write(self.style.SUCCESS(
            f"architect={counts['architect']}  "
            f"surface={counts['surface']}  "
            f"type={counts['stadium_type']}  "
            f"skipped={counts['skipped']}  "
            f"errors={counts['errors']}"
        ))
        if not dry_run and any(counts[k] for k in ("architect", "surface", "stadium_type")):
            self.stdout.write("Run: python manage.py generate_stadiums_json")


# ── Helpers ──────────────────────────────────────────────────────────────────

def _parse_wikipedia_url(url: str) -> tuple:
    parsed = urlparse(url)
    host = parsed.netloc
    if "wikipedia.org" not in host:
        raise ValueError(f"not a Wikipedia URL: {url}")
    lang = host.split(".")[0]
    path = parsed.path
    if not path.startswith("/wiki/"):
        raise ValueError(f"unexpected path: {path}")
    title = unquote(path[len("/wiki/"):])
    return lang, title


def _fetch_wikitext(session, lang, title):
    """Fetch raw wikitext via the Wikipedia Action API, following redirects."""
    url = f"https://{lang}.wikipedia.org/w/api.php"
    params = {
        "action": "query",
        "prop": "revisions",
        "titles": title,
        "redirects": "1",        # follow #REDIRECT pages automatically
        "rvprop": "content",
        "rvslots": "main",
        "format": "json",
        "formatversion": "2",
    }
    resp = session.get(url, params=params, timeout=15)
    resp.raise_for_status()
    data = resp.json()
    pages = data.get("query", {}).get("pages", [])
    if not pages:
        return None
    page = pages[0]
    if page.get("missing"):
        return None
    slots = page.get("revisions", [{}])[0].get("slots", {})
    return slots.get("main", {}).get("content", None)


def _extract_infobox_fields(wikitext, lang):
    """
    Scan wikitext line-by-line for infobox field assignments.
    Works regardless of the infobox template name (venue, stadium, stadio, etc.).
    Handles multi-line values that continue until the next | or }}.
    """
    fields = {}
    current_key = None
    current_val_lines = []
    in_infobox = False

    for line in wikitext.splitlines():
        stripped = line.strip()

        # Detect start of any Infobox template
        if re.match(r"\{\{[Ii]nfobox", stripped):
            in_infobox = True
            continue

        if not in_infobox:
            continue

        # Detect end of infobox
        if stripped == "}}":
            if current_key:
                fields[current_key] = " ".join(current_val_lines).strip()
            in_infobox = False
            break

        # New field line: | key = value
        m = re.match(r"\|\s*(\w+)\s*=\s*(.*)", stripped)
        if m:
            # Save previous field
            if current_key:
                fields[current_key] = " ".join(current_val_lines).strip()
            key = m.group(1).strip().lower()
            key = IT_FIELD_ALIASES.get(key, key)
            current_key = key
            current_val_lines = [m.group(2).strip()]
        elif current_key and stripped and not stripped.startswith("|"):
            # Continuation of a multi-line value
            current_val_lines.append(stripped)

    return fields


# Wikilink: [[Target|Display]] -> Target (full name); [[Target]] -> Target
_WIKILINK_RE = re.compile(r"\[\[([^\|\]]+)(?:\|[^\]]+)?\]\]")
# Templates: {{...}}
_TEMPLATE_RE = re.compile(r"\{\{[^\}]*\}\}")
# <ref>...</ref>
_REF_RE = re.compile(r"<ref[^/]*/?>.*?</ref>", re.DOTALL | re.IGNORECASE)
_REF_SELF_CLOSE = re.compile(r"<ref[^/]*/?>", re.IGNORECASE)
# Any remaining HTML tags
_HTML_RE = re.compile(r"<[^>]+>")


def _clean_wikitext(raw):
    """Strip wikilinks, templates, HTML tags from a wikitext value."""
    text = _REF_RE.sub("", raw)
    text = _REF_SELF_CLOSE.sub("", text)
    text = _WIKILINK_RE.sub(r"\1", text)
    text = _TEMPLATE_RE.sub("", text)
    text = _HTML_RE.sub("", text)
    return text.strip()


def _clean_architect(raw):
    """
    Extract the first architect name from a possibly multi-value field.
    Handles:
      * *Name1 *Name2 ...  (bullet list joined by extractor into one string)
      * Name1<br />Name2
      * [[Name|Abbr]] (year)
    """
    # Strip leading * bullet first so split doesn't leave empty first element
    raw = raw.lstrip("*").strip()
    # Split on: <br/>, or a run of whitespace followed by * (joined bullet lines)
    first = re.split(r"<br\s*/?>|\s+\*", raw, maxsplit=1)[0].strip()
    # Clean wikitext markup
    first = _clean_wikitext(first)
    # Remove trailing year annotation like "(1925)" or "(1925-1990)"
    first = re.sub(r"\s*\(\d{4}[^)]*\)\s*$", "", first).strip()
    # Remove trailing comma or semicolon
    first = first.rstrip(",;").strip()
    return first


def _map_surface(raw):
    lower = raw.lower()
    for keywords, choice in SURFACE_MAP:
        if any(kw in lower for kw in keywords):
            return choice
    return ""


def _map_type(raw):
    lower = raw.lower()
    for keywords, choice in TYPE_MAP:
        if any(kw in lower for kw in keywords):
            return choice
    return ""
