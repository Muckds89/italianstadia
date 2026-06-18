from django.db import migrations


def forwards(apps, schema_editor):
    Stadium = apps.get_model("italiastadiaapp", "Stadium")
    StadiumDevelopment = apps.get_model("italiastadiaapp", "StadiumDevelopment")

    # 1. Carrarese: the scraper attached Rome's Stadio dei Marmi. Correct it to the
    #    actual Carrara ground and lock it so the weekly scrape can't regress it.
    Stadium.objects.filter(slug="comunale-dei-marmi").update(
        name="Stadio dei Marmi",
        address="Carrara",
        latitude="44.065328",
        longitude="10.076805",
        owner_raw="Comune di Carrara",
        ownership="PUBLIC",
        wikipedia_url="https://it.wikipedia.org/wiki/Stadio_dei_Marmi_(Carrara)",
        image_url="https://upload.wikimedia.org/wikipedia/commons/e/e2/CarraraStadioMarmi.JPG",
        extra_images=[],
        locked=True,
    )

    # 2. Add the two missing Euro 2032 candidate venues (Italy).
    entry = {"tournament": "UEFA Euro 2032", "year": 2032, "status": "CANDIDATE"}
    for name in ("New Artemio Franchi", "New Cagliari Stadium"):
        for dev in StadiumDevelopment.objects.filter(name=name):
            tours = list(dev.tournaments or [])
            if not any(t.get("tournament") == "UEFA Euro 2032" for t in tours):
                tours.append(dict(entry))
                dev.tournaments = tours
                dev.save(update_fields=["tournaments"])


def backwards(apps, schema_editor):
    # Data correction — nothing to reverse.
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("italiastadiaapp", "0047_stadium_locked"),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
