"""
Fix 16 operational stadiums whose scraped `name` was a foreign-language stadium
(e.g. German "Stadion Rehberge" stored for Malta's Tony Bezzina Stadium). In every
case the Wikipedia URL was correct, so the authoritative name is the Wikipedia page
title. Detected via `audit_stadium_names` (name shares zero significant tokens with
its own Wikipedia title AND carries a structural word foreign to its country).
Slugs are regenerated to match (the old slugs were wrong too).
"""
from django.db import migrations
from django.utils.text import slugify


# scraped (wrong) name -> correct name (the Wikipedia page title)
RENAMES = {
    "Stade Communal Jette Expo": "Bolt Arena",
    'Sportpark "Skoatterwâld"': "Wiklöf Holding Arena",
    "Lokstadion an der Lipezker Straße": "Koševo City Stadium",
    "Müritz-Stadion": "Stadion Grbavica",
    "Estádio do Bessa Século XXI": "Stadion Rođeni",
    "Binh Duong Stadium": "Bijeljina City Stadium",
    "Stadion Feuerbachstraße": "Gradski stadion (Prijedor)",
    "AaB's Anlæg": "Mokri Dolac Stadium",
    "Stadion Glashütte": "Akranesvöllur",
    "Sportanlage Dratelnstraße (Platz 1)": "KA-Völlur",
    "Heinrich-Kruse-Stadion (Platz 1)": "Hásteinsvöllur",
    "Stadion Olivier": "Torfnesvöllur",
    "Sportplatz Mariapfarr": "Stadion Pod Racinom",
    "Stadion Rehberge": "Tony Bezzina Stadium",
    "Waldstadion Hermeskeil": "Victor Tedesco Stadium",
    "Sportplatz St. Stefan ob Leoben": "Skonto Stadium",
}


def _unique_slug(Stadium, name, pk):
    base = slugify(name) or f"stadium-{pk}"
    slug = base
    n = 2
    while Stadium.objects.filter(slug=slug).exclude(pk=pk).exists():
        slug = f"{base}-{n}"
        n += 1
    return slug


def forwards(apps, schema_editor):
    Stadium = apps.get_model("italiastadiaapp", "Stadium")
    for old, new in RENAMES.items():
        for s in Stadium.objects.filter(name=old):
            s.name = new
            s.slug = _unique_slug(Stadium, new, s.pk)
            s.save(update_fields=["name", "slug"])


def backwards(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("italiastadiaapp", "0056_stadiumdevelopment_instagram_url"),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
