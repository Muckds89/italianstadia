from django.db import migrations


def mark_national_teams(apps, schema_editor):
    Team = apps.get_model("italiastadiaapp", "Team")
    Team.objects.filter(
        league__name="National Football Team"
    ).update(is_national=True)


class Migration(migrations.Migration):

    dependencies = [
        ("italiastadiaapp", "0043_team_is_national_alter_team_tier"),
    ]

    operations = [
        migrations.RunPython(mark_national_teams, migrations.RunPython.noop),
    ]
