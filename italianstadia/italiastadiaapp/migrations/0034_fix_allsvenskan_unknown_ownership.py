"""
Fix UNKNOWN ownership for two Allsvenskan stadiums whose Wikipedia
infoboxes have no owner/operator row:

  Grimsta IP (IF Brommapojkarna) — owned by the City of Stockholm
    → ownership = PUBLIC

  Finnvedsvallen (IFK Värnamo) — owned by Värnamo Municipality
    → ownership = PUBLIC

Matched by Transfermarkt stadium URL (stable cross-environment key).
"""

from django.db import migrations


FIXES = [
    (
        "https://www.transfermarkt.com/if-brommapojkarna/stadion/verein/1092",
        "Stockholms stad",
        "PUBLIC",
    ),
    (
        "https://www.transfermarkt.com/ifk-varnamo/stadion/verein/3622",
        "Värnamo Municipality",
        "PUBLIC",
    ),
]


def fix_ownership(apps, schema_editor):
    Stadium = apps.get_model("italiastadiaapp", "Stadium")
    for tm_url, owner_raw, ownership in FIXES:
        Stadium.objects.filter(transfermarkt_url=tm_url).update(
            owner_raw=owner_raw,
            ownership=ownership,
        )


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("italiastadiaapp", "0033_fix_ekstraklasa_wiki_urls"),
    ]

    operations = [
        migrations.RunPython(fix_ownership, reverse_code=noop),
    ]
