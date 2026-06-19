from django.db import migrations


# A bad scrape attached several teamless stadiums to the wrong City (and country).
# The stadium NAME is the trustworthy signal here — each name unambiguously
# identifies a real venue whose true city was verified by cross-checking the name.
# We re-point the City FK; matching on (slug, current city name) keeps this
# idempotent and safe to re-run.
#
# Each entry: stadium slug, wrong (from) city, correct (to) city, and any City
# fields to seed when the correct city does not yet exist in the DB.
FIXES = [
    {
        "slug": "nicolae-dobrin",          # Stadionul Nicolae Dobrin — FC Argeș
        "from": ("Bucharest", "Romania"),
        "to": ("Pitești", "Romania"),
        "wiki": "https://en.wikipedia.org/wiki/Pite%C8%99ti",
    },
    {
        "slug": "hybel-arena-horsens",     # AC Horsens' ground (CASA/Hybel Arena)
        "from": ("Bucharest", "Romania"),
        "to": ("Horsens", "Denmark"),
        "wiki": "https://en.wikipedia.org/wiki/Horsens",
    },
    {
        "slug": "gradski-stadion-gostivar",  # City Stadium of Gostivar, not Tetovo
        "from": ("Tetovo", "North Macedonia"),
        "to": ("Gostivar", "North Macedonia"),
        "wiki": "https://en.wikipedia.org/wiki/Gostivar",
    },
    {
        "slug": "sportplatz-irschen",      # ASKÖ Irschen, Carinthia, Austria
        "from": ("Korçë", "Albania"),
        "to": ("Irschen", "Austria"),
        "wiki": "https://en.wikipedia.org/wiki/Irschen",
    },
    {
        "slug": "robin-park-arena",        # Robin Park, Wigan, England
        "from": ("Daugavpils", "Latvia"),
        "to": ("Wigan", "England"),
        "wiki": "https://en.wikipedia.org/wiki/Robin_Park_Arena",
    },
    {
        "slug": "campo-de-jogos-dr-marques-dos-santos",  # Sertanense FC, Sertã, PT
        "from": ("Differdange", "Luxembourg"),
        "to": ("Sertã", "Portugal"),
        "wiki": "https://en.wikipedia.org/wiki/Sert%C3%A3",
    },
]


def _move(Stadium, City, slug, src, dst, wiki):
    """Re-point Stadium <slug>'s city from src=(name,country) to dst=(name,country)."""
    target, created = City.objects.get_or_create(
        name=dst[0],
        country=dst[1],
        defaults={"wikipedia_url": wiki or ""},
    )
    Stadium.objects.filter(slug=slug, city__name=src[0], city__country=src[1]).update(
        city=target
    )


def forwards(apps, schema_editor):
    Stadium = apps.get_model("italiastadiaapp", "Stadium")
    City = apps.get_model("italiastadiaapp", "City")
    for fix in FIXES:
        _move(Stadium, City, fix["slug"], fix["from"], fix["to"], fix["wiki"])


def backwards(apps, schema_editor):
    Stadium = apps.get_model("italiastadiaapp", "Stadium")
    City = apps.get_model("italiastadiaapp", "City")
    for fix in FIXES:
        # Restore the original (incorrect) link, recreating the city if needed.
        _move(Stadium, City, fix["slug"], fix["to"], fix["from"], None)


class Migration(migrations.Migration):

    dependencies = [
        ("italiastadiaapp", "0048_fix_carrarese_and_euro2032_venues"),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
