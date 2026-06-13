import json
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand

from italiastadiaapp.views import _build_stadium_features


class Command(BaseCommand):
    help = (
        "Pre-generate italiastadiaapp/static/data/stadiums_map.json for WhiteNoise. "
        "Run after every scrape and before collectstatic."
    )

    def handle(self, *args, **options):
        features = _build_stadium_features()
        payload = json.dumps(
            {"type": "FeatureCollection", "features": features},
            separators=(",", ":"),   # compact — saves ~5–10 KB vs default spacing
        )

        out_path = (
            Path(settings.BASE_DIR)
            / "italiastadiaapp"
            / "static"
            / "data"
            / "stadiums_map.json"
        )
        out_path.write_text(payload, encoding="utf-8")

        kb = len(payload) / 1024
        self.stdout.write(
            self.style.SUCCESS(
                f"Written {len(features)} stadiums ({kb:.0f} KB) -> {out_path.relative_to(settings.BASE_DIR)}"
            )
        )
