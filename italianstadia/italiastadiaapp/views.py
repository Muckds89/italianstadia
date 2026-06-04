from django.shortcuts import get_object_or_404, render
from django.http import JsonResponse
from .models import City, League, Stadium, Team, StadiumDevelopment


def stadium_detail(request, id):
    stadium = get_object_or_404(
        Stadium.objects.select_related("city").prefetch_related("teams"),
        id=id,
    )
    return render(request, "stadium_detail.html", {
        "stadium": stadium,
        "has_coords": stadium.latitude is not None and stadium.longitude is not None,
    })

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
                "stadium_id": s.stadium_id,
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
    """
    GeoJSON endpoint for operational stadiums.

    Optional query parameters (all case-sensitive):
      ?country=Italy          — include only stadiums whose teams play in that country
      ?league=Serie+A         — include only stadiums whose teams play in that league
      ?ownership=PUBLIC       — include only stadiums with that ownership value
                                (PUBLIC | PRIVATE | MIXED | UNKNOWN)

    All three can be combined. map.js fetches with no parameters and filters
    client-side; these params are available for external API consumers and
    future server-side optimisation as the dataset grows past ~500 stadiums.
    """
    param_country   = request.GET.get("country",   "").strip()
    param_league    = request.GET.get("league",     "").strip()
    param_ownership = request.GET.get("ownership",  "").strip().upper()

    qs = Stadium.objects.select_related("city").prefetch_related(
        "teams__league__country"
    )

    # Push ownership filter to the DB — it lives directly on Stadium
    if param_ownership:
        qs = qs.filter(ownership=param_ownership)

    # Push league filter to the DB via team relationship
    if param_league:
        qs = qs.filter(teams__league__name=param_league).distinct()

    # Push country filter to the DB via team → league → country
    if param_country:
        qs = qs.filter(teams__league__country__name=param_country).distinct()

    features = []

    for s in qs:
        if s.latitude is None or s.longitude is None:
            continue

        teams = list(s.teams.all())
        city_country = s.city.country if s.city else ""

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
                "country": city_country,
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
                        "league_id": t.league_id,
                        "league_name": t.league.name if t.league else t.get_tier_display(),
                        "division_level": t.league.division_level if t.league else t.tier,
                        "country": (
                            t.league.country.name
                            if t.league and t.league.country
                            else city_country
                        ),
                        "country_rank": (
                            t.league.country.uefa_rank
                            if t.league and t.league.country
                            else None
                        ),
                        "image_url": t.image_url or "",
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

def _available_countries():
    """Countries that appear in the DB, ordered by UEFA 5-year coefficient rank."""
    return list(
        League.objects
        .select_related("country")
        .values_list("country__name", flat=True)
        .distinct()
        .order_by("country__uefa_rank", "country__name")
    )


def city_list(request):
    selected_country = request.GET.get("country", "")
    qs = City.objects.all().order_by("-population", "name")
    if selected_country:
        qs = qs.filter(country=selected_country)
    return render(request, "city_list.html", {
        "cities": qs,
        "countries": _available_countries(),
        "selected_country": selected_country,
    })


def stadium_list(request):
    selected_country = request.GET.get("country", "")

    stadia_qs = (
        Stadium.objects
        .select_related("city")
        .prefetch_related("teams__league__country")
    )
    if selected_country:
        stadia_qs = stadia_qs.filter(
            teams__league__country__name=selected_country
        ).distinct()

    # Build ordered list of leagues to use as sections
    leagues_qs = League.objects.select_related("country").order_by(
        "country__name", "division_level"
    )
    if selected_country:
        leagues_qs = leagues_qs.filter(country__name=selected_country)

    # Single pass: assign each stadium to its primary league bucket
    league_map = {lg.id: lg for lg in leagues_qs}
    buckets = {lg_id: [] for lg_id in league_map}
    other_stadia = []

    for stadium in stadia_qs:
        primary = _primary_league(stadium)
        if primary and primary.id in league_map:
            buckets[primary.id].append(stadium)
        elif not selected_country:
            other_stadia.append(stadium)

    sections = []
    for league in league_map.values():
        stadia_in_section = sorted(buckets[league.id], key=lambda s: s.capacity or 0, reverse=True)
        if stadia_in_section:
            sections.append({
                "league": league,
                "league_label": league.name,
                "anchor": f"league-{league.id}",
                "stadia": stadia_in_section,
            })

    if other_stadia:
        sections.append({
            "league": None,
            "league_label": "Other",
            "anchor": "other",
            "stadia": sorted(other_stadia, key=lambda s: s.capacity or 0, reverse=True),
        })

    return render(request, "stadium_list.html", {
        "sections": sections,
        "countries": _available_countries(),
        "selected_country": selected_country,
    })


def _primary_league(stadium):
    """Return the League with the lowest division_level among a stadium's teams."""
    best = None
    for team in stadium.teams.all():
        if team.league and team.league.country:
            if best is None or team.league.division_level < best.division_level:
                best = team.league
    return best


def team_detail(request, pk):
    team = get_object_or_404(
        Team.objects.select_related(
            "city",
            "stadium__city",
            "league__country",
            "under_development_stadium",
        ),
        pk=pk,
    )
    return render(request, "team_detail.html", {"team": team})


def team_list(request):
    selected_country = request.GET.get("country", "")

    teams_qs = Team.objects.select_related("city", "stadium", "league__country")
    if selected_country:
        teams_qs = teams_qs.filter(league__country__name=selected_country)

    leagues_qs = League.objects.select_related("country").order_by(
        "country__name", "division_level"
    )
    if selected_country:
        leagues_qs = leagues_qs.filter(country__name=selected_country)

    sections = []
    assigned_ids = set()

    for league in leagues_qs:
        section_teams = [t for t in teams_qs if t.league_id == league.id]
        section_teams.sort(key=lambda t: t.average_attendance or 0, reverse=True)
        assigned_ids.update(t.id for t in section_teams)
        if section_teams:
            sections.append({
                "league": league,
                "league_label": league.name,
                "anchor": f"league-{league.id}",
                "teams": section_teams,
            })

    # Fallback: teams with no league FK
    if not selected_country:
        other_teams = [t for t in teams_qs if t.id not in assigned_ids]
        other_teams.sort(key=lambda t: t.average_attendance or 0, reverse=True)
        if other_teams:
            sections.append({
                "league": None,
                "league_label": "Other",
                "anchor": "other",
                "teams": other_teams,
            })

    return render(request, "team_list.html", {
        "sections": sections,
        "countries": _available_countries(),
        "selected_country": selected_country,
    })
    


