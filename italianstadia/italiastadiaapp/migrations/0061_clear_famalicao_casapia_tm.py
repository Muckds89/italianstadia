"""
Full-league `audit_team_links` sweep (713 teams) found 2 more genuinely wrong
Transfermarkt links (the other flags were diacritic/exonym false positives — links OK):
  FC Famalicão  verein/3664 -> "Borussia Wendschott" (Germany)
  Casa Pia AC   verein/9607 -> "Harlow Town" (England)
Clear the wrong link + TM-derived crest (wiki links kept). Re-source correct IDs later.
"""
from django.db import migrations

WRONG_VEREIN_IDS = ["verein/3664", "verein/9607"]


def forwards(apps, schema_editor):
    Team = apps.get_model("italiastadiaapp", "Team")
    for vid in WRONG_VEREIN_IDS:
        for t in Team.objects.filter(transfermarkt_url__contains=vid):
            changed = ["transfermarkt_url"]
            t.transfermarkt_url = ""
            if t.image_url and "tmssl" in t.image_url:
                t.image_url = ""
                changed.append("image_url")
            t.save(update_fields=changed)


def backwards(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("italiastadiaapp", "0060_more_national_teams"),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
