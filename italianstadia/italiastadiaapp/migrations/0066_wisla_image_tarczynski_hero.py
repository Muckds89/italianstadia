"""
- Wisła Kraków (Stadion Miejski (Kraków)) had no image (the I Liga scrape's
  get_or_create matched the existing row and never set one) → add a CC hero + gallery.
- Tarczyński Arena's hero was a non-free /wikipedia/en/ PNG with good Commons photos in
  extra_images → drop the non-free first image and promote the first Commons photo.
All images CC from Wikimedia Commons, credited.
"""
from django.db import migrations

WISLA_HERO = "https://upload.wikimedia.org/wikipedia/commons/e/ea/Nowy_stadion_Wis%C5%82y_Krak%C3%B3w.jpg"
WISLA_CREDIT = "Piotr Drabik / Wikimedia Commons / CC BY 2.0"
WISLA_EXTRAS = [
    {"url": "https://upload.wikimedia.org/wikipedia/commons/4/4c/Stadion_Wisly_Krakow.jpg",
     "credit": "Piotr Drabik / Wikimedia Commons / CC BY 2.0"},
    {"url": "https://upload.wikimedia.org/wikipedia/commons/9/92/Wis%C5%82a_Stadium_fa%C3%A7ade.jpg",
     "credit": "Piotr Drabik / Wikimedia Commons / CC BY 2.0"},
    {"url": "https://upload.wikimedia.org/wikipedia/commons/d/d9/Stadion_przed_meczem.jpg",
     "credit": "Piotr Drabik / Wikimedia Commons / CC BY 2.0"},
]


def forwards(apps, schema_editor):
    Stadium = apps.get_model("italiastadiaapp", "Stadium")

    for s in Stadium.objects.filter(name="Stadion Miejski (Kraków)"):
        if not s.image_url:
            s.image_url = WISLA_HERO
            s.image_credit = WISLA_CREDIT
            s.extra_images = WISLA_EXTRAS
            s.save(update_fields=["image_url", "image_credit", "extra_images"])

    for s in Stadium.objects.filter(name="Tarczyński Arena"):
        if s.image_url and "/wikipedia/en/" in s.image_url and s.extra_images:
            first = s.extra_images[0]
            s.image_url = first["url"]
            s.image_credit = first.get("credit", "")
            s.extra_images = s.extra_images[1:]
            s.save(update_fields=["image_url", "image_credit", "extra_images"])


def backwards(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("italiastadiaapp", "0065_cleanup_teamless_and_dup"),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
