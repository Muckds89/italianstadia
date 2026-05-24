from django.shortcuts import get_object_or_404, render
from django.http import HttpResponse, JsonResponse
from .models import City, Stadium, Team, StadiumDevelopment


def stadium_detail(request, id):
    stadium = get_object_or_404(
        Stadium.objects.select_related("city").prefetch_related("teams"),
        id=id,
    )
    return render(request, "stadium_detail.html", {"stadium": stadium})

def stadium_development_detail(request, pk):
    development = get_object_or_404(
        StadiumDevelopment.objects.prefetch_related("future_tenants"),
        pk=pk
    )

    return render(request, "stadium_development_detail.html", {
        "development": development
    })

def stadium_developments_geojson(request):
    features = []

    for s in StadiumDevelopment.objects.all():
        if s.latitude is None or s.longitude is None:
            continue

        features.append({
            "type": "Feature",
            "geometry": {
                "type": "Point",
                "coordinates": [float(s.longitude), float(s.latitude)],
            },
            "properties": {
                "id": s.id,
                "name": s.name,
                "project_type": s.get_project_type_display(),
                "status": s.get_status_display(),
                "future_capacity": s.future_capacity,
                "estimated_opening": s.estimated_opening,
                "architect": s.architect or "",
                "developer": s.developer or "",
                "source_url": s.source_url or "",
                "image_url": s.image_url or "",
                "notes": s.notes or "",
            }
        })

    return JsonResponse({
        "type": "FeatureCollection",
        "features": features
    })

def stadiums_geojson(request):
    features = []

    for s in Stadium.objects.prefetch_related("teams").select_related("city"):
        if s.latitude is None or s.longitude is None:
            continue

        teams = list(s.teams.all())

        features.append({
            "type": "Feature",
            "geometry": {
                "type": "Point",
                "coordinates": [float(s.longitude), float(s.latitude)],
            },
            "properties": {
                "id": s.id,
                "name": s.name,
                "city": s.city.name if s.city else "",
                "capacity": s.capacity,
                "ownership": s.ownership,
                "owner_raw": s.owner_raw or "",
                "wikipedia_url": s.wikipedia_url or "",
                "transfermarkt_url": s.transfermarkt_url or "",
                "teams": [
                    {
                        "id": t.id,
                        "name": t.name,
                        "tier": t.tier,
                        "tier_name": t.get_tier_display(),
                        "girone": t.girone or "",
                        "wikipedia_url": t.wikipedia_url or "",
                        "transfermarkt_url": t.transfermarkt_url or "",
                    }
                    for t in teams
                ]
            }
        })

    return JsonResponse({
        "type": "FeatureCollection",
        "features": features
    })

def index(request):
    return render(request, "index.html")

def city_list(request):
    cities = City.objects.all().order_by("-population", "name")
    return render(request, 'city_list.html', {'cities': cities})

def stadium_list(request):
    stadia = (
        Stadium.objects
        .select_related("city")
        .prefetch_related("teams")
        .all()
    )

    tier_sections = {
        "serie-a": {
            "title": "Serie A",
            "stadia": [],
        },
        "serie-b": {
            "title": "Serie B",
            "stadia": [],
        },
        "serie-c": {
            "title": "Serie C",
            "stadia": [],
        },
    }

    for stadium in stadia:
        tiers = {team.tier for team in stadium.teams.all()}

        if 1 in tiers:
            tier_sections["serie-a"]["stadia"].append(stadium)
        elif 2 in tiers:
            tier_sections["serie-b"]["stadia"].append(stadium)
        elif 3 in tiers:
            tier_sections["serie-c"]["stadia"].append(stadium)

    for section in tier_sections.values():
        section["stadia"].sort(
            key=lambda s: s.capacity or 0,
            reverse=True
        )

    return render(request, "stadium_list.html", {
        "tier_sections": tier_sections,
    })

def team_list(request):
    teams = (
        Team.objects
        .select_related("city", "stadium")
        .all()
    )

    tier_sections = {
        "serie-a": {"title": "Serie A", "teams": []},
        "serie-b": {"title": "Serie B", "teams": []},
        "serie-c": {"title": "Serie C", "teams": []},
    }

    for team in teams:
        if team.tier == 1:
            tier_sections["serie-a"]["teams"].append(team)
        elif team.tier == 2:
            tier_sections["serie-b"]["teams"].append(team)
        elif team.tier == 3:
            tier_sections["serie-c"]["teams"].append(team)

    for section in tier_sections.values():
        section["teams"].sort(
            key=lambda t: t.average_attendance or 0,
            reverse=True
        )

    return render(request, "team_list.html", {
        "tier_sections": tier_sections,
    })
    


