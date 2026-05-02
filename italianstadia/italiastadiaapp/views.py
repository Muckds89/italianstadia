from django.shortcuts import render
from django.http import HttpResponse
from .models import City,Stadium,Team

from django.http import JsonResponse

def stadium_detail(request, id):
    stadium = Stadium.objects.get(id=id)
    return render(request, "stadium_detail.html", {"stadium": stadium})

def stadiums_geojson(request):
    features = []

    for s in Stadium.objects.all():
        if s.latitude and s.longitude:
            main_team = s.teams.first()

            features.append({
                "type": "Feature",
                "geometry": {
                    "type": "Point",
                    "coordinates": [s.longitude, s.latitude],
                },
                "properties": {
                    "id": s.id,
                    "name": s.name,
                    "city": s.city.name if s.city else "",
                    "capacity": s.capacity,
                    "team": main_team.name if main_team else "",
                    "tier": main_team.tier if main_team else "",
                    "tier_name": main_team.get_tier_display() if main_team else "",
                    "wikipedia_url": s.wikipedia_url or "",
                    "transfermarkt_url": s.transfermarkt_url or "",
                }
            })

    return JsonResponse({
        "type": "FeatureCollection",
        "features": features
    })      

def stadiums_json(request):
    data = []

    for s in Stadium.objects.all():
        data.append({
            "id": s.id,
            "name": s.name,
            "city": s.city.name if s.city else "",
            "lat": s.latitude,
            "lng": s.longitude,
        })

    return JsonResponse(data, safe=False)

# Create your views here.
# def home(request):
#     return HttpResponse("Hello World")
def index(request):
    stadiums = Stadium.objects.all()

    return render(request, "index.html", {
        "stadiums": stadiums
    })
    return render(request,'italianstadiaapp/index.html')

def city_list(request):
    cities = City.objects.all()
    if cities is None:
        return HttpResponse(status=404, content="city not found")
    else:
        return render(request,'city_list.html',{'cities': cities})

def stadium_list(request):
    stadia = Stadium.objects.all()
    if stadia is None:
        return HttpResponse(status=404, content="stadium not found")
    else:
        return render(request,'stadium_list.html',{'stadia': stadia})

def team_list(request):
    teams = Team.objects.all()
    if teams is None:
        return HttpResponse(status=404, content="team not found")
    else:
        return render(request,'team_list.html',{'teams': teams})
    


