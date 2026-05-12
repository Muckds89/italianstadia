import pytest
from django.urls import reverse

from italiastadiaapp.models import (
    City,
    Stadium,
    StadiumDevelopment,
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

    response = client.get(reverse("stadiums_geojson"))

    assert response.status_code == 200

    data = response.json()

    assert data["type"] == "FeatureCollection"
    assert len(data["features"]) == 1
    assert data["features"][0]["geometry"]["coordinates"] == [9.0, 45.0]


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

    response = client.get(reverse("stadium_developments_geojson"))

    assert response.status_code == 200

    data = response.json()

    assert data["type"] == "FeatureCollection"
    assert len(data["features"]) == 1