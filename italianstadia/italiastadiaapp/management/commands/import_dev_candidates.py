"""
import_dev_candidates
=====================
Imports the curated under-development seed file
(scripts/data/dev_stadiums_candidates.json) into StadiumDevelopment.

Conservative image/coords policy (see INTEGRATION_DESIGN_dev_pipeline.md):
  - REDEVELOPMENT / EXPANSION → the venue already exists, so we geocode + pull
    freely-licensed (CC / public-domain) Wikimedia Commons photos of it.
  - NEW (greenfield) → Commons has no correct photo yet (only copyrighted renders
    or photos of a different/old ground), so we import text + facts only; the
    architect_firm link serves as the outbound "see renders" reference.

Idempotent: update_or_create on name; never overwrites a row marked locked.

Usage:
    python -X utf8 manage.py import_dev_candidates --dry-run
    python -X utf8 manage.py import_dev_candidates
"""
import json
import re
import time
from pathlib import Path

import requests
from django.conf import settings
from django.core.management.base import BaseCommand

HEADERS = {"User-Agent": "ItalianStadiaBot/1.0 (learning project; contact example@example.com)"}
SEED = Path(settings.BASE_DIR) / "scripts" / "data" / "dev_stadiums_candidates.json"
IMG_SKIP = ["logo", "flag", "map", "icon", "wikidata", "locator", "edit", "arrow",
            "seal", "coat_of_arms", "plan", "diagram", "_map", "commons-logo"]


def _clean_int(value):
    """Coerce capacity/year to int, or None for blank/UNKNOWN/non-numeric values."""
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _get_json(url, params, tries=4):
    for attempt in range(tries):
        r = requests.get(url, params=params, headers=HEADERS, timeout=30)
        if r.status_code == 429:
            time.sleep(5 + attempt * 5)
            continue
        r.raise_for_status()
        return r.json()
    return {}


def _wiki_api(wikipedia_url):
    host = wikipedia_url.split("/wiki/")[0]
    title = wikipedia_url.split("/wiki/")[-1]
    return host + "/w/api.php", requests.utils.unquote(title)


def fetch_coords(wikipedia_url):
    if not wikipedia_url:
        return None, None
    api, title = _wiki_api(wikipedia_url)
    data = _get_json(api, {"action": "query", "titles": title,
                           "prop": "coordinates", "format": "json"})
    for p in data.get("query", {}).get("pages", {}).values():
        if "coordinates" in p:
            c = p["coordinates"][0]
            return round(c["lat"], 6), round(c["lon"], 6)
    return None, None


def fetch_commons_images(wikipedia_url, max_images=4):
    """Return [{url, credit}] of CC/PD images embedded in the article."""
    if not wikipedia_url:
        return []
    api, title = _wiki_api(wikipedia_url)
    time.sleep(1.5)
    data = _get_json(api, {"action": "query", "titles": title, "prop": "images",
                           "imlimit": 40, "redirects": 1, "format": "json"})
    files = []
    for p in data.get("query", {}).get("pages", {}).values():
        for img in p.get("images", []):
            n = img["title"]
            nl = n.lower()
            if nl.endswith((".svg", ".gif")) or any(s in nl for s in IMG_SKIP):
                continue
            files.append(n)
    if not files:
        return []
    time.sleep(1.5)
    info = _get_json(api, {"action": "query", "titles": "|".join(files[:30]),
                           "prop": "imageinfo", "iiprop": "url|extmetadata|size",
                           "format": "json"})
    out = []
    for p in info.get("query", {}).get("pages", {}).values():
        ii = (p.get("imageinfo") or [{}])[0]
        url = ii.get("url", "")
        size = ii.get("size", 0)
        if not url or any(s in url.lower() for s in IMG_SKIP):
            continue
        if size and (size < 90_000 or size > 6_000_000):
            continue
        meta = ii.get("extmetadata", {})
        lic = meta.get("LicenseShortName", {}).get("value", "")
        if "cc" not in lic.lower() and "public" not in lic.lower():
            continue
        author = re.sub("<[^>]+>", "", meta.get("Artist", {}).get("value", "")).strip()
        credit = " / ".join(x for x in [author, "Wikimedia Commons", lic] if x)
        out.append({"url": url, "credit": credit})
        if len(out) >= max_images:
            break
    return out


class Command(BaseCommand):
    help = "Import curated under-development stadium candidates into StadiumDevelopment."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **opts):
        from italiastadiaapp.models import StadiumDevelopment

        dry = opts["dry_run"]
        candidates = json.loads(SEED.read_text(encoding="utf-8"))["candidates"]
        created = updated = skipped = 0

        for c in candidates:
            name = c["name"]
            existing = StadiumDevelopment.objects.filter(name=name).first()
            if existing and getattr(existing, "locked", False):
                self.stdout.write(f"  [LOCKED skip] {name}")
                skipped += 1
                continue

            src = c.get("sources", {})
            fields = {
                "country": c.get("country") or "",
                "project_type": c["project_type"],
                "status": c["status"],
                "future_capacity": _clean_int(c.get("future_capacity")),
                "estimated_opening": _clean_int(c.get("estimated_opening")),
                "architect": c.get("architect") or "",
                "source_url": src.get("architect_firm") or src.get("official") or src.get("wikipedia") or "",
                "notes": c.get("seo_description") or "",
            }

            # Conservative image/coords: existing venues only.
            wiki = src.get("wikipedia", "")
            if c["project_type"] in ("REDEVELOPMENT", "EXPANSION") and wiki:
                lat, lon = fetch_coords(wiki)
                if lat is not None:
                    fields["latitude"], fields["longitude"] = lat, lon
                imgs = fetch_commons_images(wiki)
                if imgs:
                    fields["image_url"] = imgs[0]["url"]
                    fields["image_credit"] = imgs[0]["credit"]
                    fields["extra_images"] = imgs[1:]
                tag = f"coords={'Y' if lat is not None else '-'} imgs={len(imgs)}"
            else:
                tag = "NEW: text-only (no image/coords)"

            if dry:
                flag = "UPDATE" if existing else "CREATE"
                self.stdout.write(f"  [{flag}] {name[:40]:40} | {tag}")
                created += 0 if existing else 1
                updated += 1 if existing else 0
                continue

            obj, was_created = StadiumDevelopment.objects.update_or_create(
                name=name, defaults=fields,
            )

            # Link the future tenant club (M2M) from the candidate "team" field.
            from italiastadiaapp.models import Team
            team_q = (c.get("team") or "").strip()
            if team_q:
                team = Team.objects.filter(name=team_q).first()
                if not team:
                    stop = {"team", "national", "football", "club", "calcio",
                            "stadium", "city", "united", "real"}
                    for w in sorted(team_q.split(), key=len, reverse=True):
                        if len(w) >= 4 and w.lower() not in stop:
                            team = Team.objects.filter(name__icontains=w).first()
                            if team:
                                break
                obj.future_tenants.set([team] if team else [])
            created += 1 if was_created else 0
            updated += 0 if was_created else 1
            self.stdout.write(self.style.SUCCESS(
                f"  {'Created' if was_created else 'Updated'}: {name} | {tag}"
            ))

        self.stdout.write(self.style.SUCCESS(
            f"\nDone. Created {created} | Updated {updated} | Skipped(locked) {skipped}"
        ))
        if not dry and (created or updated):
            self.stdout.write(self.style.WARNING(
                "\nRemember to regenerate the static GeoJSON if any dev now has coords,\n"
                "and to deploy these rows to production (data migration or fixture)."
            ))
