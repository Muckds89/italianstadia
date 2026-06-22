"""
generate_insight_maps
======================
Render back-end PNG hero maps for the /insights/ pages (satellite base, flag badges,
spotlit countries, logo + watermark — same stack as the tournament maps) into
`italiastadiaapp/static/exports/insight_<key>.png`.

Heavy Pillow/tile rendering happens ONCE here, not per request (Render 512 MB tier).
Re-run after data changes that affect the insight (e.g. a new national-team-only
ground), then commit the regenerated PNG.

Usage:
    python -X utf8 manage.py generate_insight_maps
"""
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand
from django.test import RequestFactory


class Command(BaseCommand):
    help = "Render insight hero map PNGs to static/exports/."

    # key -> export query params
    MAPS = {
        "national": {
            "national_only": "1", "spotlight": "1", "style_key": "satellite",
            "size_key": "landscape", "labels": "1", "legend": "0", "north": "1",
            "title": "National-team-only stadiums of Europe",
            "subtitle": "Grounds used exclusively by a national side",
        },
    }

    def handle(self, *args, **opts):
        from italiastadiaapp.views import (
            _parse_export_params, _compose_export_image, _draw_watermark,
        )
        out_dir = Path(settings.BASE_DIR) / "italiastadiaapp" / "static" / "exports"
        out_dir.mkdir(parents=True, exist_ok=True)
        rf = RequestFactory()

        for key, query in self.MAPS.items():
            params = _parse_export_params(rf.get("/api/export/map/", query))
            params["logo"] = True
            try:
                img, err = _compose_export_image(params)
                if err:
                    self.stderr.write(f"  {key}: {err}")
                    continue
                img = _draw_watermark(img, params["W"], params["H"])
                path = out_dir / f"insight_{key}.png"
                img.convert("RGB").save(path, format="PNG", optimize=True)
                self.stdout.write(self.style.SUCCESS(f"  Wrote {path.name}"))
            except Exception as e:
                self.stderr.write(f"  {key}: render failed: {e}")

        self.stdout.write(self.style.WARNING(
            "\nCommit the regenerated PNGs (served as static files by WhiteNoise)."))
