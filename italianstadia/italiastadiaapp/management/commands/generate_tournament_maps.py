"""
generate_tournament_maps
========================
Render a back-end PNG map for each tournament (satellite style, labels, legend,
north arrow, the site logo AND watermark — same look as the public export) and save
it to `italiastadiaapp/static/exports/tournament_<slug>.png`.

The tournament detail page embeds this static image, so the heavy Pillow/tile render
happens ONCE here (offline) rather than on every page view — important on Render's
512 MB free tier. **Re-run after any change to tournament data** (the same way you
re-run `generate_stadiums_json`), then commit the regenerated PNGs.

Usage:
    python -X utf8 manage.py generate_tournament_maps
    python -X utf8 manage.py generate_tournament_maps --slug uefa-euro-2032
"""
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand
from django.test import RequestFactory
from django.utils.text import slugify


class Command(BaseCommand):
    help = "Render each tournament's map PNG (watermark + logo) to static/exports/."

    def add_arguments(self, parser):
        parser.add_argument("--slug", default="", help="Render only this tournament slug.")
        parser.add_argument("--size", default="landscape", help="Export size key (wide, fits all venues).")

    def handle(self, *args, **opts):
        from italiastadiaapp.models import Stadium, StadiumDevelopment
        from italiastadiaapp.views import (
            _parse_export_params, _compose_export_image, _draw_watermark,
        )

        # Collect slug -> display name from both stadiums and developments.
        tour = {}
        for obj in list(Stadium.objects.exclude(tournaments=[]).only("tournaments")) + \
                   list(StadiumDevelopment.objects.exclude(tournaments=[]).only("tournaments")):
            for entry in (obj.tournaments or []):
                name = entry.get("tournament", "")
                if name:
                    tour.setdefault(slugify(name), name)

        if opts["slug"]:
            tour = {k: v for k, v in tour.items() if k == opts["slug"]}
            if not tour:
                self.stderr.write(f"No tournament with slug '{opts['slug']}'.")
                return

        out_dir = Path(settings.BASE_DIR) / "italiastadiaapp" / "static" / "exports"
        out_dir.mkdir(parents=True, exist_ok=True)
        rf = RequestFactory()

        for slug, name in sorted(tour.items()):
            query = {
                "tournament": slug,
                "style_key": "satellite",   # satellite imagery base
                "size_key": opts["size"],   # landscape — fits the full geographic spread
                "spotlight": "1",           # dim & outline the host countries
                "legend": "1", "labels": "1", "north": "1", "scale": "0",
                "title": name,
                "subtitle": "Candidate and confirmed host stadiums",
            }
            req = rf.get("/api/export/map/", query)
            params = _parse_export_params(req)
            params["logo"] = True   # branded version (logo + watermark), like the public export
            try:
                img, err = _compose_export_image(params)
                if err:
                    self.stderr.write(f"  {slug}: {err}")
                    continue
                img = _draw_watermark(img, params["W"], params["H"])
                path = out_dir / f"tournament_{slug}.png"
                img.convert("RGB").save(path, format="PNG", optimize=True)
                self.stdout.write(self.style.SUCCESS(f"  Wrote {path.name} ({name})"))
            except Exception as e:
                self.stderr.write(f"  {slug}: render failed: {e}")

        self.stdout.write(self.style.WARNING(
            "\nCommit the regenerated PNGs (served as static files by WhiteNoise)."))
