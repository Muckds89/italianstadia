"""
The entire Maltese league was scraped with wrong Transfermarkt verein IDs — every
club's link resolved to a foreign club (e.g. Hibernians FC → "BSC Rehberge", Ħamrun
Spartans → "Hermeskeiler SV"), and the crest (wappen/<id>.png) inherited the same
wrong ID. Verified with `audit_team_links --country Malta` (11/12 wrong, 1 dead 404).

We can't send users to the wrong club, so clear the bad Transfermarkt URL and the
TM-derived crest for all Maltese teams. Correct IDs to be re-sourced later. The
Wikipedia links for these clubs are correct and are left untouched.
"""
from django.db import migrations


def forwards(apps, schema_editor):
    Team = apps.get_model("italiastadiaapp", "Team")
    qs = Team.objects.filter(league__country__name="Malta")
    for t in qs:
        changed = []
        if t.transfermarkt_url:
            t.transfermarkt_url = ""
            changed.append("transfermarkt_url")
        if t.image_url and "tmssl" in t.image_url:
            t.image_url = ""
            changed.append("image_url")
        if changed:
            t.save(update_fields=changed)


def backwards(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("italiastadiaapp", "0057_fix_misnamed_stadiums"),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
