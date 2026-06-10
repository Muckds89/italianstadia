from django.db import migrations

EUROPEAN_COUNTRIES = [
    ("Albania", "AL"),
    ("Andorra", "AD"),
    ("Armenia", "AM"),
    ("Austria", "AT"),
    ("Azerbaijan", "AZ"),
    ("Belarus", "BY"),
    ("Belgium", "BE"),
    ("Bosnia and Herzegovina", "BA"),
    ("Bulgaria", "BG"),
    ("Croatia", "HR"),
    ("Cyprus", "CY"),
    ("Czech Republic", "CZ"),
    ("Denmark", "DK"),
    ("England", "GB"),
    ("Estonia", "EE"),
    ("Finland", "FI"),
    ("France", "FR"),
    ("Georgia", "GE"),
    ("Germany", "DE"),
    ("Greece", "GR"),
    ("Hungary", "HU"),
    ("Iceland", "IS"),
    ("Ireland", "IE"),
    ("Italy", "IT"),
    ("Kosovo", "XK"),
    ("Latvia", "LV"),
    ("Liechtenstein", "LI"),
    ("Lithuania", "LT"),
    ("Luxembourg", "LU"),
    ("Malta", "MT"),
    ("Moldova", "MD"),
    ("Monaco", "MC"),
    ("Montenegro", "ME"),
    ("Netherlands", "NL"),
    ("North Macedonia", "MK"),
    ("Norway", "NO"),
    ("Poland", "PL"),
    ("Portugal", "PT"),
    ("Romania", "RO"),
    ("Russia", "RU"),
    ("San Marino", "SM"),
    ("Scotland", "SC"),
    ("Serbia", "RS"),
    ("Slovakia", "SK"),
    ("Slovenia", "SI"),
    ("Spain", "ES"),
    ("Sweden", "SE"),
    ("Switzerland", "CH"),
    ("Turkey", "TR"),
    ("Ukraine", "UA"),
    ("Wales", "WL"),
]


def seed_countries(apps, schema_editor):
    Country = apps.get_model("italiastadiaapp", "Country")
    for name, code in EUROPEAN_COUNTRIES:
        Country.objects.get_or_create(name=name, defaults={"code": code})


def unseed_countries(apps, schema_editor):
    # Only remove countries that have no leagues attached — safe to reverse
    Country = apps.get_model("italiastadiaapp", "Country")
    League = apps.get_model("italiastadiaapp", "League")
    seeded_names = {name for name, _ in EUROPEAN_COUNTRIES}
    has_leagues = set(League.objects.values_list("country_id", flat=True))
    Country.objects.filter(
        name__in=seeded_names
    ).exclude(
        id__in=has_leagues
    ).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("italiastadiaapp", "0029_alter_team_num_of_titles"),
    ]

    operations = [
        migrations.RunPython(seed_countries, reverse_code=unseed_countries),
    ]
