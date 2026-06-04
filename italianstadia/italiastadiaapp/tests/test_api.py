import pytest
from django.urls import reverse

from italiastadiaapp.models import (
    City,
    Country,
    League,
    Stadium,
    StadiumDevelopment,
    Team,
)


@pytest.mark.django_db
def test_stadiums_geojson_returns_valid_feature_collection(client):
    city = City.objects.create(
        name="Test City",
        population=100000,
        country="Italy",
    )

    Stadium.objects.create(
        name="Test Stadium",
        city=city,
        latitude=45.0,
        longitude=9.0,
        ownership="PUBLIC",
    )

    response = client.get(reverse("italiastadiaapp:stadiums_geojson"))

    assert response.status_code == 200

    data = response.json()

    assert data["type"] == "FeatureCollection"
    assert len(data["features"]) == 1
    feature = data["features"][0]
    assert feature["geometry"]["coordinates"] == [9.0, 45.0]
    assert "country" in feature["properties"]


@pytest.mark.django_db
def test_stadiums_geojson_team_league_fields(client):
    # Use get_or_create — data migration may have already seeded Italy / Serie A
    country, _ = Country.objects.get_or_create(name="Italy", defaults={"code": "IT"})
    league, _ = League.objects.get_or_create(
        name="Serie A", country=country, defaults={"division_level": 1}
    )

    city = City.objects.create(name="Milan", population=1300000, country="Italy")
    stadium = Stadium.objects.create(
        name="San Siro", city=city, latitude=45.478, longitude=9.124, ownership="PUBLIC"
    )
    Team.objects.create(
        name="AC Milan", city=city, stadium=stadium, tier=1, league=league
    )

    response = client.get(reverse("italiastadiaapp:stadiums_geojson"))
    assert response.status_code == 200

    teams = response.json()["features"][0]["properties"]["teams"]
    assert len(teams) == 1
    t = teams[0]
    assert "league_id" in t
    assert "league_name" in t
    assert "division_level" in t
    assert "country" in t
    assert t["league_name"] == "Serie A"
    assert t["division_level"] == 1
    assert t["country"] == "Italy"
    assert "country_rank" in t  # UEFA rank exposed in GeoJSON for map sorting
    assert "image_url" in t     # required for badge marker rendering


@pytest.mark.django_db
def test_stadium_developments_geojson(client):

    StadiumDevelopment.objects.create(
        name="Test New Stadium",
        project_type="NEW",
        status="PLANNING",
        future_capacity=30000,
        estimated_opening=2028,
        latitude=45.0,
        longitude=9.0,
    )

    response = client.get(reverse("italiastadiaapp:stadium_developments_geojson"))

    assert response.status_code == 200

    data = response.json()

    assert data["type"] == "FeatureCollection"
    assert len(data["features"]) == 1