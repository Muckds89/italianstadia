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

from PIL import Image
from django.conf import settings
from django.core.management.base import BaseCommand
from django.test import RequestFactory


class Command(BaseCommand):
    help = "Render insight hero map PNGs to static/exports/."

    # key -> export query params
    MAPS = {
        "national": {
            "national": "1", "spotlight": "1", "style_key": "satellite",
            "size_key": "landscape", "labels": "1", "legend": "0", "north": "1",
            "title": "National stadiums of Europe",
            "subtitle": "Each country's main national-team venue",
        },
        "surface": {
            "color_by": "surface", "no_badges": "1", "surface_known": "1",
            "style_key": "satellite", "size_key": "landscape",
            "labels": "0", "legend": "1", "north": "1",
            "title": "Artificial vs natural grass in Europe",
            "subtitle": "Pitch surface of every stadium",
        },
        "overview": {
            "color_by": "country", "style_key": "satellite", "size_key": "landscape",
            "labels": "0", "legend": "0", "north": "1",
            "title": "Football Stadiums of Europe",
            "subtitle": "Every ground on one interactive map",
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
                rgb = img.convert("RGB")
                path = out_dir / f"insight_{key}.png"
                rgb.save(path, format="PNG", optimize=True)

                # Card thumbnail. The full PNG is 1920x1080 and ~3 MB; the
                # /insights/ grid draws it into a ~300x170 box, so shipping the
                # original meant several MB of hero images per page load. JPEG at
                # card width is ~2% of the bytes and visually identical at that size.
                card = rgb.copy()
                card.thumbnail((640, 640), Image.LANCZOS)
                card_path = out_dir / f"insight_{key}_card.jpg"
                card.save(card_path, format="JPEG", quality=82, optimize=True,
                          progressive=True)

                self.stdout.write(self.style.SUCCESS(
                    f"  Wrote {path.name} + {card_path.name} "
                    f"({card_path.stat().st_size // 1024} KB)"))
            except Exception as e:
                self.stderr.write(f"  {key}: render failed: {e}")

        self.stdout.write(self.style.WARNING(
            "\nCommit the regenerated PNGs (served as static files by WhiteNoise)."))
