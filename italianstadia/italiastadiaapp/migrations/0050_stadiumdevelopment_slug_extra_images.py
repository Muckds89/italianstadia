from django.db import migrations, models
from django.utils.text import slugify


TABLE = "italiastadiaapp_stadiumdevelopment"


def apply_everything(apps, schema_editor):
    """
    Idempotent: add slug column, backfill slugs, create unique index.
    Mirrors 0045_team_slug so concurrent migrate processes (Render multi-worker)
    and retries after partial failure are all safe.
    """
    conn = schema_editor.connection
    vendor = conn.vendor
    Development = apps.get_model("italiastadiaapp", "StadiumDevelopment")

    with conn.cursor() as cursor:
        if vendor == "postgresql":
            cursor.execute(
                f"ALTER TABLE {TABLE} "
                "ADD COLUMN IF NOT EXISTS slug varchar(255) NOT NULL DEFAULT ''"
            )
        elif vendor == "sqlite":
            cursor.execute(f"PRAGMA table_info({TABLE})")
            if "slug" not in [row[1] for row in cursor.fetchall()]:
                cursor.execute(
                    f"ALTER TABLE {TABLE} "
                    "ADD COLUMN slug varchar(255) NOT NULL DEFAULT ''"
                )

    # Backfill slugs (skips rows that already have one)
    for dev in Development.objects.order_by("pk"):
        if dev.slug:
            continue
        base = slugify(dev.name) or f"development-{dev.pk}"
        slug = base
        n = 2
        while Development.objects.filter(slug=slug).exclude(pk=dev.pk).exists():
            slug = f"{base}-{n}"
            n += 1
        dev.slug = slug
        dev.save(update_fields=["slug"])

    # Create unique index idempotently
    with conn.cursor() as cursor:
        if vendor == "postgresql":
            cursor.execute(
                f"DROP INDEX IF EXISTS {TABLE}_slug_uniq"
            )
            cursor.execute(
                f"CREATE UNIQUE INDEX IF NOT EXISTS {TABLE}_slug_uniq "
                f"ON {TABLE} (slug)"
            )
            cursor.execute(
                f"CREATE INDEX IF NOT EXISTS {TABLE}_slug_like "
                f"ON {TABLE} (slug varchar_pattern_ops)"
            )
        elif vendor == "sqlite":
            cursor.execute(
                f"CREATE UNIQUE INDEX IF NOT EXISTS {TABLE}_slug_uniq "
                f"ON {TABLE} (slug)"
            )


class Migration(migrations.Migration):
    atomic = False  # Each statement commits independently — safe for retries

    dependencies = [
        ("italiastadiaapp", "0049_fix_teamless_stadium_city_links"),
    ]

    operations = [
        # extra_images: plain JSON column, safe default — normal AddField.
        migrations.AddField(
            model_name="stadiumdevelopment",
            name="extra_images",
            field=models.JSONField(blank=True, default=list),
        ),
        # slug: add as non-unique in ORM state, backfill + index via raw SQL,
        # then mark unique in ORM state (DDL handled by apply_everything).
        migrations.SeparateDatabaseAndState(
            database_operations=[],
            state_operations=[
                migrations.AddField(
                    model_name="stadiumdevelopment",
                    name="slug",
                    field=models.SlugField(blank=True, max_length=255),
                ),
            ],
        ),
        migrations.RunPython(apply_everything, migrations.RunPython.noop),
        migrations.SeparateDatabaseAndState(
            database_operations=[],
            state_operations=[
                migrations.AlterField(
                    model_name="stadiumdevelopment",
                    name="slug",
                    field=models.SlugField(blank=True, max_length=255, unique=True),
                ),
            ],
        ),
    ]
