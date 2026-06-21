"""
Naftan Novopolotsk's home, Atlant Stadium, was scraped with an empty Wikipedia link
and no photo. Point it at the Atlant Stadium article and add the Commons (PD) photo.
"""
from django.db import migrations

STAD_WIKI = "https://en.wikipedia.org/wiki/Atlant_Stadium"
STAD_IMG = "https://upload.wikimedia.org/wikipedia/commons/d/d8/StadAtlant.JPG"
STAD_CREDIT = "Артём Д / Wikimedia Commons (Public domain)"


def forwards(apps, schema_editor):
    Stadium = apps.get_model("italiastadiaapp", "Stadium")
    for s in Stadium.objects.filter(name="Atlant Stadium"):
        if not s.wikipedia_url:
            s.wikipedia_url = STAD_WIKI
        if not s.image_url:
            s.image_url = STAD_IMG
            s.image_credit = STAD_CREDIT
        s.save(update_fields=["wikipedia_url", "image_url", "image_credit"])


def backwards(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("italiastadiaapp", "0068_torpedo_zhodino_fixes"),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
