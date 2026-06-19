"""
Enrich the three teamless Turkish UEFA Euro 2032 candidate stadiums with original
SEO descriptions, accurate facts, and freely-licensed (CC BY-SA 4.0) hero images
from Wikimedia Commons. Descriptions are original prose written from facts (not
copied from any source). Rows are locked so the weekly scrape can't regress them.
"""
from django.db import migrations


STADIUMS = {
    "Timsah Arena": {
        "capacity": 43361,
        "year_of_construction": 2015,
        "architect": "Hasan Sözüneri",
        "wikipedia_url": "https://en.wikipedia.org/wiki/Centennial_Atat%C3%BCrk_Stadium",
        "image_url": "https://upload.wikimedia.org/wikipedia/commons/f/fb/Bursa_Metropolitan_Municipality_Stadium_%2815.11.2025%29.jpg",
        "image_credit": "Eemirrgs / Wikimedia Commons (CC BY-SA 4.0)",
        "description": (
            "Timsah Arena, officially the Centennial Atatürk Stadium, is a 43,361-seat "
            "football stadium in Bursa, Turkey, opened on 21 December 2015 as the home of "
            "Bursaspor. Designed by Hasan Sözüneri and owned by Turkey's Ministry of Youth "
            "and Sports, it is famous for the giant crocodile head built into the north "
            "stand — 'timsah' is Turkish for crocodile. The arena is one of Turkey's "
            "candidate venues for UEFA Euro 2032."
        ),
    },
    "Yeni Eskişehir Stadyumu": {
        "capacity": 32500,
        "year_of_construction": 2016,
        "architect": "HSY Yapı & Aras İnşaat",
        "wikipedia_url": "https://en.wikipedia.org/wiki/New_Eski%C5%9Fehir_Stadium",
        "image_url": "https://upload.wikimedia.org/wikipedia/commons/e/e9/Yeni_Eski%C5%9Fehir_Atat%C3%BCrk_Stadyumu.jpg",
        "image_credit": "Emekin / Wikimedia Commons (CC BY-SA 4.0)",
        "description": (
            "Yeni Eskişehir Stadyumu, officially the Prof. Dr. Fethi Heper Stadium, is a "
            "32,500-seat football stadium in Eskişehir, Turkey, opened on 20 November 2016 "
            "as the home of Eskişehirspor. It replaced the old Eskişehir Atatürk Stadium and "
            "is named after the club's record goalscorer Fethi Heper. The modern arena is one "
            "of Turkey's candidate venues for UEFA Euro 2032."
        ),
    },
    "Yeni Ankara Stadyumu": {
        "capacity": 51050,
        "architect": "",
        "wikipedia_url": "https://en.wikipedia.org/wiki/New_Ankara_Stadium",
        "image_url": "https://upload.wikimedia.org/wikipedia/commons/a/a1/Yeni_Ankara_19_May%C4%B1s_Stadyumu_in%C5%9Faat%C4%B1%2C_May%C4%B1s_2026.jpg",
        "image_credit": "𐰇𐱅𐰚𐰤 / Wikimedia Commons (CC BY-SA 4.0)",
        "description": (
            "Yeni Ankara Stadyumu (New Ankara Stadium) is a 51,050-seat football stadium "
            "under construction in the Altındağ district of Ankara, Turkey, built on the site "
            "of the historic 19 Mayıs Stadium after groundbreaking in July 2022. Owned by "
            "Turkey's Ministry of Youth and Sports, the domed arena is set to become the "
            "capital's largest stadium and is a candidate venue for UEFA Euro 2032."
        ),
    },
}


def forwards(apps, schema_editor):
    Stadium = apps.get_model("italiastadiaapp", "Stadium")
    for name, data in STADIUMS.items():
        for s in Stadium.objects.filter(name=name):
            for field, value in data.items():
                setattr(s, field, value)
            s.locked = True
            s.save()


def backwards(apps, schema_editor):
    # Content enrichment — nothing to reverse.
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("italiastadiaapp", "0050_stadiumdevelopment_slug_extra_images"),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
