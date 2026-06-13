import csv
import json
from collections import defaultdict

from django.conf import settings
from django.db.models import F
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.views.decorators.cache import cache_page
from .models import City, LastRefresh, League, Stadium, Team, StadiumDevelopment


def stadium_detail(request, id):
    stadium = get_object_or_404(
        Stadium.objects.select_related("city").prefetch_related("teams"),
        id=id,
    )
    # Back-navigation: ?from_list=<country> when coming from stadium_list,
    # or ?from_list=<country>&from_team_list=1 when coming via team_detail.
    from_list    = request.GET.get("from_list", None)
    back_country = from_list.strip() if from_list else ""
    from_teams   = request.GET.get("from_team_list", "")   # "1" when routed via team_detail

    # Build a JSON-safe logos array for the mini-map split badge
    team_logos = [
        {"url": t.image_url, "name": t.name}
        for t in stadium.teams.all()
        if t.image_url
    ]

    return render(request, "stadium_detail.html", {
        "stadium": stadium,
        "has_coords": stadium.latitude is not None and stadium.longitude is not None,
        "from_list": from_list is not None,
        "back_country": back_country,
        "from_team_list": bool(from_teams),
        "team_logos_json": json.dumps(team_logos),
    })

def stadium_development_detail(request, pk):
    development = get_object_or_404(
        StadiumDevelopment.objects.prefetch_related("future_tenants"),
        pk=pk
    )

    return render(request, "stadium_development_detail.html", {
        "development": development
    })

@cache_page(60 * 60)
def stadium_developments_geojson(request):
    features = []

    qs = StadiumDevelopment.objects.select_related(
        "stadium__city"
    ).prefetch_related("future_tenants")

    for s in qs:
        if s.latitude is None or s.longitude is None:
            continue

        country = s.country or (
            s.stadium.city.country if s.stadium and s.stadium.city else ""
        )
        city = s.stadium.city.name if s.stadium and s.stadium.city else ""

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
                "country": country,
                "city": city,
                "future_tenants": [
                    {"id": t.id, "name": t.name, "image_url": t.image_url or ""}
                    for t in s.future_tenants.all()
                ],
            }
        })

    return JsonResponse({
        "type": "FeatureCollection",
        "features": features
    })

def _build_stadium_features(qs=None):
    """Serialize a Stadium queryset into a list of GeoJSON Feature dicts.

    Shared by stadiums_geojson (HTTP view) and generate_stadiums_json (management
    command that writes the pre-built static file served by WhiteNoise).
    """
    if qs is None:
        qs = Stadium.objects.select_related("city").prefetch_related(
            "teams__league__country"
        )
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
                ],
            },
        })
    return features


@cache_page(60 * 60)  # 1-hour cache — data changes only when scraper runs
def stadiums_geojson(request):
    """
    GeoJSON endpoint for operational stadiums (server-side filtered queries).

    Optional query parameters (all case-sensitive):
      ?country=Italy          — include only stadiums whose teams play in that country
      ?league=Serie+A         — include only stadiums whose teams play in that league
      ?ownership=PUBLIC       — include only stadiums with that ownership value

    map.js does NOT call this endpoint for the initial map load — it fetches
    the pre-built static file (data/stadiums_map.json) served by WhiteNoise.
    These params are available for external API consumers only.
    """
    param_country   = request.GET.get("country",   "").strip()
    param_league    = request.GET.get("league",     "").strip()
    param_ownership = request.GET.get("ownership",  "").strip().upper()

    qs = Stadium.objects.select_related("city").prefetch_related(
        "teams__league__country"
    )
    if param_ownership:
        qs = qs.filter(ownership=param_ownership)
    if param_league:
        qs = qs.filter(teams__league__name=param_league).distinct()
    if param_country:
        qs = qs.filter(teams__league__country__name=param_country).distinct()

    return JsonResponse({
        "type": "FeatureCollection",
        "features": _build_stadium_features(qs),
    })

def index(request):
    return render(request, "index.html")

def _available_countries():
    """Countries that appear in the DB, ordered by UEFA 5-year coefficient rank.

    Uses NULLS LAST so that unranked countries sort after ranked ones on both
    SQLite (which sorts NULLs first by default) and PostgreSQL.
    """
    return list(
        League.objects
        .select_related("country")
        .values_list("country__name", flat=True)
        .distinct()
        .order_by(
            F("country__uefa_rank").asc(nulls_last=True),
            "country__name",
        )
    )


# ── Flag icon helpers ────────────────────────────────────────────────────────

# Map ISO-2 DB codes to flag-icons CSS class suffixes (fi-<code>).
# Standard ISO codes lower-case to "fi-at"; exceptions listed here.
_FLAG_CODE_OVERRIDES = {
    "GB": "gb-eng",   # England uses GB-ENG subdivision flag
    "SC": "gb-sct",   # Scotland
    "WL": "gb-wls",   # Wales
}


def _country_flag_code(code: str) -> str:
    """Return the flag-icons CSS suffix for use as class="fi fi-<result>"."""
    return _FLAG_CODE_OVERRIDES.get(code.upper(), code.lower())


