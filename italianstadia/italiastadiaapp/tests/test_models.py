import pytest

from italiastadiaapp.models import City, Country, League, Stadium, Team, StadiumDevelopment


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


@pytest.mark.django_db
def test_country_and_league_str():
    # Use get_or_create — data migration may have already seeded Italy
    country, _ = Country.objects.get_or_create(name="Italy", defaults={"code": "IT"})
    assert str(country) == "Italy"

    league, _ = League.objects.get_or_create(
        name="Serie A", country=country, defaults={"division_level": 1}
    )
    assert "Serie A" in str(league)
    assert "Italy" in str(league)


@pytest.mark.django_db
def test_league_ordering():
    # Use get_or_create — data migration may have already seeded these rows
    country, _ = Country.objects.get_or_create(name="Italy", defaults={"code": "IT"})
    League.objects.get_or_create(name="Serie C", country=country, defaults={"division_level": 3})
    League.objects.get_or_create(name="Serie A", country=country, defaults={"division_level": 1})
    League.objects.get_or_create(name="Serie B", country=country, defaults={"division_level": 2})

    names = list(League.objects.filter(country=country).values_list("name", flat=True))
    assert names == ["Serie A", "Serie B", "Serie C"]