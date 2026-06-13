import django, os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'italianstadia.settings')
django.setup()
from italiastadiaapp.models import Stadium, Team

print("--- A. Le Coq Arena entries ---")
lecq = Stadium.objects.filter(name__icontains='Le Coq').values('id','name','wikipedia_url','city__name')
for s in lecq:
    teams = list(Team.objects.filter(stadium_id=s['id']).values_list('name', flat=True))
    print(f"ID={s['id']} | {s['name']} | wiki={s['wikipedia_url']} | city={s['city__name']} | teams={teams}")

print("\n--- All Estonian stadiums ---")
est = Stadium.objects.filter(city__country__code='EE').values('id','name','wikipedia_url','capacity','ownership')
for s in est:
    teams = list(Team.objects.filter(stadium_id=s['id']).values_list('name', flat=True))
    print(f"ID={s['id']} | {s['name']} | cap={s['capacity']} | own={s['ownership']} | teams={teams}")
    print(f"       wiki={s['wikipedia_url']}")
