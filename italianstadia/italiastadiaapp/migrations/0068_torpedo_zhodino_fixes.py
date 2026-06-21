"""
Torpedo-BelAZ Zhodino fixes (reported after the Belarus scrape):
- Team badge: the scrape stored the Transfermarkt crest (tmssl.akamaized.net), which
  ad/tracking blockers commonly drop, so the badge didn't render. Swap to the club's
  own crest hosted on Wikipedia (upload.wikimedia.org — not blocked).
- Stadium: the scrape left the Wikipedia link blank and no photo. Point it at
  "Torpedo Stadium (Zhodino)" and add the Commons CC BY-SA 3.0 photo.
"""
from django.db import migrations

TEAM_CREST = "https://upload.wikimedia.org/wikipedia/en/8/85/TorpedoZhodinoLogo.png"
STAD_WIKI = "https://en.wikipedia.org/wiki/Torpedo_Stadium_(Zhodino)"
STAD_IMG = "https://upload.wikimedia.org/wikipedia/commons/9/91/Torpedo_stadium_Zhodino_west_stand_03.jpg"
STAD_CREDIT = "Griser / Wikimedia Commons / CC BY-SA 3.0"


def forwards(apps, schema_editor):
    Team = apps.get_model("italiastadiaapp", "Team")
    Stadium = apps.get_model("italiastadiaapp", "Stadium")

    for t in Team.objects.filter(name="Torpedo-BelAZ Zhodino"):
        t.image_url = TEAM_CREST
        t.image_credit = "Torpedo-BelAZ Zhodino crest (fair use)"
        t.save(update_fields=["image_url", "image_credit"])
        s = t.stadium
        if s and s.name == "Torpedo Stadium":
            s.wikipedia_url = STAD_WIKI
            if not s.image_url:
                s.image_url = STAD_IMG
                s.image_credit = STAD_CREDIT
            s.save(update_fields=["wikipedia_url", "image_url", "image_credit"])


def backwards(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("italiastadiaapp", "0067_belarus_corrections"),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
