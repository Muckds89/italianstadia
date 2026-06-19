"""
Clear individual teams whose Transfermarkt verein ID resolves to a different club
(verified with `audit_team_links`): the link sends users to the wrong club and the
crest (wappen/<id>.png) inherits the same wrong ID. Matched by verein ID (precise).
Wikipedia links are correct and kept. Latvia/Montenegro were re-checked and are fine
(earlier flags were diacritic/abbreviation false positives, now handled by the audit).

  FK Željezničar      verein/2493  -> "SV Waren 09" (Germany)
  FK Sloga Doboj      verein/17660 -> "Avaí FC B" (Brazil)
  Vestri Ísafjörður   verein/18940 -> "R Knokke FC" (Belgium)
  Valur Reykjavík     verein/3397  -> dead (404)
  KTP Kotka           verein/8780  -> "Sligo Rovers" (Ireland)
"""
from django.db import migrations

WRONG_VEREIN_IDS = ["verein/2493", "verein/17660", "verein/18940",
                    "verein/3397", "verein/8780"]


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
        ("italiastadiaapp", "0058_clear_malta_wrong_tm_links"),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
