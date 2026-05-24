import pytest
from django.urls import reverse


@pytest.mark.django_db
def test_homepage_loads(client):

    response = client.get(reverse("italiastadiaapp:home"))

    assert response.status_code == 200


from italiastadiaapp.models import City, Stadium


@pytest.mark.django_db
def test_stadium_detail_page_loads(client):

    city = City.objects.create(
        name="Rome",
        population=2800000,
        country="Italy",
    )

    stadium = Stadium.objects.create(
        name="Olimpico",
        city=city,
        latitude=41.9339,
        longitude=12.4547,
        ownership="PUBLIC",
    )

    response = client.get(
        reverse("italiastadiaapp:stadium_detail", args=[stadium.id])
    )

    assert response.status_code == 200