"""
Belarus corrections after the Belarusian Premier League scrape:
- FK Baranovichi's Wikipedia link pointed at a person ("David Samedov") → fix to the club
  page, and rename its stadium "City Stadium Baranovichi" → "Lokomotiv Stadium".
- Classify the stadiums the scrape left UNKNOWN (no owner infobox row) per the owner's
  research: mostly PUBLIC (city/regional/state grounds), with two MIXED (Torpedo-BelAZ =
  BelAZ industrial + state; Atlant = historically the state oil company Naftan).
(NATIONALITY_MAP gained "Belarus": "Belarusian" so a re-scrape records domestic titles.)
"""
from django.db import migrations
from django.utils.text import slugify

OWNERSHIP = {
    "OSK Brestsky": "PUBLIC",
    "Torpedo Stadium": "MIXED",
    "Yunost Stadium": "PUBLIC",
    "Central Stadium": "PUBLIC",
    "Neman Stadium": "PUBLIC",
    "FC Minsk Stadium": "PUBLIC",
    "Spartak Stadium Mogilev": "PUBLIC",
    "City Stadium Dzerzhinsk": "PUBLIC",
    "Lokomotiv Stadium": "PUBLIC",   # FK Baranovichi (renamed below)
    "Atlant Stadium": "MIXED",
}


def forwards(apps, schema_editor):
    Team = apps.get_model("italiastadiaapp", "Team")
    Stadium = apps.get_model("italiastadiaapp", "Stadium")

    Team.objects.filter(name="FK Baranovichi").update(
        wikipedia_url="https://en.wikipedia.org/wiki/FC_Baranovichi")

    for s in Stadium.objects.filter(name="City Stadium Baranovichi"):
        s.name = "Lokomotiv Stadium"
        base = slugify("Lokomotiv Stadium") or f"stadium-{s.pk}"
        slug = base
        n = 2
        while Stadium.objects.filter(slug=slug).exclude(pk=s.pk).exists():
            slug = f"{base}-{n}"
            n += 1
        s.slug = slug
        s.ownership = "PUBLIC"
        s.save(update_fields=["name", "slug", "ownership"])

    for name, own in OWNERSHIP.items():
        if name == "Lokomotiv Stadium":
            continue  # handled in the rename above
        Stadium.objects.filter(name=name).update(ownership=own)


def backwards(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("italiastadiaapp", "0066_wisla_image_tarczynski_hero"),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
