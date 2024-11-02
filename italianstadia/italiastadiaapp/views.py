from django.shortcuts import render
from django.http import HttpResponse
from .models import City,Stadium,Team

# Create your views here.
# def home(request):
#     return HttpResponse("Hello World")
def index(request):
    return render(request,'italianstadiaapp/index.html')

def city_list(request):
    cities = City.objects.all()
    if cities is None:
        return HttpResponse(status=404, content="city not found")
    else:
        return render(request,'italianstadiaapp/city_list.html',{'cities': cities})

def stadium_list(request):
    stadia = Stadium.objects.all()
    if stadia is None:
        return HttpResponse(status=404, content="stadium not found")
    else:
        return render(request,'italianstadiaapp/stadium_list.html',{'stadia': stadia})

def team_list(request):
    teams = Team.objects.all()
    if teams is None:
        return HttpResponse(status=404, content="team not found")
    else:
        return render(request,'italianstadiaapp/team_list.html',{'teams': teams})