def city_list(request):
    selected_country = request.GET.get("country", "")
    qs = City.objects.prefetch_related("teams").order_by("-population", "name")
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

    # Build ordered list of leagues to use as sections — ranked countries first,
    # unranked countries last (nulls_last), then alphabetically within each group.
    leagues_qs = League.objects.select_related("country").order_by(
        F("country__uefa_rank").asc(nulls_last=True),
        "country__name",
        "division_level",
    )
    if selected_country:
        leagues_qs = leagues_qs.filter(country__name=selected_country)

    # Single pass: assign each stadium to its primary league bucket
    league_map = {lg.id: lg for lg in leagues_qs}
    buckets = {lg_id: [] for lg_id in league_map}
    other_stadia = []

    for stadium in stadia_qs:
        primary = _primary_league(stadium.teams.all())
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
                "flag_code": (
                    _country_flag_code(league.country.code)
                    if league.country else ""
                ),
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


def _primary_league(teams):
    """Return the League with the lowest division_level among the given teams."""
    best = None
    for team in teams:
        if team.league and team.league.country:
            if best is None or team.league.division_level < best.division_level:
                best = team.league
    return best


def _country_flag_emoji(code: str) -> str:
    """Convert ISO-2 country code to flag emoji. England uses tagged flag, not UK flag."""
    OVERRIDES = {"GB": "\U0001F3F4\U000E0067\U000E0062\U000E0065\U000E006E\U000E0067\U000E007F"}
    if code in OVERRIDES:
        return OVERRIDES[code]
    if len(code) == 2:
        return chr(0x1F1E0 + ord(code[0].upper()) - 65) + chr(0x1F1E0 + ord(code[1].upper()) - 65)
    return ""


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
    from_list    = request.GET.get("from_list", None)
    back_country = from_list if from_list else ""
    return render(request, "team_detail.html", {
        "team": team,
        "from_list": from_list is not None,
        "back_country": back_country,
    })


def team_list(request):
    selected_country = request.GET.get("country", "")

    teams_qs = Team.objects.select_related("city", "stadium", "league__country")
    if selected_country:
        teams_qs = teams_qs.filter(league__country__name=selected_country)

    leagues_qs = League.objects.select_related("country").order_by(
        F("country__uefa_rank").asc(nulls_last=True),
        "country__name",
        "division_level",
    )
    if selected_country:
        leagues_qs = leagues_qs.filter(country__name=selected_country)

    team_by_league: dict = defaultdict(list)
    for t in teams_qs:
        team_by_league[t.league_id].append(t)

    sections = []

    for league in leagues_qs:
        section_teams = sorted(
            team_by_league.get(league.id, []),
            key=lambda t: t.average_attendance or 0,
            reverse=True,
        )
        if section_teams:
            sections.append({
                "league": league,
                "league_label": league.name,
                "anchor": f"league-{league.id}",
                "teams": section_teams,
                "flag": _country_flag_emoji(league.country.code) if league.country else "",
                "flag_code": (
                    _country_flag_code(league.country.code)
                    if league.country else ""
                ),
            })

    # Fallback: teams with no league FK
    if not selected_country:
        other_teams = sorted(
            team_by_league.get(None, []),
            key=lambda t: t.average_attendance or 0,
            reverse=True,
        )
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


# ── Export API ────────────────────────────────────────────────────────────────

_EXPORT_FIELDS = [
    "id", "name", "city", "country", "league",
    "capacity", "ownership", "owner_raw",
    "latitude", "longitude", "year_of_construction", "wikipedia_url",
]


def _stadium_to_row(stadium):
    """Return a dict with the exported fields for one stadium."""
    primary_team = next(iter(stadium.teams.all()), None)
    return {
        "id": stadium.id,
        "name": stadium.name,
        "city": stadium.city.name if stadium.city else "",
        "country": (
            primary_team.league.country.name
            if primary_team and primary_team.league and primary_team.league.country
            else ""
        ),
        "league": (
            primary_team.league.name
            if primary_team and primary_team.league
            else ""
        ),
        "capacity": stadium.capacity or "",
        "ownership": stadium.ownership,
        "owner_raw": stadium.owner_raw or "",
        "latitude": float(stadium.latitude) if stadium.latitude else "",
        "longitude": float(stadium.longitude) if stadium.longitude else "",
        "year_of_construction": stadium.year_of_construction or "",
        "wikipedia_url": stadium.wikipedia_url or "",
    }


def export_stadiums(request):
    fmt = request.GET.get("format", "json").lower()
    if fmt not in ("csv", "json"):
        return JsonResponse({"error": "Invalid format. Use csv or json."}, status=400)

    qs = Stadium.objects.select_related("city").prefetch_related(
        "teams__league__country"
    )

    country = request.GET.get("country", "").strip()
    league = request.GET.get("league", "").strip()
    ownership = request.GET.get("ownership", "").strip().upper()

    if country:
        qs = qs.filter(teams__league__country__name=country)
    if league:
        qs = qs.filter(teams__league__name=league)
    if ownership:
        qs = qs.filter(ownership=ownership)

    qs = qs.distinct()
    rows = [_stadium_to_row(s) for s in qs]

    if fmt == "csv":
        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = 'attachment; filename="stadiums.csv"'
        writer = csv.DictWriter(response, fieldnames=_EXPORT_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
        return response

    return JsonResponse(rows, safe=False)


# ── Status API ────────────────────────────────────────────────────────────────

def privacy(request):
    return render(request, "privacy.html", {
        "adsense_client": settings.GOOGLE_ADSENSE_CLIENT,
    })


def api_status(request):
    refresh = LastRefresh.objects.filter(pk=1).first()
    return JsonResponse({
        "stadium_count": Stadium.objects.count(),
        "last_refresh": refresh.ran_at.isoformat() if refresh and refresh.ran_at else None,
        "last_refresh_status": refresh.status if refresh else None,
        "last_refresh_detail": refresh.detail if refresh else None,
    })
