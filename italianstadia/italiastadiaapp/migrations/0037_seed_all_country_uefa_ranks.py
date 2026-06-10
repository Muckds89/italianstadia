"""
Seed UEFA 2024-25 country access-round coefficient rankings for all 51
member associations tracked in this project.

The five already-seeded ranks (England=1, Italy=2, Germany=4, France=5,
Portugal=6) are included here so the migration is idempotent.  Spain
(rank 3) was accidentally omitted from the original data.

Looks up countries by ISO-2 code (not name) so the migration survives
country name changes across deployments (e.g. "Czech Republic" vs "Czechia").

Source: UEFA country coefficients table 2024-25
"""
from django.db import migrations

# (ISO-2 country code as stored in Country.code, rank)
UEFA_RANKS = [
    ("GB",  1),   # England
    ("IT",  2),   # Italy
    ("ES",  3),   # Spain
    ("DE",  4),   # Germany
    ("FR",  5),   # France
    ("PT",  6),   # Portugal
    ("NL",  7),   # Netherlands
    ("BE",  8),   # Belgium
    ("CZ",  9),   # Czech Republic / Czechia
    ("AT", 10),   # Austria
    ("TR", 11),   # Turkey
    ("SC", 12),   # Scotland
    ("UA", 13),   # Ukraine
    ("CH", 14),   # Switzerland
    ("HR", 15),   # Croatia
    ("DK", 16),   # Denmark
    ("RS", 17),   # Serbia
    ("GR", 18),   # Greece
    ("NO", 19),   # Norway
    ("SE", 20),   # Sweden
    ("RO", 21),   # Romania
    ("PL", 22),   # Poland
    ("HU", 23),   # Hungary
    ("SK", 24),   # Slovakia
    ("CY", 25),   # Cyprus
    ("BG", 26),   # Bulgaria
    ("IE", 27),   # Ireland
    ("RU", 28),   # Russia
    ("SI", 29),   # Slovenia
    ("AZ", 30),   # Azerbaijan
    ("IS", 31),   # Iceland
    ("AL", 32),   # Albania
    ("BY", 33),   # Belarus
    ("GE", 34),   # Georgia
    ("XK", 35),   # Kosovo
    ("LV", 36),   # Latvia
    ("LU", 37),   # Luxembourg
    ("LT", 38),   # Lithuania
    ("EE", 39),   # Estonia
    ("MK", 40),   # North Macedonia
    ("FI", 41),   # Finland
    ("BA", 42),   # Bosnia and Herzegovina
    ("ME", 43),   # Montenegro
    ("AM", 44),   # Armenia
    ("MD", 45),   # Moldova
    ("WL", 46),   # Wales
    ("MT", 47),   # Malta
    ("LI", 48),   # Liechtenstein
    ("AD", 49),   # Andorra
    ("SM", 50),   # San Marino
    ("MC", 51),   # Monaco
]


def seed_ranks(apps, schema_editor):
    Country = apps.get_model("italiastadiaapp", "Country")
    updated = 0
    missing = []
    for code, rank in UEFA_RANKS:
        rows = Country.objects.filter(code=code).update(uefa_rank=rank)
        if rows:
            updated += rows
        else:
            missing.append(code)
    print(f"  UEFA ranks: updated {updated} countries.")
    if missing:
        print(f"  Code not found in DB (no data scraped yet): {', '.join(missing)}")


def clear_ranks(apps, schema_editor):
    Country = apps.get_model("italiastadiaapp", "Country")
    seeded_codes = [code for code, _ in UEFA_RANKS]
    Country.objects.filter(code__in=seeded_codes).update(uefa_rank=None)


class Migration(migrations.Migration):

    dependencies = [
        ("italiastadiaapp", "0036_fix_scotland_wales_country_codes"),
    ]

    operations = [
        migrations.RunPython(seed_ranks, reverse_code=clear_ranks),
    ]
