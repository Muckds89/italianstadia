"""
Seed the under-development stadium candidates (+ the new Spotify Camp Nou) into
StadiumDevelopment for production. Data is baked into a static JSON
(italiastadiaapp/data/dev_seed_baked.json) produced by `import_dev_candidates`,
so this migration does NO network I/O — it just upserts the resolved rows.

Conservative image policy already applied at bake time: NEW greenfield builds carry
text/facts only; REDEVELOPMENT/EXPANSION carry CC/PD Commons photos + coords of the
existing venue. The Camp Nou row links to the operational Stadium of the same name.
Idempotent (update_or_create on name); never overwrites a locked row.
"""
import json
from pathlib import Path

from django.conf import settings
from django.db import migrations
from django.utils.text import slugify


SEED = Path(settings.BASE_DIR) / "italiastadiaapp" / "data" / "dev_seed_baked.json"


def _unique_slug(model, name):
    """Historical models lack the model's custom save() that auto-slugs, so we
    must generate the unique slug here (mirrors StadiumDevelopment.save())."""
    base = slugify(name) or "development"
    slug = base
    n = 2
    while model.objects.filter(slug=slug).exclude(name=name).exists():
        slug = f"{base}-{n}"
        n += 1
    return slug


def forwards(apps, schema_editor):
    StadiumDevelopment = apps.get_model("italiastadiaapp", "StadiumDevelopment")
    Stadium = apps.get_model("italiastadiaapp", "Stadium")
    Team = apps.get_model("italiastadiaapp", "Team")
    rows = json.loads(SEED.read_text(encoding="utf-8"))

    for r in rows:
        existing = StadiumDevelopment.objects.filter(name=r["name"]).first()
        if existing and getattr(existing, "locked", False):
            continue

        stadium = None
        if r.get("stadium_name"):
            stadium = Stadium.objects.filter(name=r["stadium_name"]).first()

        obj, _ = StadiumDevelopment.objects.update_or_create(
            name=r["name"],
            defaults={
                "slug": existing.slug if existing and existing.slug else _unique_slug(StadiumDevelopment, r["name"]),
                "country": r.get("country") or "",
                "project_type": r["project_type"],
                "status": r["status"],
                "future_capacity": r.get("future_capacity"),
                "estimated_opening": r.get("estimated_opening"),
                "architect": r.get("architect") or "",
                "developer": r.get("developer") or "",
                "source_url": r.get("source_url") or "",
                "notes": r.get("notes") or "",
                "latitude": r.get("latitude"),
                "longitude": r.get("longitude"),
                "image_url": r.get("image_url") or "",
                "image_credit": r.get("image_credit") or "",
                "extra_images": r.get("extra_images") or [],
                "stadium": stadium,
            },
        )

        # Link the future tenant club (M2M), resolved at bake time to an exact name.
        if r.get("team_name"):
            team = Team.objects.filter(name=r["team_name"]).first()
            obj.future_tenants.set([team] if team else [])


def backwards(apps, schema_editor):
    StadiumDevelopment = apps.get_model("italiastadiaapp", "StadiumDevelopment")
    rows = json.loads(SEED.read_text(encoding="utf-8"))
    StadiumDevelopment.objects.filter(name__in=[r["name"] for r in rows]).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("italiastadiaapp", "0052_fix_turkish_stadium_coords_gallery"),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
