import pytest

from italiastadiaapp.models import City, Stadium, Team, StadiumDevelopment


@pytest.mark.django_db
def test_stadium_string_representation():

    city = City.objects.create(
        name="Milan",
        population=1300000,
        country="Italy",
    )

    stadium = Stadium.objects.create(
        name="San Siro",
        city=city,
        latitude=45.4781,
        longitude=9.1240,
        ownership="PUBLIC",
    )

    assert str(stadium) == "San Siro"

@pytest.mark.django_db
def test_team_string_representation_team():

    city = City.objects.create(
        name="Milan",
        population=1300000,
        country="Italy",
    )
    stadium = Stadium.objects.create(
        name="San Siro",
        city=city,
        latitude=45.4781,
        longitude=9.1240,
        ownership="PUBLIC",
    )
    
    team = Team.objects.create(
        name="AC Milan",
        city=city,
        stadium=stadium,
        tier=1,
        )
    
    assert str(team) == "AC Milan"

@pytest.mark.django_db
def test_stadium_development_string_representation():
    stadium_development = StadiumDevelopment.objects.create(
        name="Test New Stadium",
        project_type="NEW",
        status="PLANNING",
        future_capacity=30000,
        estimated_opening=2028,
        latitude=45.0,
        longitude=9.0,
    )
    assert str(stadium_development) == "Test New Stadium"