import csv
import json
from collections import defaultdict, OrderedDict

from django.conf import settings
from django.db.models import Avg, Count, F, Max, Sum
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.text import slugify
from django.views.decorators.cache import cache_page
from .models import City, LastRefresh, League, Stadium, Team, StadiumDevelopment


def _trim(text, limit=155):
    """Trim to `limit` chars at a word boundary."""
    if len(text) <= limit:
        return text
    return text[:limit].rsplit(" ", 1)[0].rstrip(",.") + "…"


def _stadium_description(stadium):
    parts = [stadium.name]
    cap = getattr(stadium, "capacity", None)
    if cap:
        parts.append(f"{cap:,} capacity")
    city = getattr(stadium, "city", None)
    if city:
        loc = city.name
        if city.country:
            loc += f", {city.country}"
        parts.append(loc)
    year = getattr(stadium, "year_of_construction", None)
    if year:
        parts.append(f"built {year}")
    stype = stadium.get_stadium_type_display() if stadium.stadium_type else None
    surface = stadium.get_surface_display() if stadium.surface else None
    if stype and surface:
        parts.append(f"{stype} roof, {surface.lower()} surface")
    elif stype:
        parts.append(f"{stype} roof")
    teams = list(stadium.teams.all())
    if teams:
        team_names = ", ".join(t.name for t in teams[:3])
        parts.append(f"Home of {team_names}")
    sentence = ". ".join([parts[0]] + [p[0].upper() + p[1:] for p in parts[1:]]) + "."
    return _trim(sentence)


def _team_description(team):
    parts = [team.name]
    if team.league:
        parts.append(team.league.name)
    if team.city:
        loc = team.city.name
        if team.league and team.league.country:
            loc += f", {team.league.country.name}"
        parts.append(loc)
    if team.stadium:
        stad = team.stadium.name
        if team.stadium.capacity:
            stad += f" ({team.stadium.capacity:,} capacity)"
        parts.append(f"Home ground: {stad}")
    if team.founded:
        parts.append(f"Founded {team.founded.year}")
    if team.num_of_titles:
        parts.append(f"{team.num_of_titles} league title{'s' if team.num_of_titles != 1 else ''}")
    sentence = ". ".join([parts[0]] + [p[0].upper() + p[1:] for p in parts[1:]]) + "."
    return _trim(sentence)


def stadium_detail(request, slug):
    stadium = get_object_or_404(
        Stadium.objects.select_related("city").prefetch_related(
            "teams__league__country"
        ),
        slug=slug,
    )
    # Back-navigation: ?from_list=<country> when coming from stadium_list,
    # or ?from_list=<country>&from_team_list=1 when coming via team_detail.
    from_list    = request.GET.get("from_list", None)
    back_country = from_list.strip() if from_list else ""
    from_teams   = request.GET.get("from_team_list", "")   # "1" when routed via team_detail

    # Flag image URLs for national teams (flagcdn.com, handles GB subdivisions)
    team_flag_urls = {}
    for t in stadium.teams.all():
        if t.is_national and t.league and t.league.country:
            code = _country_flag_code(t.league.country.code)
            team_flag_urls[t.pk] = f"https://flagcdn.com/w160/{code}.png"

    # Build a JSON-safe logos array for the mini-map split badge
    # Use flag URL for national teams so the broken SVG badge is not shown
    team_logos = [
        {"url": team_flag_urls.get(t.pk) or t.image_url, "name": t.name}
        for t in stadium.teams.all()
        if team_flag_urls.get(t.pk) or t.image_url
    ]

    return render(request, "stadium_detail.html", {
        "stadium": stadium,
        "has_coords": stadium.latitude is not None and stadium.longitude is not None,
        "from_list": from_list is not None,
        "back_country": back_country,
        "from_team_list": bool(from_teams),
        "team_logos_json": json.dumps(team_logos),
        "team_flag_urls": team_flag_urls,
        "page_description": _stadium_description(stadium),
    })


def stadium_detail_redirect(request, id):
    stadium = get_object_or_404(Stadium, pk=id)
    return redirect("italiastadiaapp:stadium_detail", slug=stadium.slug, permanent=True)


