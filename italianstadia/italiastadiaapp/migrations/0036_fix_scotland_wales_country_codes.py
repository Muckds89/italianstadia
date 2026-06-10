"""
Corrective data migration: shorten Scotland and Wales country codes to ≤ 2 chars.

Root cause: migration 0030 originally seeded "GB-SCT" (6 chars) and "GB-WLS" (6 chars)
into Country.code which is CharField(max_length=2).  SQLite silently accepts over-length
values; PostgreSQL raises DataError and blocks the Render deploy.

Migration 0030 has been corrected to use "SC" / "WL" for fresh deployments.
This migration fixes any local dev database that already ran the old 0030.
"""
from django.db import migrations


def fix_codes(apps, schema_editor):
    Country = apps.get_model("italiastadiaapp", "Country")
    fixes = [
        ("GB-SCT", "SC"),
        ("GB-WLS", "WL"),
    ]
    for old_code, new_code in fixes:
        updated = Country.objects.filter(code=old_code).update(code=new_code)
        if updated:
            print(f"  Fixed Country code {old_code!r} -> {new_code!r} ({updated} row)")


def reverse_codes(apps, schema_editor):
    Country = apps.get_model("italiastadiaapp", "Country")
    fixes = [
        ("SC", "GB-SCT"),
        ("WL", "GB-WLS"),
    ]
    for old_code, new_code in fixes:
        Country.objects.filter(code=old_code).update(code=new_code)


class Migration(migrations.Migration):

    dependencies = [
        ("italiastadiaapp", "0035_team_uefa_coefficient"),
    ]

    operations = [
        migrations.RunPython(fix_codes, reverse_code=reverse_codes),
    ]
