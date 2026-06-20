"""
Add existing Polish stadiums to the Euro 2036 Poland bid (they were already in the
DB from the Ekstraklasa scrape). Brings the Poland bid to 9 venues; Zawisza Bydgoszcz
(Stadion Zdzisława Krzyszkowiaka) will be added with the Polish 2nd-tier scrape → 10.
"""
from django.db import migrations

TOURNAMENT = "UEFA Euro 2036"
ADD = [
    "Stadion Miejski im. Marszałka Józefa Piłsudskiego",  # Legia Warsaw
    "Arena Zabrze",
    "Stadion Widzewa",                                     # Łódź
]


def forwards(apps, schema_editor):
    Stadium = apps.get_model("italiastadiaapp", "Stadium")
    for name in ADD:
        for s in Stadium.objects.filter(name=name):
            tours = list(s.tournaments or [])
            if any(t.get("tournament") == TOURNAMENT for t in tours):
                continue
            tours.append({"tournament": TOURNAMENT, "year": 2036,
                          "status": "CANDIDATE", "bid": "Poland"})
            s.tournaments = tours
            s.save(update_fields=["tournaments"])


def backwards(apps, schema_editor):
    Stadium = apps.get_model("italiastadiaapp", "Stadium")
    for s in Stadium.objects.filter(name__in=ADD):
        tours = [t for t in (s.tournaments or []) if t.get("tournament") != TOURNAMENT]
        if len(tours) != len(s.tournaments or []):
            s.tournaments = tours
            s.save(update_fields=["tournaments"])


class Migration(migrations.Migration):

    dependencies = [
        ("italiastadiaapp", "0063_enrich_polish_bid_stadiums"),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