def country_stats(request, country_name):
    stadiums = (
        Stadium.objects
        .select_related("city")
        .prefetch_related("teams__league__country")
        .filter(city__country__iexact=country_name)
    )
    agg = stadiums.filter(capacity__isnull=False).aggregate(
        total_stadiums=Count("id"),
        total_seats=Sum("capacity"),
        avg_capacity=Avg("capacity"),
        max_capacity=Max("capacity"),
    )
    total_stadiums_all = stadiums.count()
    top10 = (
        stadiums
        .filter(capacity__isnull=False)
        .order_by("-capacity")[:10]
    )
    leagues = (
        League.objects
        .select_related("country")
        .filter(country__name__iexact=country_name)
        .order_by("division_level")
    )
    # GeoJSON for mini-map
    map_features = []
    for s in stadiums:
        if s.latitude is None or s.longitude is None:
            continue
        map_features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [float(s.longitude), float(s.latitude)]},
            "properties": {
                "id": s.id,
                "slug": s.slug or str(s.id),
                "name": s.name,
                "capacity": s.capacity,
            },
        })
    geojson = json.dumps({"type": "FeatureCollection", "features": map_features})

    return render(request, "country_stats.html", {
        "country_name": country_name,
        "total_stadiums": total_stadiums_all,
        "total_seats": agg.get("total_seats") or 0,
        "avg_capacity": int(agg.get("avg_capacity") or 0),
        "max_capacity": agg.get("max_capacity") or 0,
        "top10": top10,
        "leagues": leagues,
        "geojson": geojson,
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
                "slug": s.slug or str(s.id),
                "name": s.name,
                "city": s.city.name if s.city else "",
                "country": city_country,
                "capacity": s.capacity,
                "year_of_construction": s.year_of_construction,
                "stadium_type": s.stadium_type or "",
                "surface": s.surface or "",
                "architect": s.architect or "",
                "ownership": s.ownership,
                "owner_raw": s.owner_raw or "",
                "wikipedia_url": s.wikipedia_url or "",
                "transfermarkt_url": s.transfermarkt_url or "",
                "teams": [
                    {
                        "id": t.id,
                        "slug": t.slug,
                        "name": t.name,
                        "is_national": t.is_national,
                        "tier": t.tier,
                        "tier_name": t.get_tier_display() if t.tier else ("National Team" if t.is_national else ""),
                        "girone": t.girone or "",
                        "league_id": t.league_id,
                        "league_name": t.league.name if t.league else ("National Team" if t.is_national else ""),
                        "division_level": t.league.division_level if t.league else (0 if t.is_national else t.tier),
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


def team_detail(request, slug):
    team = get_object_or_404(
        Team.objects.select_related(
            "city",
            "stadium__city",
            "league__country",
            "under_development_stadium",
        ),
        slug=slug,
    )
    from_list    = request.GET.get("from_list", None)
    back_country = from_list if from_list else ""
    return render(request, "team_detail.html", {
        "team": team,
        "from_list": from_list is not None,
        "back_country": back_country,
        "page_description": _team_description(team),
    })


def team_detail_redirect(request, pk):
    team = get_object_or_404(Team, pk=pk)
    return redirect("italiastadiaapp:team_detail", slug=team.slug, permanent=True)


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


def stadium_development_list(request):
    selected_country = request.GET.get("country", "").strip()
    selected_status  = request.GET.get("status",  "").strip()

    qs = (
        StadiumDevelopment.objects
        .select_related("stadium__city")
        .prefetch_related("future_tenants")
        .order_by("country", "estimated_opening", "name")
    )
    if selected_country:
        qs = qs.filter(country=selected_country)
    if selected_status:
        qs = qs.filter(status=selected_status)

    countries = list(
        StadiumDevelopment.objects
        .exclude(country__isnull=True).exclude(country="")
        .values_list("country", flat=True)
        .distinct().order_by("country")
    )

    status_choices = StadiumDevelopment._meta.get_field("status").choices

    by_country = defaultdict(list)
    for dev in qs:
        by_country[dev.country or "Unknown"].append(dev)

    sections = [
        {"country": c, "developments": devs,
         "anchor": "country-" + c.lower().replace(" ", "-")}
        for c, devs in sorted(by_country.items())
    ]

    return render(request, "stadium_development_list.html", {
        "sections": sections,
        "countries": countries,
        "selected_country": selected_country,
        "status_choices": status_choices,
        "selected_status": selected_status,
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


COUNTRY_FLAGS = {
    "England":  "🇬🇧",
    "Wales":    "🇬🇧",
    "Scotland": "🇬🇧",
    "Ireland":  "🇮🇪",
    "Italy":    "🇮🇹",
    "Turkey":   "🇹🇷",
}


def tournament_list(request):
    return redirect("italiastadiaapp:home")


@cache_page(60 * 60)
def tournament_detail(request, slug):
    """Show all venues for a single tournament (Stadium + StadiumDevelopment)."""
    tournament_name = None
    tournament_year = None
    venues = []

    # Pull from operational stadiums
    for stadium in Stadium.objects.select_related("city").exclude(tournaments=[]):
        for entry in stadium.tournaments:
            name = entry.get("tournament", "")
            if slugify(name) == slug:
                tournament_name = name
                tournament_year = entry.get("year")
                venues.append({
                    "name": stadium.name,
                    "city": stadium.city,
                    "capacity": stadium.capacity,
                    "image_url": stadium.image_url,
                    "latitude": stadium.latitude,
                    "longitude": stadium.longitude,
                    "detail_url": reverse("italiastadiaapp:stadium_detail", kwargs={"slug": stadium.slug}),
                    "status": entry.get("status", ""),
                    "matches": entry.get("matches"),
                    "is_development": False,
                })
                break

    # Pull from development stadiums
    for dev in StadiumDevelopment.objects.select_related("stadium__city").exclude(tournaments=[]):
        for entry in dev.tournaments:
            name = entry.get("tournament", "")
            if slugify(name) == slug:
                tournament_name = tournament_name or name
                tournament_year = tournament_year or entry.get("year")
                city = dev.stadium.city if dev.stadium else None
                country = dev.country or (city.country if city else None)
                venues.append({
                    "name": dev.name,
                    "city": city,
                    "country_override": country,
                    "capacity": dev.future_capacity,
                    "image_url": dev.image_url,
                    "latitude": dev.latitude,
                    "longitude": dev.longitude,
                    "detail_url": reverse("italiastadiaapp:stadium_development_detail", kwargs={"pk": dev.id}),
                    "status": entry.get("status", ""),
                    "matches": entry.get("matches"),
                    "is_development": True,
                })
                break

    if not tournament_name:
        raise Http404

    # CONFIRMED first, then CANDIDATE, each group sorted by capacity desc
    venues.sort(key=lambda v: (
        0 if v["status"] == "CONFIRMED" else 1,
        -(v["capacity"] or 0),
    ))

    # Aggregate stats
    confirmed_venues = [v for v in venues if v["status"] == "CONFIRMED"]
    total_capacity = sum(v["capacity"] or 0 for v in confirmed_venues)
    total_matches = sum(v["matches"] or 0 for v in venues if v["matches"])

    def _venue_country(v):
        if v.get("country_override"):
            return v["country_override"]
        return v["city"].country if v.get("city") else "Unknown"

    # Group venues by country
    _country_groups = {}
    for v in venues:
        country = _venue_country(v)
        flag = COUNTRY_FLAGS.get(country, "")
        if country not in _country_groups:
            _country_groups[country] = {"flag": flag, "venues": []}
        _country_groups[country]["venues"].append(v)

    venues_by_country = OrderedDict(sorted(_country_groups.items(), key=lambda item: item[0]))
    multi_country = len(venues_by_country) > 1

    host_country_flags = OrderedDict(
        (c, grp["flag"]) for c, grp in venues_by_country.items()
    )

    # GeoJSON for mini-map
    features = []
    for v in venues:
        if v["latitude"] is None or v["longitude"] is None:
            continue
        features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [float(v["longitude"]), float(v["latitude"])]},
            "properties": {
                "url": v["detail_url"],
                "name": v["name"],
                "capacity": v["capacity"],
                "status": v["status"],
                "matches": v["matches"],
            },
        })
    geojson = json.dumps({"type": "FeatureCollection", "features": features})

    # Build meta description
    host_countries = list(venues_by_country.keys())
    if len(host_countries) == 1:
        host_str = host_countries[0]
    elif len(host_countries) == 2:
        host_str = f"{host_countries[0]} and {host_countries[1]}"
    else:
        host_str = ", ".join(host_countries[:-1]) + f" and {host_countries[-1]}"
    desc_parts = [f"{tournament_name} — {len(confirmed_venues)} confirmed venue{'s' if len(confirmed_venues) != 1 else ''}"]
    if host_str:
        desc_parts.append(f"across {host_str}")
    if total_matches:
        desc_parts.append(f"{total_matches} matches")
    sample_names = [v["name"] for v in confirmed_venues[:3]]
    if sample_names:
        desc_parts.append(", ".join(sample_names))
    tournament_description = _trim(". ".join(desc_parts) + ".")

    return render(request, "tournament_detail.html", {
        "tournament_name": tournament_name,
        "tournament_year": tournament_year,
        "tournament_slug": slug,
        "venues": venues,
        "venues_by_country": venues_by_country,
        "multi_country": multi_country,
        "confirmed_count": len(confirmed_venues),
        "candidate_count": len(venues) - len(confirmed_venues),
        "total_capacity": total_capacity,
        "total_matches": total_matches,
        "host_country_flags": host_country_flags,
        "geojson": geojson,
        "page_description": tournament_description,
    })


# ── Map Export ────────────────────────────────────────────────────────────────

import io
import math
import requests as _requests
from concurrent.futures import ThreadPoolExecutor, as_completed
from django.core.cache import cache
from PIL import Image, ImageDraw, ImageFont

_EXPORT_SIZES = {
    "twitter":   (1500, 500),
    "instagram": (1080, 1080),
    "landscape": (1920, 1080),
}

# Free tile servers — no API key required
_TILE_SERVERS = {
    "dark":      "https://a.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}.png",
    "light":     "https://a.basemaps.cartocdn.com/light_all/{z}/{x}/{y}.png",
    "topo":      "https://tile.openstreetmap.org/{z}/{x}/{y}.png",
    "satellite": "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
}

# Fallback solid colours if tile fetch fails
_STYLE_BACKGROUNDS = {
    "dark":      (18,  22,  36,  255),
    "light":     (240, 242, 245, 255),
    "topo":      (228, 237, 214, 255),
    "satellite": (16,  28,  16,  255),
}

_TILE_SIZE = 256

_SURFACE_COLOURS = {
    "ARTIFICIAL": (245, 197, 66),
    "GRASS":      (76, 175, 80),
    "HYBRID":     (33, 150, 243),
}
_DEFAULT_DOT_COLOUR = (136, 136, 136)

_COUNTRY_PALETTE = [
    (229, 57, 53), (30, 136, 229), (67, 160, 71), (251, 140, 0),
    (142, 36, 170), (0, 172, 193), (216, 27, 96), (124, 179, 66),
    (255, 179, 0), (84, 110, 122), (0, 137, 123), (198, 40, 40),
]


def _parse_export_params(request):
    """Validate and return all export configuration from query params."""
    size_key = request.GET.get("size", "landscape").lower()
    if size_key not in _EXPORT_SIZES:
        size_key = "landscape"
    W, H = _EXPORT_SIZES[size_key]

    style_key = request.GET.get("style", "dark").lower()
    if style_key not in _STYLE_BACKGROUNDS:
        style_key = "dark"

    color_by = request.GET.get("color_by", "surface").lower()
    if color_by not in ("surface", "country", "single"):
        color_by = "surface"

    raw_color = request.GET.get("dot_color", "#f5c542").lstrip("#")
    try:
        single_color = tuple(int(raw_color[i:i+2], 16) for i in (0, 2, 4))
    except Exception:
        single_color = (245, 197, 66)

    return {
        "W": W, "H": H,
        "size_key": size_key,
        "style_key": style_key,
        "color_by": color_by,
        "single_color": single_color,
        "legend": request.GET.get("legend", "1") == "1",
        "north": request.GET.get("north", "0") == "1",
        "labels": request.GET.get("labels", "1") == "1",
        "title": request.GET.get("title", "").strip()[:80],
        # filter params
        "surface": request.GET.get("surface", "").strip().upper(),
        "country": request.GET.get("country", "").strip(),
        "league": request.GET.get("league", "").strip(),
        "ownership": request.GET.get("ownership", "").strip().upper(),
    }


def _get_export_stadiums(params):
    """Return list of dicts for stadiums matching the filter params."""
    qs = Stadium.objects.select_related("city").prefetch_related("teams__league__country")
    if params["surface"]:
        qs = qs.filter(surface=params["surface"])
    if params["country"]:
        qs = qs.filter(city__country=params["country"])
    if params["league"]:
        qs = qs.filter(teams__league__name=params["league"])
    if params["ownership"]:
        qs = qs.filter(ownership=params["ownership"])
    qs = qs.exclude(latitude=None).exclude(longitude=None).distinct()

    results = []
    for s in qs:
        country = s.city.country if s.city else ""
        results.append({
            "name": s.name,
            "lat": float(s.latitude),
            "lon": float(s.longitude),
            "surface": s.surface or "",
            "country": country,
        })
    return results


def _bbox_with_padding(stadiums, pad=0.12):
    lats = [s["lat"] for s in stadiums]
    lons = [s["lon"] for s in stadiums]
    lat_min, lat_max = min(lats), max(lats)
    lon_min, lon_max = min(lons), max(lons)
    lat_pad = max((lat_max - lat_min) * pad, 1.5)
    lon_pad = max((lon_max - lon_min) * pad, 1.5)
    return (
        lon_min - lon_pad, lat_min - lat_pad,
        lon_max + lon_pad, lat_max + lat_pad,
    )


def _merc_y(lat):
    """Latitude → normalized Mercator Y (0 = north pole, 1 = south pole)."""
    lat = max(min(lat, 85.051), -85.051)
    r = math.radians(lat)
    return (1 - math.log(math.tan(r) + 1 / math.cos(r)) / math.pi) / 2


def _lon_lat_to_px(lon, lat, bbox, W, H):
    """Mercator projection: lon/lat → pixel coordinates within the export image."""
    lon_min, lat_min, lon_max, lat_max = bbox
    x = (lon - lon_min) / (lon_max - lon_min) * W
    y = (_merc_y(lat) - _merc_y(lat_max)) / (_merc_y(lat_min) - _merc_y(lat_max)) * H
    return int(x), int(y)


def _fetch_one_tile(z, x, y, style_key):
    """Fetch a single 256×256 tile, caching for 24 h."""
    cache_key = f"tile_{style_key}_{z}_{x}_{y}"
    data = cache.get(cache_key)
    if data:
        return Image.open(io.BytesIO(data)).convert("RGBA")
    url = _TILE_SERVERS[style_key].format(z=z, x=x, y=y)
    headers = {"User-Agent": "StadiumsOfEurope/1.0 (stadiumsofeurope.com)"}
    resp = _requests.get(url, timeout=8, headers=headers)
    resp.raise_for_status()
    cache.set(cache_key, resp.content, 86400)
    return Image.open(io.BytesIO(resp.content)).convert("RGBA")


def _make_background(style_key, W, H, bbox):
    """Stitch free map tiles into a background image, fall back to solid colour on error."""
    lon_min, lat_min, lon_max, lat_max = bbox
    lon_min = max(lon_min, -179.9); lon_max = min(lon_max, 179.9)
    lat_min = max(lat_min, -85.0);  lat_max = min(lat_max, 85.0)

    # Pick zoom so the bbox spans at least the output width or height in pixels
    z = 4
    for z_try in range(7, 2, -1):
        n = 2 ** z_try
        span_x = ((lon_max - lon_min) / 360) * n * _TILE_SIZE
        span_y = (_merc_y(lat_min) - _merc_y(lat_max)) * n * _TILE_SIZE
        if span_x >= W or span_y >= H:
            z = z_try
            break

    n = 2 ** z
    tx_min_f = (lon_min + 180) / 360 * n
    tx_max_f = (lon_max + 180) / 360 * n
    ty_min_f = _merc_y(lat_max) * n   # lat_max → smaller y (north = top)
    ty_max_f = _merc_y(lat_min) * n

    tx0, tx1 = max(0, int(tx_min_f)), min(n - 1, int(tx_max_f) + 1)
    ty0, ty1 = max(0, int(ty_min_f)), min(n - 1, int(ty_max_f) + 1)

    stitch_w = (tx1 - tx0 + 1) * _TILE_SIZE
    stitch_h = (ty1 - ty0 + 1) * _TILE_SIZE
    stitched = Image.new("RGBA", (stitch_w, stitch_h), _STYLE_BACKGROUNDS[style_key])

    coords = [(tx, ty) for tx in range(tx0, tx1 + 1) for ty in range(ty0, ty1 + 1)]

    def _fetch(coord):
        tx, ty = coord
        try:
            return coord, _fetch_one_tile(z, tx, ty, style_key)
        except Exception:
            return coord, None

    with ThreadPoolExecutor(max_workers=8) as pool:
        for coord, tile in pool.map(_fetch, coords):
            if tile:
                tx, ty = coord
                stitched.paste(tile, ((tx - tx0) * _TILE_SIZE, (ty - ty0) * _TILE_SIZE))

    # Crop to exact bbox in tile-pixel space, then scale to output size
    crop_l = (tx_min_f - tx0) * _TILE_SIZE
    crop_t = (ty_min_f - ty0) * _TILE_SIZE
    crop_r = (tx_max_f - tx0) * _TILE_SIZE
    crop_b = (ty_max_f - ty0) * _TILE_SIZE
    cropped = stitched.crop((int(crop_l), int(crop_t), int(crop_r), int(crop_b)))
    return cropped.resize((W, H), Image.LANCZOS)


def _dot_colour(stadium, params, country_index):
    if params["color_by"] == "single":
        return params["single_color"]
    if params["color_by"] == "country":
        idx = country_index.get(stadium["country"], 0)
        return _COUNTRY_PALETTE[idx % len(_COUNTRY_PALETTE)]
    # surface
    return _SURFACE_COLOURS.get(stadium["surface"], _DEFAULT_DOT_COLOUR)


def _draw_dots_and_labels(img, stadiums, params, bbox, W, H, country_index):
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("arial.ttf", 13)
    except Exception:
        font = ImageFont.load_default()

    for s in stadiums:
        px, py = _lon_lat_to_px(s["lon"], s["lat"], bbox, W, H)
        colour = _dot_colour(s, params, country_index)
        r = 6
        draw.ellipse([px - r, py - r, px + r, py + r], fill=colour, outline=(255, 255, 255), width=1)

        if params["labels"]:
            label = s["name"]
            try:
                bbox_txt = draw.textbbox((0, 0), label, font=font)
                tw = bbox_txt[2] - bbox_txt[0]
            except AttributeError:
                tw = len(label) * 7

            gap = 4
            lx = px + r + gap if px + r + gap + tw < W else px - r - gap - tw
            ly = py - 7
            # Dark outline
            for dx, dy in [(-1, -1), (1, -1), (-1, 1), (1, 1)]:
                draw.text((lx + dx, ly + dy), label, font=font, fill=(0, 0, 0))
            draw.text((lx, ly), label, font=font, fill=(255, 255, 255))
    return img


def _build_legend_entries(params, stadiums):
    """Return list of (colour_tuple, label_str) for the legend."""
    if params["color_by"] == "single":
        return [(params["single_color"], "Stadium")]
    if params["color_by"] == "surface":
        surfaces_present = {s["surface"] for s in stadiums}
        entries = []
        for surf, colour in _SURFACE_COLOURS.items():
            if surf in surfaces_present:
                entries.append((colour, surf.capitalize()))
        if "" in surfaces_present or "UNKNOWN" in surfaces_present:
            entries.append((_DEFAULT_DOT_COLOUR, "Unknown"))
        return entries
    # country
    country_index = {}
    for s in stadiums:
        if s["country"] not in country_index:
            country_index[s["country"]] = len(country_index)
    return [
        (_COUNTRY_PALETTE[i % len(_COUNTRY_PALETTE)], name)
        for name, i in sorted(country_index.items(), key=lambda x: x[1])
    ]


def _draw_legend(img, params, stadiums):
    entries = _build_legend_entries(params, stadiums)
    if not entries:
        return img

    try:
        font = ImageFont.truetype("arial.ttf", 14)
    except Exception:
        font = ImageFont.load_default()

    padding = 12
    dot_r = 6
    line_h = 22
    box_w = 160
    box_h = padding * 2 + len(entries) * line_h

    W, H = img.size
    margin = 16
    x0, y0 = margin, H - margin - box_h

    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(overlay)
    d.rounded_rectangle([x0, y0, x0 + box_w, y0 + box_h], radius=8, fill=(20, 20, 20, 190))

    for i, (colour, label) in enumerate(entries):
        cy = y0 + padding + i * line_h + dot_r
        cx = x0 + padding + dot_r
        d.ellipse([cx - dot_r, cy - dot_r, cx + dot_r, cy + dot_r], fill=colour)
        d.text((cx + dot_r + 8, cy - 8), label, font=font, fill=(230, 230, 230))

    return Image.alpha_composite(img, overlay)


def _draw_north_arrow(img, W, H):
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(overlay)
    margin = 20
    cx, cy = W - margin - 18, margin + 30
    # Arrow shaft + head
    d.polygon([(cx, cy - 20), (cx - 8, cy + 4), (cx + 8, cy + 4)], fill=(255, 255, 255, 220))
    d.polygon([(cx, cy - 20), (cx - 8, cy + 4), (cx, cy - 4)], fill=(100, 100, 100, 220))
    try:
        font = ImageFont.truetype("arial.ttf", 14)
    except Exception:
        font = ImageFont.load_default()
    d.text((cx - 5, cy + 6), "N", font=font, fill=(255, 255, 255, 220))
    return Image.alpha_composite(img, overlay)


def _draw_title(img, title_text, W):
    try:
        font = ImageFont.truetype("arialbd.ttf", 22)
    except Exception:
        try:
            font = ImageFont.truetype("arial.ttf", 22)
        except Exception:
            font = ImageFont.load_default()

    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(overlay)
    margin = 16
    padding = 10

    try:
        bb = d.textbbox((0, 0), title_text, font=font)
        tw, th = bb[2] - bb[0], bb[3] - bb[1]
    except AttributeError:
        tw, th = len(title_text) * 13, 22

    rx0, ry0 = margin, margin
    rx1, ry1 = margin + tw + padding * 2, margin + th + padding * 2
    d.rounded_rectangle([rx0, ry0, rx1, ry1], radius=6, fill=(10, 10, 10, 200))
    d.text((rx0 + padding, ry0 + padding), title_text, font=font, fill=(255, 255, 255))
    return Image.alpha_composite(img, overlay)


def map_export(request):
    # Rate-limit: 1 request per 10 s per IP
    ip = request.META.get("HTTP_X_FORWARDED_FOR", request.META.get("REMOTE_ADDR", ""))
    cache_key = f"map_export_ratelimit_{ip}"
    if cache.get(cache_key):
        return JsonResponse({"error": "Too many requests. Wait 10 seconds."}, status=429)
    cache.set(cache_key, True, 10)

    params = _parse_export_params(request)
    stadiums = _get_export_stadiums(params)

    if not stadiums:
        return JsonResponse({"error": "No stadiums match the selected filters."}, status=400)

    W, H = params["W"], params["H"]
    bbox = _bbox_with_padding(stadiums)

    # Build country index for colour-by-country mode
    country_index = {}
    for s in stadiums:
        if s["country"] not in country_index:
            country_index[s["country"]] = len(country_index)

    img = _make_background(params["style_key"], W, H, bbox)

    img = _draw_dots_and_labels(img, stadiums, params, bbox, W, H, country_index)

    if params["legend"]:
        img = _draw_legend(img, params, stadiums)
    if params["north"]:
        img = _draw_north_arrow(img, W, H)
    if params["title"]:
        img = _draw_title(img, params["title"], W)

    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="PNG", optimize=True)
    buf.seek(0)

    filename = f"stadiums-map-{params['size_key']}.png"
    response = HttpResponse(buf.read(), content_type="image/png")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response
