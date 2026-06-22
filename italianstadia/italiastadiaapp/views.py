import csv
import hashlib
import io
import json
import logging
import math
import os as _os
import threading as _threading
import time as _time
import traceback
import uuid
from collections import defaultdict, OrderedDict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import timedelta
from pathlib import Path

import requests as _requests
import stripe
from PIL import Image, ImageDraw, ImageFont

from django.conf import settings
from django.core.cache import cache
from django.db.models import Avg, Count, F, Max, Q, Sum
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.text import slugify
from django.core.mail import EmailMessage
from django.views.decorators.cache import cache_page
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST
from .models import City, Country, ExportToken, LastRefresh, League, Stadium, Team, StadiumDevelopment


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


def _stadium_answer_faq(stadium):
    """A snippet-friendly answer sentence + FAQ Q&A pairs for a stadium page.
    Targets the dominant 'X capacity / where is X / what pitch' search intent."""
    city = stadium.city
    loc = (f"{city.name}, {city.country}" if city and city.country
           else (city.name if city else ""))
    teams = list(stadium.teams.all())
    team_names = ", ".join(t.name for t in teams[:3])

    bits = [f"{stadium.name} is a football stadium"]
    if loc:
        bits.append(f"in {loc}")
    if stadium.capacity:
        bits.append(f"with a capacity of {stadium.capacity:,}")
    answer = " ".join(bits) + "."
    if stadium.year_of_construction:
        answer += f" It opened in {stadium.year_of_construction}."
    if stadium.surface:
        answer += f" The pitch is {stadium.get_surface_display().lower()}."
    if team_names:
        answer += f" It is home to {team_names}."

    faq = []
    if stadium.capacity:
        faq.append((f"What is the capacity of {stadium.name}?",
                    f"{stadium.name} has a capacity of {stadium.capacity:,} spectators."))
    if loc:
        faq.append((f"Where is {stadium.name} located?",
                    f"{stadium.name} is located in {loc}."))
    if stadium.year_of_construction:
        faq.append((f"When did {stadium.name} open?",
                    f"{stadium.name} opened in {stadium.year_of_construction}."))
    if stadium.surface:
        faq.append((f"What kind of pitch does {stadium.name} have?",
                    f"{stadium.name} has a {stadium.get_surface_display().lower()} pitch."))
    if team_names:
        faq.append((f"Which teams play at {stadium.name}?",
                    f"{stadium.name} is the home ground of {team_names}."))
    return answer, [{"q": q, "a": a} for q, a in faq]


def _team_answer_faq(team):
    """Snippet-friendly answer + FAQ for a team page (full name, ground, country, founded)."""
    country = team.league.country.name if team.league and team.league.country else (
        team.city.country if team.city else "")
    where = team.city.name if team.city else ""
    if where and country:
        where = f"{where}, {country}"
    elif country:
        where = country
    ground = team.stadium.name if team.stadium else ""

    bits = [f"{team.name} is a football club"]
    if where:
        bits.append(f"based in {where}")
    answer = " ".join(bits) + "."
    if team.founded:
        answer += f" It was founded in {team.founded.year}."
    if ground:
        cap = f" ({team.stadium.capacity:,} capacity)" if team.stadium.capacity else ""
        answer += f" The club plays at {ground}{cap}."

    faq = []
    if where:
        faq.append((f"Where is {team.name} from?", f"{team.name} is based in {where}."))
    if ground:
        faq.append((f"What stadium does {team.name} play at?",
                    f"{team.name} plays at {ground}."
                    + (f" Its capacity is {team.stadium.capacity:,}." if team.stadium.capacity else "")))
    if team.founded:
        faq.append((f"When was {team.name} founded?",
                    f"{team.name} was founded in {team.founded.year}."))
    if team.num_of_titles:
        faq.append((f"How many league titles has {team.name} won?",
                    f"{team.name} has won {team.num_of_titles} domestic league "
                    f"title{'s' if team.num_of_titles != 1 else ''}."))
    return answer, [{"q": q, "a": a} for q, a in faq]


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

    answer, faq = _stadium_answer_faq(stadium)
    return render(request, "stadium_detail.html", {
        "stadium": stadium,
        "has_coords": stadium.latitude is not None and stadium.longitude is not None,
        "from_list": from_list is not None,
        "back_country": back_country,
        "from_team_list": bool(from_teams),
        "team_logos_json": json.dumps(team_logos),
        "team_flag_urls": team_flag_urls,
        "page_description": _stadium_description(stadium),
        "answer": answer,
        "faq": faq,
        "faq_json": json.dumps([{"@type": "Question", "name": f["q"],
                                 "acceptedAnswer": {"@type": "Answer", "text": f["a"]}}
                                for f in faq]),
    })


def stadium_detail_redirect(request, id):
    stadium = get_object_or_404(Stadium, pk=id)
    return redirect("italiastadiaapp:stadium_detail", slug=stadium.slug, permanent=True)


@cache_page(60 * 60)
def country_stats(request, country_name):
    # Canonical display name if it matches a Country row; else use the URL value as-is.
    country_obj = Country.objects.filter(name__iexact=country_name).first()
    name = country_obj.name if country_obj else country_name

    # Match stadiums by the city's country OR by the country of any tenant's league —
    # catches grounds whose free-text City.country differs from the canonical name.
    stadiums = (
        Stadium.objects
        .select_related("city")
        .prefetch_related("teams__league__country")
        .filter(Q(city__country__iexact=name) | Q(teams__league__country__name__iexact=name))
        .distinct()
    )
    agg = stadiums.filter(capacity__isnull=False).aggregate(
        total_seats=Sum("capacity"),
        avg_capacity=Avg("capacity"),
        max_capacity=Max("capacity"),
    )
    total_stadiums_all = stadiums.count()
    # Full list (largest first) for the hub — every ground is an internal link.
    all_stadiums = list(stadiums.order_by(
        F("capacity").desc(nulls_last=True), "name"))
    top10 = [s for s in all_stadiums if s.capacity][:10]
    biggest = top10[0] if top10 else None
    leagues = (
        League.objects.select_related("country")
        .filter(country__name__iexact=name).order_by("division_level")
    )

    map_features = []
    for s in all_stadiums:
        if s.latitude is None or s.longitude is None:
            continue
        map_features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [float(s.longitude), float(s.latitude)]},
            "properties": {"id": s.id, "slug": s.slug or str(s.id),
                           "name": s.name, "capacity": s.capacity},
        })
    geojson = json.dumps({"type": "FeatureCollection", "features": map_features})

    # SEO answer block + FAQ targeting "<country> football stadiums" intent.
    answer = f"There are {total_stadiums_all} football stadiums in {name} in our database"
    if biggest and biggest.capacity:
        answer += (f", the largest being {biggest.name} in {biggest.city.name} "
                   f"with a capacity of {biggest.capacity:,}")
    answer += "."
    if agg.get("total_seats"):
        answer += f" Combined, they seat about {int(agg['total_seats']):,} spectators."
    faq = []
    faq.append((f"How many football stadiums are there in {name}?",
                f"Our database lists {total_stadiums_all} football stadiums in {name}."))
    if biggest and biggest.capacity:
        faq.append((f"What is the biggest stadium in {name}?",
                    f"The biggest football stadium in {name} is {biggest.name} in "
                    f"{biggest.city.name}, with a capacity of {biggest.capacity:,}."))
    if leagues:
        faq.append((f"What are the main football leagues in {name}?",
                    f"The main leagues in {name} include "
                    f"{', '.join(l.name for l in leagues[:4])}."))
    faq = [{"q": q, "a": a} for q, a in faq]
    page_description = _trim(answer)

    return render(request, "country_stats.html", {
        "country_name": name,
        "total_stadiums": total_stadiums_all,
        "total_seats": agg.get("total_seats") or 0,
        "avg_capacity": int(agg.get("avg_capacity") or 0),
        "max_capacity": agg.get("max_capacity") or 0,
        "top10": top10,
        "all_stadiums": all_stadiums,
        "leagues": leagues,
        "geojson": geojson,
        "answer": answer,
        "faq": faq,
        "faq_json": json.dumps([{"@type": "Question", "name": f["q"],
                                 "acceptedAnswer": {"@type": "Answer", "text": f["a"]}}
                                for f in faq]),
        "page_description": page_description,
    })

def stadium_development_detail(request, slug):
    development = get_object_or_404(
        StadiumDevelopment.objects.prefetch_related("future_tenants"),
        slug=slug
    )

    return render(request, "stadium_development_detail.html", {
        "development": development
    })


def stadium_development_detail_redirect(request, pk):
    """301 old /stadium-development/<int:pk>/ URLs to the new slug URL."""
    development = get_object_or_404(StadiumDevelopment, pk=pk)
    return redirect(
        "italiastadiaapp:stadium_development_detail",
        slug=development.slug,
        permanent=True,
    )

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
                "slug": s.slug or str(s.id),
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
                "tournaments": s.tournaments or [],
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
                        # National sides show their country flag (reliable PD flagcdn,
                        # GB-subdivision aware) instead of a non-free crest that may not load.
                        "image_url": (
                            f"https://flagcdn.com/w160/{_country_flag_code(t.league.country.code)}.png"
                            if t.is_national and t.league and t.league.country and t.league.country.code
                            else (t.image_url or "")
                        ),
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
    param_view      = request.GET.get("view",       "").strip().lower()

    qs = Stadium.objects.select_related("city").prefetch_related(
        "teams__league__country"
    )
    if param_ownership:
        qs = qs.filter(ownership=param_ownership)
    if param_league:
        qs = qs.filter(teams__league__name=param_league).distinct()
    if param_country:
        qs = qs.filter(teams__league__country__name=param_country).distinct()
    # Insight views (see /insights/) — preset filters reused by the shared insights map JS.
    if param_view == "national":
        # Any ground that hosts a national side (a country's national stadium, even if a
        # club also plays there — e.g. Johan Cruijff ArenA, Rajko Mitić).
        qs = qs.filter(teams__is_national=True).distinct()
    elif param_view == "surface":
        qs = qs.exclude(surface__isnull=True).exclude(surface="")
    elif param_view == "capacity":
        qs = qs.exclude(capacity__isnull=True).exclude(capacity=0)

    return JsonResponse({
        "type": "FeatureCollection",
        "features": _build_stadium_features(qs),
    })

def index(request):
    # Cache-bust the pre-built static map file: its mtime changes on every
    # `generate_stadiums_json` / deploy, so the browser refetches instead of
    # serving a stale copy (which made newly-scraped leagues look "missing").
    map_path = Path(__file__).parent / "static" / "data" / "stadiums_map.json"
    try:
        map_version = int(map_path.stat().st_mtime)
    except OSError:
        map_version = 0
    return render(request, "index.html", {"map_version": map_version})

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
    "NI": "gb-nir",   # Northern Ireland
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
    answer, faq = _team_answer_faq(team)
    return render(request, "team_detail.html", {
        "team": team,
        "from_list": from_list is not None,
        "back_country": back_country,
        "page_description": _team_description(team),
        "answer": answer,
        "faq": faq,
        "faq_json": json.dumps([{"@type": "Question", "name": f["q"],
                                 "acceptedAnswer": {"@type": "Answer", "text": f["a"]}}
                                for f in faq]),
    })


def team_detail_redirect(request, pk):
    team = get_object_or_404(Team, pk=pk)
    return redirect("italiastadiaapp:team_detail", slug=team.slug, permanent=True)


def team_list(request):
    selected_country = request.GET.get("country", "")

    teams_qs = (
        Team.objects
        .select_related("city", "stadium", "league__country")
        .exclude(is_national=True)   # hide national teams from the club list
    )
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
    "England":          "🇬🇧",
    "Wales":            "🇬🇧",
    "Scotland":         "🇬🇧",
    "Northern Ireland": "🇬🇧",
    "Ireland":          "🇮🇪",
    "Italy":            "🇮🇹",
    "Turkey":           "🇹🇷",
    # Euro 2036 bid nations
    "Poland":           "🇵🇱",
    "Denmark":          "🇩🇰",
    "Sweden":           "🇸🇪",
    "Norway":           "🇳🇴",
    "Finland":          "🇫🇮",
    "Croatia":          "🇭🇷",
    "Serbia":           "🇷🇸",
    "Bosnia and Herzegovina": "🇧🇦",
    "North Macedonia":  "🇲🇰",
    # Champions League final hosts
    "Hungary":          "🇭🇺",
    "Spain":            "🇪🇸",
    "Germany":          "🇩🇪",
}

# Euro 2036-style competing-bid colours (hex for web/legend, RGB for the PNG export)
_BID_COLOR_HEX = {
    "Poland": "#dc2626",   # red
    "Nordic": "#2563eb",   # blue
    "Balkan": "#d97706",   # amber
}
_BID_COLOR = {
    "Poland": (220, 38, 38),
    "Nordic": (37, 99, 235),
    "Balkan": (217, 119, 6),
}

# Host nations that must always appear on a tournament page even if they have no
# venue in the data yet (e.g. Northern Ireland co-hosts Euro 2028 but its only
# candidate ground, Casement Park, is unresolved).
TOURNAMENT_EXTRA_HOSTS = {
    "uefa-euro-2028": ["Northern Ireland"],
}


def tournament_list(request):
    return redirect("italiastadiaapp:home")


# Tournament venue status: 3-way. Blank/unknown is treated as CANDIDATE.
_TOURNAMENT_STATUS_ORDER = {"CONFIRMED": 0, "CANDIDATE": 1, "DISCARDED": 2}


def _norm_tournament_status(s):
    s = (s or "").upper()
    return s if s in _TOURNAMENT_STATUS_ORDER else "CANDIDATE"


def _list_tournaments():
    """All tournaments in the data as [{slug, name, year}], deduped, oldest first."""
    seen = {}
    for model in (Stadium, StadiumDevelopment):
        for obj in model.objects.exclude(tournaments=[]).only("tournaments"):
            for e in (obj.tournaments or []):
                nm = e.get("tournament")
                if not nm:
                    continue
                s = slugify(nm)
                if s not in seen:
                    seen[s] = {"slug": s, "name": nm, "year": e.get("year")}
    return sorted(seen.values(), key=lambda t: (t.get("year") or 0))


def _tournament_venues(slug):
    """Return (tournament_name, tournament_year, venues) for a tournament slug.

    Sources venues from BOTH operational Stadiums and under-development
    StadiumDevelopments. Each venue dict carries a 3-way `status`
    (CONFIRMED / CANDIDATE / DISCARDED). Shared by the tournament detail page and
    the export tool so the two can never drift.
    """
    tournament_name = None
    tournament_year = None
    venues = []

    for stadium in Stadium.objects.select_related("city").prefetch_related("teams").exclude(tournaments=[]):
        for entry in stadium.tournaments:
            name = entry.get("tournament", "")
            if slugify(name) == slug:
                tournament_name = name
                tournament_year = entry.get("year")
                primary_team = next(iter(stadium.teams.all()), None)
                venues.append({
                    "name": stadium.name,
                    "city": stadium.city,
                    "capacity": stadium.capacity,
                    "image_url": stadium.image_url,
                    "badge_url": (primary_team.image_url or "") if primary_team else "",
                    "latitude": stadium.latitude,
                    "longitude": stadium.longitude,
                    "detail_url": reverse("italiastadiaapp:stadium_detail", kwargs={"slug": stadium.slug}),
                    "status": _norm_tournament_status(entry.get("status")),
                    "matches": entry.get("matches"),
                    "year": entry.get("year"),
                    "bid": entry.get("bid", ""),
                    "is_development": False,
                })
                break

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
                    "detail_url": reverse("italiastadiaapp:stadium_development_detail", kwargs={"slug": dev.slug or str(dev.id)}),
                    "badge_url": "",   # future venue — no club crest, drawn as a status dot
                    "status": _norm_tournament_status(entry.get("status")),
                    "matches": entry.get("matches"),
                    "bid": entry.get("bid", ""),
                    "is_development": True,
                })
                break

    return tournament_name, tournament_year, venues


# Hand-written, per-tournament editorial. Keyed by slug so a single shared template
# can still carry tournament-specific analysis (the auto-generated `tournament_about`
# / `bid_analysis` text is data-driven and cannot say things like "Italy and Turkey
# merged their bids"). Rendered as its own card; `paragraphs` is a list of prose
# blocks and `sources` a list of {label, url} citations.
_TOURNAMENT_EDITORIAL = {
    "uefa-euro-2032": {
        "heading": "Bid analysis: how the Italy–Turkey joint bid came about",
        "paragraphs": [
            "UEFA Euro 2032 will be co-hosted by Italy and Turkey, but the joint bid was "
            "not the original plan. During the bidding process the two federations merged "
            "what had been separate, competing candidacies into a single dual-host bid.",
            "From Italy's point of view the move made strategic sense. A standalone Italian "
            "bid was considered highly unlikely to succeed, largely because of long-standing "
            "doubts over its ageing stadium infrastructure, so joining forces with Turkey was "
            "a pragmatic way to stay in the race. The decision was also consequential: it led "
            "Italy to drop its involvement in the Euro 2028 bid in order to concentrate on 2032.",
            "From Turkey's point of view the logic is less obvious. Turkey already has a deep "
            "portfolio of modern stadiums that comfortably satisfy UEFA's hosting requirements "
            "and could plausibly have staged the tournament alone. One widely-discussed theory "
            "is that Turkey is betting on Italy's lack of preparedness: should Italy fail to "
            "deliver the required venues in time, it could be excluded from the joint bid, "
            "leaving Turkey to be awarded the tournament as sole host. Those concerns are not "
            "merely hypothetical — UEFA president Aleksander Čeferin has publicly warned that "
            "Italy risks being removed as co-host if its infrastructure plans do not progress.",
        ],
        "sources": [
            {"label": "Calcio e Finanza — Italy–Turkey joint candidacy for Euro 2032",
             "url": "https://www.calcioefinanza.it/2023/07/28/gravina-candidatura-italia-turchia-per-euro-2032-svolta-storica/"},
            {"label": "Football Italia — Gravina on Italy, Euro 2032 and Turkey",
             "url": "https://football-italia.net/gravina-italy-lost-euro-2032-turkey-mancini/"},
            {"label": "Reuters — Čeferin threatens to remove Italy as Euro 2032 co-host over infrastructure",
             "url": "https://www.reuters.com/sports/soccer/uefa-chief-ceferin-threatens-remove-italy-euro-2032-co-host-over-infrastructure-2026-04-02/"},
        ],
        "faq": [
            ("Where will UEFA Euro 2032 be held?",
             "UEFA Euro 2032 will be co-hosted by Italy and Turkey, the first time the two "
             "countries have staged the tournament together."),
            ("Why are Italy and Turkey hosting Euro 2032 together?",
             "Italy and Turkey merged their separate bids into a single joint candidacy during "
             "the bidding process; UEFA awarded them the 2032 finals unopposed in October 2023."),
            ("How many stadiums will Euro 2032 use?",
             "UEFA requires each host to provide around 10 stadiums meeting its capacity tiers, "
             "so the Italy–Turkey edition is expected to use roughly 20 venues split between the "
             "two countries, narrowed from a longer candidate list."),
        ],
    },
    "champions-league-final": {
        "heading": "Champions League final venues, 2026–2030",
        "paragraphs": [
            "Unlike a Euro, the UEFA Champions League final is played at a single, different "
            "stadium every year, chosen by UEFA's Executive Committee a few seasons in advance. "
            "This page maps the venues for the upcoming finals — those already confirmed and "
            "those still being decided between rival candidate cities.",
            "The 2026 final is confirmed for the Puskás Aréna in Budapest, and the 2027 final "
            "for the Estadio Metropolitano (Riyadh Air Metropolitano) in Madrid. The 2028 final "
            "is expected to head to Munich's Allianz Arena, while 2029 is a contest between "
            "London's Wembley Stadium and Barcelona's Camp Nou. The 2030 host has not yet been "
            "announced — bids are still open.",
            "Final proposals for the 2028 and 2029 editions were submitted in mid-2026, with "
            "UEFA's host appointments expected to follow. We will update the map as each "
            "decision is confirmed.",
        ],
        "sources": [
            {"label": "Footbeen — Champions League final venues 2026–2030",
             "url": "https://footbeen.com/blog/champions-league-final-venues-2026-2030"},
        ],
        "faq": [
            ("Where is the 2026 Champions League final?",
             "The 2026 UEFA Champions League final will be played at the Puskás Aréna in "
             "Budapest, Hungary."),
            ("Where is the 2027 Champions League final?",
             "The 2027 final is confirmed for the Estadio Metropolitano in Madrid, Spain."),
            ("Which cities are bidding for the 2028 and 2029 Champions League finals?",
             "Munich's Allianz Arena is the frontrunner for 2028, while Wembley Stadium "
             "(London) and Camp Nou (Barcelona) are the candidates for 2029."),
            ("Where will the 2030 Champions League final be held?",
             "UEFA has not yet announced the host of the 2030 Champions League final."),
        ],
    },
}


@cache_page(60 * 60)
def tournament_detail(request, slug):
    """Show all venues for a single tournament (Stadium + StadiumDevelopment)."""
    tournament_name, tournament_year, venues = _tournament_venues(slug)

    if not tournament_name:
        raise Http404

    # CONFIRMED, then CANDIDATE, then DISCARDED; each group by capacity desc
    venues.sort(key=lambda v: (
        _TOURNAMENT_STATUS_ORDER.get(v["status"], 1),
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

    # Always show co-host nations even with no venues yet (e.g. N. Ireland @ Euro 2028)
    for host in TOURNAMENT_EXTRA_HOSTS.get(slug, []):
        if host not in _country_groups:
            _country_groups[host] = {"flag": COUNTRY_FLAGS.get(host, ""), "venues": []}

    venues_by_country = OrderedDict(sorted(_country_groups.items(), key=lambda item: item[0]))
    multi_country = len(venues_by_country) > 1

    host_country_flags = OrderedDict(
        (c, grp["flag"]) for c, grp in venues_by_country.items()
    )

    # Bid grouping — for tournaments with competing bids (e.g. Euro 2036). Auto-
    # activates when any venue carries a `bid` label; otherwise the page keeps the
    # country grouping above. Shape: bid → countries → venues.
    has_bids = any(v.get("bid") for v in venues)
    bids = []
    if has_bids:
        _bid_groups = OrderedDict()
        for v in venues:
            bid_name = v.get("bid") or "Other"
            country = _venue_country(v)
            grp = _bid_groups.setdefault(bid_name, OrderedDict())
            grp.setdefault(country, {"flag": COUNTRY_FLAGS.get(country, ""), "venues": []})
            grp[country]["venues"].append(v)
        for bid_name, countries in _bid_groups.items():
            country_list = [{"country": c, "flag": g["flag"], "venues": g["venues"]}
                            for c, g in sorted(countries.items())]
            vcount = sum(len(c["venues"]) for c in country_list)
            cap = sum(v["capacity"] or 0 for c in country_list for v in c["venues"])
            is_joint = len(country_list) > 1
            bids.append({
                "name": bid_name,
                "countries": country_list,
                "country_names": [c["country"] for c in country_list],
                "venue_count": vcount,
                "total_capacity": cap,
                "is_joint": is_joint,
                "kind": "joint bid" if is_joint else "solo bid",
                "color": _BID_COLOR_HEX.get(bid_name, "#6c757d"),
            })
        # Fixed running order (Poland leads — strongest chances), then by size.
        _BID_ORDER = {"Poland": 0, "Nordic": 1, "Balkan": 2}
        bids.sort(key=lambda b: (_BID_ORDER.get(b["name"], 9), -b["venue_count"]))

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
                "bid": v.get("bid", ""),
                "bid_color": _BID_COLOR_HEX.get(v.get("bid", ""), ""),
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
    # Original prose description — used both as a visible on-page intro (good for
    # ranking + AI answers) and, trimmed, as the <meta name="description">.
    sample_names = [v["name"] for v in confirmed_venues[:3]] or [v["name"] for v in venues[:3]]
    n_total = len(venues)
    intro_parts = []
    bid_blurbs = []   # rich per-bid editorial paragraphs (also good for SEO/AEO)
    bid_analysis = ""   # standing editorial on the joint-bid trend (SEO long-form)
    tournament_about = ""   # data-aware long-form for single-host tournaments
    # UEFA stadium-portfolio requirement, woven into the page description text.
    req_text = (
        " To stage the tournament a host must field around 10 stadiums meeting UEFA's "
        "capacity tiers — at least 3 of 50,000–60,000+ seats (for the opening match, "
        "semi-finals and final), 4 of at least 40,000 and 3 of at least 30,000."
    )
    if has_bids:
        # Competing-bids tournament (host not yet chosen).
        intro_parts.append(
            f"{tournament_name} does not yet have a host nation — several rival bids are "
            f"competing to stage the tournament. This page maps every proposed host "
            f"stadium grouped by bid, so you can compare who is bidding and with which "
            f"grounds."
        )
        intro_parts.append(
            f"{len(bids)} bids are in the running across {n_total} proposed venues: "
            + ", ".join(
                f"{b['name']} ({b['kind']}, {b['venue_count']} venue"
                f"{'s' if b['venue_count'] != 1 else ''})" for b in bids
            ) + "."
        )
        for b in bids:
            who = (" and ".join([", ".join(b["country_names"][:-1]), b["country_names"][-1]])
                   if b["is_joint"] else b["country_names"][0])
            vnames = ", ".join(v["name"] for c in b["countries"] for v in c["venues"][:3])
            blurb = (
                f"The {b['name']} {b['kind']} is led by {who}, proposing "
                f"{b['venue_count']} stadium{'s' if b['venue_count'] != 1 else ''}"
            )
            if b["total_capacity"]:
                blurb += f" with a combined capacity of about {b['total_capacity']:,} seats"
            blurb += f". Proposed venues include {vnames}."
            b["blurb"] = blurb
            bid_blurbs.append({"name": b["name"], "color": b["color"], "text": blurb})

        # Standing editorial on the joint-bid trend — long-form, data-aware (the
        # tournament pages are the site's top traffic, so this is worth the words).
        joint = [b for b in bids if b["is_joint"]]
        solo = [b for b in bids if not b["is_joint"]]
        bid_analysis = (
            "The joint, multi-country bid is fast becoming the norm for the European "
            "Championship. Rather than carrying the cost, security and infrastructure "
            "demands alone, national federations are teaming up to spread the financial "
            "risk, pool a wider set of world-class stadiums and strengthen both the appeal "
            "and the likelihood of success of their bid. The last single-nation host was "
            "Germany at UEFA Euro 2024; the next two editions are already co-hosted — Euro "
            "2028 by the United Kingdom and Ireland, and Euro 2032 by Italy and Turkey."
        )
        if bids:
            count_phrase = (
                f"{len(joint)} joint multi-country bid{'s' if len(joint) != 1 else ''}"
                if joint else "no joint bids yet"
            )
            if solo:
                count_phrase += (
                    f" and {len(solo)} solo bid{'s' if len(solo) != 1 else ''}"
                )
            bid_analysis += (
                f" Of the {len(bids)} Euro 2036 bids tracked on this page, {count_phrase}. "
                "Will UEFA return to a single-country host model, or is shared hosting "
                "simply the new reality of staging a modern Euro? For now, teaming up looks "
                "like the winning strategy."
            )
        bid_analysis += req_text
    else:
        if host_str:
            intro_parts.append(f"{tournament_name} will be hosted in {host_str}.")
        else:
            intro_parts.append(f"{tournament_name} host stadiums.")
        if n_total:
            intro_parts.append(
                f"Explore all {n_total} candidate and confirmed host "
                f"stadium{'s' if n_total != 1 else ''} on an interactive map, with "
                f"capacities, host cities and match details."
            )
        if confirmed_venues:
            sentence = (
                f"The {len(confirmed_venues)} confirmed venue"
                f"{'s' if len(confirmed_venues) != 1 else ''} include {', '.join(sample_names)}"
            )
            sentence += (
                f" and offer a combined capacity of {total_capacity:,} seats."
                if total_capacity else "."
            )
            intro_parts.append(sentence)

        # Data-aware long-form "About" for single-host tournaments (SEO; top traffic).
        about = [f"{tournament_name} is one of the showpiece events of European football."]
        if host_str:
            yr = f" {tournament_year}" if tournament_year else ""
            about.append(f"The{yr} edition is set to be hosted by {host_str}.")
        if n_total:
            about.append(
                f"This page tracks all {n_total} stadium{'s' if n_total != 1 else ''} linked "
                f"to the tournament — {len(confirmed_venues)} confirmed and "
                f"{len(venues) - len(confirmed_venues)} candidate — mapped with capacities, "
                f"host cities and, where known, how many matches each is set to stage."
            )
        if total_capacity:
            about.append(
                f"Together the confirmed venues seat around {total_capacity:,} spectators.")
        tournament_about = " ".join(about) + req_text
    tournament_intro = " ".join(intro_parts)
    tournament_description = _trim(tournament_intro)

    # Data-aware FAQ (captures "where is <T> / which stadiums / how many / biggest") —
    # the exact tournament search intent. Editorial may add custom Q&A via the "faq" key.
    cap_venues = [v for v in venues if v.get("capacity")]
    biggest_venue = max(cap_venues, key=lambda v: v["capacity"]) if cap_venues else None
    sample_confirmed = [v["name"] for v in confirmed_venues[:5]] or [v["name"] for v in venues[:5]]
    faq = []
    if host_str and not has_bids:
        faq.append((f"Where will {tournament_name} be held?",
                    f"{tournament_name} will be held in {host_str}."))
    elif has_bids:
        faq.append((f"Who is bidding to host {tournament_name}?",
                    f"{', '.join(b['name'] for b in bids)} "
                    f"{'are' if len(bids) != 1 else 'is'} bidding to host {tournament_name}."))
    if tournament_year:
        faq.append((f"When is {tournament_name}?",
                    f"{tournament_name} is scheduled for {tournament_year}."))
    if n_total:
        faq.append((f"How many stadiums will host {tournament_name}?",
                    f"{n_total} stadiums are linked to {tournament_name} "
                    f"({len(confirmed_venues)} confirmed and "
                    f"{n_total - len(confirmed_venues)} candidate)."))
    if sample_confirmed:
        faq.append((f"Which stadiums will host {tournament_name}?",
                    f"Host venues include {', '.join(sample_confirmed)}."))
    if biggest_venue:
        faq.append((f"What is the biggest stadium at {tournament_name}?",
                    f"{biggest_venue['name']} is the largest, with a capacity of "
                    f"{biggest_venue['capacity']:,}."))
    _ed = _TOURNAMENT_EDITORIAL.get(slug) or {}
    for q, a in _ed.get("faq", []):
        faq.append((q, a))
    faq = [{"q": q, "a": a} for q, a in faq]

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
        "tournament_intro": tournament_intro,
        "has_bids": has_bids,
        "bids": bids,
        "bid_blurbs": bid_blurbs,
        "bid_analysis": bid_analysis,
        "tournament_about": tournament_about,
        "tournament_editorial": _TOURNAMENT_EDITORIAL.get(slug),
        "faq": faq,
        "faq_json": json.dumps([{"@type": "Question", "name": f["q"],
                                 "acceptedAnswer": {"@type": "Answer", "text": f["a"]}}
                                for f in faq]),
        "other_tournaments": [t for t in _list_tournaments() if t["slug"] != slug],
    })


# ── Insights (data-story pages: SEO / CTR) ─────────────────────────────────────

_INSIGHTS = [
    {
        "slug": "national-stadiums",
        "title": "National stadiums of Europe",
        "blurb": "Each country's main national-team venue — and which are club-free.",
        "url_name": "insight_national",
        "image": "exports/insight_national.png",
    },
    {
        "slug": "stadium-surfaces",
        "title": "Artificial vs natural grass in European stadiums",
        "blurb": "How many grounds use real grass, hybrid pitches or full artificial turf.",
        "url_name": "insight_surface",
    },
    {
        "slug": "stadium-density",
        "title": "Stadium density per population",
        "blurb": "Which countries pack in the most football stadiums per million people.",
        "url_name": "insight_density",
    },
    {
        "slug": "biggest-stadiums",
        "title": "Biggest & smallest stadiums in Europe",
        "blurb": "The largest football stadiums in Europe by capacity — and the smallest.",
        "url_name": "insight_biggest",
    },
]


def _insight_others(current_slug):
    """The other insight cards, for the 'Related insights' footer block."""
    return [i for i in _INSIGHTS if i["slug"] != current_slug]


@cache_page(60 * 60)
def insights_index(request):
    return render(request, "insights_index.html", {
        "insights": _INSIGHTS,
        "page_description": (
            "Data insights on European football stadiums — national-team grounds, "
            "pitch surfaces (grass vs artificial) and stadium density per population."
        ),
    })


@cache_page(60 * 60)
def insight_national(request):
    qs = (Stadium.objects.select_related("city")
          .prefetch_related("teams__league__country")
          .annotate(
              _nat=Count("teams", filter=Q(teams__is_national=True), distinct=True),
              _club=Count("teams", filter=Q(teams__is_national=False), distinct=True))
          .filter(_nat__gte=1)
          .exclude(latitude__isnull=True))
    rows = []
    dedicated = 0
    for s in qs:
        nat = next((t for t in s.teams.all() if t.is_national), None)
        country = nat.league.country.name if (nat and nat.league and nat.league.country) else (
            s.city.country if s.city else "")
        is_dedicated = s._club == 0
        if is_dedicated:
            dedicated += 1
        rows.append({
            "stadium": s, "nation": nat.name if nat else "",
            "country": country, "capacity": s.capacity or 0,
            "dedicated": is_dedicated,
        })
    rows.sort(key=lambda r: r["capacity"], reverse=True)
    total_cap = sum(r["capacity"] for r in rows)
    intro = (
        f"Across Europe, {len(rows)} stadiums in our dataset host a national team — each "
        f"country's main international venue. {dedicated} of them are used exclusively by the "
        "national side; the rest are shared with a leading club. Together they seat about "
        f"{total_cap:,} spectators."
    )
    about = (
        "Most countries play their internationals at a stadium that a top club also calls "
        "home — for example the Netherlands at the Johan Cruijff ArenA (Ajax) or Serbia at "
        "the Rajko Mitić Stadium (Red Star). A truly dedicated national ground, used by no "
        "club, is rarer and usually a flagship — Wembley, the Stade de France, the Puskás "
        "Aréna. The table flags which grounds are dedicated; the map shows them all."
    )
    debate = (
        "The list could grow. Several countries are actively debating a dedicated national "
        "stadium: in Croatia there is a long-running discussion about finally building a "
        "national ground in Zagreb rather than relying on club stadiums. In Italy, Rome's "
        "Stadio Olimpico could effectively become a national-team venue once Lazio and Roma "
        "move into their own purpose-built club stadiums, leaving the Olimpico without a "
        "permanent club tenant. As those projects progress, expect more purely national "
        "grounds to appear on this map."
    )
    return render(request, "insight_national.html", {
        "rows": rows, "count": len(rows), "total_capacity": total_cap,
        "intro": intro, "about": about, "debate": debate,
        "geojson_url": reverse("italiastadiaapp:stadiums_geojson") + "?view=national",
        "others": _insight_others("national-stadiums"),
        "page_description": _trim(intro),
        "hero_image": "exports/insight_national.png",
    })


@cache_page(60 * 60)
def insight_surface(request):
    qs = Stadium.objects.exclude(surface__isnull=True).exclude(surface="")
    counts = {"GRASS": 0, "HYBRID": 0, "ARTIFICIAL": 0}
    by_country = defaultdict(lambda: {"GRASS": 0, "HYBRID": 0, "ARTIFICIAL": 0})
    for s in qs.select_related("city"):
        if s.surface in counts:
            counts[s.surface] += 1
            country = s.city.country if s.city else "Unknown"
            by_country[country][s.surface] += 1
    known = sum(counts.values())

    def pct(n):
        return round(100 * n / known, 1) if known else 0.0
    surface_stats = [
        {"key": "GRASS", "label": "Natural grass", "count": counts["GRASS"], "pct": pct(counts["GRASS"])},
        {"key": "HYBRID", "label": "Hybrid", "count": counts["HYBRID"], "pct": pct(counts["HYBRID"])},
        {"key": "ARTIFICIAL", "label": "Artificial", "count": counts["ARTIFICIAL"], "pct": pct(counts["ARTIFICIAL"])},
    ]
    # Countries with the highest artificial share (min 4 known grounds, for signal).
    artificial_rows = []
    for country, c in by_country.items():
        tot = c["GRASS"] + c["HYBRID"] + c["ARTIFICIAL"]
        if tot >= 4:
            artificial_rows.append({
                "country": country, "total": tot,
                "artificial": c["ARTIFICIAL"], "hybrid": c["HYBRID"], "grass": c["GRASS"],
                "artificial_pct": round(100 * c["ARTIFICIAL"] / tot, 1),
            })
    artificial_rows.sort(key=lambda r: (r["artificial_pct"], r["total"]), reverse=True)
    intro = (
        f"Of the {known:,} European stadiums in our dataset with a recorded pitch type, "
        f"{pct(counts['GRASS'])}% use natural grass, {pct(counts['HYBRID'])}% use a hybrid "
        f"reinforced pitch and {pct(counts['ARTIFICIAL'])}% are fully artificial. Artificial "
        "and hybrid surfaces are most common in colder northern climates and in lower "
        "divisions, where year-round playability matters more than top-flight regulations."
    )
    about = (
        "Pitch type is recorded from each stadium's Wikipedia infobox where available. "
        "Stadiums without a recorded surface are excluded from these percentages so the "
        "figures reflect only confirmed data. Use the map to see the surface of each "
        "individual ground."
    )
    debate = (
        "This map was prompted by a very Italian debate. After Andrea Cambiaso said he hadn't "
        "played on artificial turf since he was 17, and Cristian Chivu's Inter were knocked "
        "out of Europe by Bodø/Glimt — whose synthetic pitch and remarkable home record drew "
        "intense scrutiny — fans and pundits in Italy openly questioned whether UEFA should "
        "ban artificial surfaces in its competitions. So how unusual is Bodø/Glimt's pitch "
        "really? The data is clear: artificial turf is overwhelmingly a Scandinavian "
        "phenomenon — Norway, Finland and Sweden dominate the table below, driven by climate "
        "and year-round playability. An Italian club drawn against a Nordic side in Europe "
        "will almost certainly face it. Is the pitch a valid excuse, or just poor "
        "preparation? Explore every artificial-turf ground on the map and judge for yourself."
    )
    return render(request, "insight_surface.html", {
        "surface_stats": surface_stats, "known": known,
        "artificial_rows": artificial_rows[:15],
        "intro": intro, "about": about, "debate": debate,
        "geojson_url": reverse("italiastadiaapp:stadiums_geojson") + "?view=surface",
        "others": _insight_others("stadium-surfaces"),
        "page_description": _trim(intro),
    })


@cache_page(60 * 60)
def insight_density(request):
    # TOP-FLIGHT stadiums per million people, by country. Restricting to the top division
    # makes this comparable across countries regardless of how many lower leagues we've
    # scraped — it answers "how many top-tier grounds does a nation support per capita".
    from .models import Country
    counts = (Stadium.objects
              .filter(teams__league__division_level=1)
              .values("teams__league__country__name")
              .annotate(n=Count("id", distinct=True)).order_by())
    count_by_country = {r["teams__league__country__name"]: r["n"]
                        for r in counts if r["teams__league__country__name"]}
    rows = []
    for c in Country.objects.exclude(population__isnull=True):
        n = count_by_country.get(c.name, 0)
        if not n:
            continue
        per_m = round(n / (c.population / 1_000_000), 2)
        rows.append({
            "country": c.name, "code": c.code, "stadiums": n,
            "population": c.population, "per_million": per_m,
        })
    rows.sort(key=lambda r: r["per_million"], reverse=True)
    # name -> per_million for the choropleth JS, keyed to match the hi-res geojson polygon
    # names. The geojson has ONE "United Kingdom" polygon (not the four home nations) and
    # uses "Czech Republic", so reconcile those here. The ranking table stays granular.
    _GEOJSON_ALIAS = {"Czechia": "Czech Republic"}
    _UK = {"England", "Scotland", "Wales", "Northern Ireland"}
    density_by_name = {}
    uk_stadiums = uk_pop = 0
    for r in rows:
        if r["country"] in _UK:
            uk_stadiums += r["stadiums"]
            uk_pop += r["population"]
            continue
        density_by_name[_GEOJSON_ALIAS.get(r["country"], r["country"])] = r["per_million"]
    if uk_pop:
        density_by_name["United Kingdom"] = round(uk_stadiums / (uk_pop / 1_000_000), 2)
    top = rows[0] if rows else None
    intro = (
        "This map ranks European countries by TOP-FLIGHT football-stadium density — the number "
        "of first-division grounds per million inhabitants. "
        + (f"{top['country']} leads with {top['per_million']} top-tier stadiums per million "
           f"people. " if top else "")
        + "Smaller nations rank high because even a normal-sized top division is large "
        "relative to their population."
    )
    about = (
        "Density here is the number of first-division (top-flight) stadiums divided by national "
        "population, per million. Restricting to the top division keeps countries comparable "
        "regardless of how many lower leagues are in our dataset."
    )
    debate = (
        "League size is part of this story. A bigger top flight means more top-tier stadiums "
        "per capita — and Italy's Serie A is at the centre of a long-running debate about "
        "shrinking from 20 clubs to 18, or even 16, to ease fixture congestion, raise quality "
        "and give the national team more rest. England, Spain and Germany have all weighed "
        "similar moves. If Serie A cut to 18, Italy's top-flight density on this map would drop "
        "accordingly — a reminder that these numbers reflect competition design as much as "
        "football culture."
    )
    return render(request, "insight_density.html", {
        "rows": rows, "intro": intro, "about": about, "debate": debate,
        "density_json": json.dumps(density_by_name),
        "others": _insight_others("stadium-density"),
        "page_description": _trim(intro),
    })


def _cap_row(s):
    teams = list(s.teams.all())
    country = next((t.league.country.name for t in teams
                    if t.league and t.league.country), s.city.country if s.city else "")
    return {
        "name": s.name, "slug": s.slug, "capacity": s.capacity,
        "city": s.city.name if s.city else "", "country": country,
        "team": ", ".join(t.name for t in teams[:2]),
    }


@cache_page(60 * 60)
def insight_biggest(request):
    base = (Stadium.objects.exclude(capacity__isnull=True).exclude(capacity=0)
            .select_related("city").prefetch_related("teams__league__country"))
    biggest = [_cap_row(s) for s in base.order_by("-capacity")[:50]]
    smallest = [_cap_row(s) for s in base.order_by("capacity")[:15]]
    # Largest ground per country
    per_country = {}
    for s in base.order_by("-capacity"):
        r = _cap_row(s)
        if r["country"] and r["country"] not in per_country:
            per_country[r["country"]] = r
    country_top = sorted(per_country.values(), key=lambda r: r["capacity"], reverse=True)
    top = biggest[0] if biggest else None
    intro = (
        (f"The biggest football stadium in our European dataset is {top['name']} in "
         f"{top['city']}, {top['country']}, holding {top['capacity']:,} spectators. "
         if top else "")
        + "This page ranks the largest football stadiums in Europe by capacity, the biggest "
        "ground in each country, and the smallest grounds in the dataset — on an interactive "
        "map and in sortable tables."
    )
    about = (
        "Capacities are the all-seated figures recorded for each stadium. The map plots every "
        "ground with a known capacity, scaled by size; the tables list the top 50 overall, the "
        "largest per country, and the 15 smallest."
    )
    return render(request, "insight_biggest.html", {
        "biggest": biggest, "smallest": smallest, "country_top": country_top,
        "intro": intro, "about": about,
        "geojson_url": reverse("italiastadiaapp:stadiums_geojson") + "?view=capacity",
        "others": _insight_others("biggest-stadiums"),
        "page_description": _trim(intro),
    })


# ── Map Export ────────────────────────────────────────────────────────────────

_EXPORT_SIZES = {
    "hd":        (1280, 720),
    "fhd":       (1920, 1080),
    "4k":        (3840, 2160),
    "instagram": (1080, 1080),
    "twitter":   (1500, 500),
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


def _hex_to_rgba(hex_str, default):
    try:
        h = hex_str.lstrip("#")
        return tuple(int(h[i:i+2], 16) for i in (0, 2, 4)) + (255,)
    except Exception:
        return default


def _parse_export_params(request):
    """Validate and return all export configuration from query params.
    Accepts both 'size'/'style' (legacy) and 'size_key'/'style_key' (export page).
    """
    size_key = (request.GET.get("size_key") or request.GET.get("size") or "fhd").lower()
    if size_key not in _EXPORT_SIZES:
        size_key = "fhd"
    W, H = _EXPORT_SIZES[size_key]

    style_key = (request.GET.get("style_key") or request.GET.get("style") or "dark").lower()
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

    # Custom background colour (hex, e.g. "#1a1033")
    bg_hex = request.GET.get("bg_color", "").strip()
    bg_color = _hex_to_rgba(bg_hex, None) if bg_hex else None

    # Label appearance
    try:
        label_size = max(10, min(48, int(request.GET.get("label_size", "22"))))
    except ValueError:
        label_size = 22
    label_color = request.GET.get("label_color", "#ffffff").strip()

    # Badge (club crest) radius on the map
    try:
        badge_size = max(7, min(28, int(request.GET.get("badge_size", "13"))))
    except ValueError:
        badge_size = 13

    # Tournament mode: slug + which statuses to show (default confirmed+candidate)
    tournament = request.GET.get("tournament", "").strip()
    tstatus_raw = request.GET.get("tstatus", "").strip().lower()
    if tstatus_raw:
        tstatus = {s.strip().upper() for s in tstatus_raw.split(",")
                   if s.strip().upper() in _TOURNAMENT_STATUS_ORDER}
    else:
        tstatus = {"CONFIRMED", "CANDIDATE"}
    if not tstatus:
        tstatus = {"CONFIRMED", "CANDIDATE"}

    # Layer: operational stadiums (default) or under-development projects.
    layer = request.GET.get("layer", "operational").strip().lower()
    if layer not in ("operational", "development"):
        layer = "operational"
    dstatus_raw = request.GET.get("dstatus", "").strip().upper()
    if dstatus_raw:
        dstatus = {s.strip() for s in dstatus_raw.split(",") if s.strip() in _DEV_STATUSES}
    else:
        dstatus = set(_DEV_STATUSES)
    if not dstatus:
        dstatus = set(_DEV_STATUSES)

    # National-stadiums-only mode (operational layer): venues that host a national side.
    national = request.GET.get("national", "0") == "1"
    # Stricter: only grounds used EXCLUSIVELY by a national team (the insight set).
    national_only = request.GET.get("national_only", "0") == "1"

    return {
        "W": W, "H": H,
        "size_key": size_key,
        "style_key": style_key,
        "color_by": color_by,
        "single_color": single_color,
        "bg_color": bg_color,
        "label_size": label_size,
        "label_color": label_color,
        "badge_size": badge_size,
        "legend": request.GET.get("legend", "0") == "1",
        "north": request.GET.get("north", "0") == "1",
        "scale": request.GET.get("scale", "0") == "1",
        "spotlight": request.GET.get("spotlight", "0") == "1",
        "labels": request.GET.get("labels", "1") == "1",
        "logo": request.GET.get("logo", "0") == "1",
        "tiles": request.GET.get("tiles", "1") != "0",
        "title":    request.GET.get("title", "").strip()[:80],
        "subtitle": request.GET.get("subtitle", "").strip()[:100],
        # filter params
        "surface":   request.GET.get("surface", "").strip().upper(),
        "country":   request.GET.get("country", "").strip(),
        "league":    request.GET.get("league", "").strip(),
        "ownership": request.GET.get("ownership", "").strip().upper(),
        "tournament": tournament,
        "tstatus":    tstatus,
        "layer":      layer,
        "dstatus":    dstatus,
        "national":   national,
        "national_only": national_only,
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
    if params.get("national"):
        qs = qs.filter(teams__is_national=True)
    if params.get("national_only"):
        qs = qs.annotate(
            _nat=Count("teams", filter=Q(teams__is_national=True), distinct=True),
            _club=Count("teams", filter=Q(teams__is_national=False), distinct=True),
        ).filter(_nat__gte=1, _club=0)
    qs = qs.exclude(latitude=None).exclude(longitude=None).distinct()

    results = []
    for s in qs:
        country = s.city.country if s.city else ""
        teams = list(s.teams.all())
        # In national mode, prefer the national side's crest/name as the badge.
        primary_team = None
        if params.get("national") or params.get("national_only"):
            primary_team = next((t for t in teams if t.is_national), None)
        if primary_team is None:
            primary_team = next(iter(teams), None)
        # National sides: use the reliable flagcdn flag (non-free Wikipedia crests
        # often fail the server-side badge fetch — see the live map fix).
        if (primary_team and primary_team.is_national and primary_team.league
                and primary_team.league.country and primary_team.league.country.code):
            image_url = (f"https://flagcdn.com/w160/"
                         f"{_country_flag_code(primary_team.league.country.code)}.png")
        else:
            image_url = (primary_team.image_url or "") if primary_team else ""
        team_name  = (primary_team.name or "") if primary_team else ""
        results.append({
            "name":       s.name,
            "team_name":  team_name,
            "lat":        float(s.latitude),
            "lon":        float(s.longitude),
            "surface":    s.surface or "",
            "country":    country,
            "image_url":  image_url,
        })
    return results


# Venue-status colours for tournament maps (green / orange / red)
_TOURNAMENT_STATUS_COLOR = {
    "CONFIRMED": (40, 199, 111),
    "CANDIDATE": (255, 159, 28),
    "DISCARDED": (231, 76, 60),
}
_TOURNAMENT_STATUS_LABEL = {
    "CONFIRMED": "Confirmed",
    "CANDIDATE": "Candidate",
    "DISCARDED": "Discarded",
}

# Under-development venue status colours (distinct from tournament green/orange/red)
_DEV_STATUSES = ("PLANNING", "APPROVED", "UNDER_CONSTRUCTION", "ON_HOLD", "COMPLETED")
_DEV_STATUS_COLOR = {
    "PLANNING": (219, 39, 119),             # pink/magenta (distinct from Approved blue)
    "APPROVED": (59, 130, 246),             # blue
    "UNDER_CONSTRUCTION": (255, 159, 28),   # orange
    "ON_HOLD": (156, 163, 175),             # grey
    "COMPLETED": (40, 199, 111),            # green
}
_DEV_STATUS_LABEL = {
    "PLANNING": "Planning",
    "APPROVED": "Approved",
    "UNDER_CONSTRUCTION": "Under construction",
    "ON_HOLD": "On hold",
    "COMPLETED": "Completed",
}


def _get_tournament_export_stadiums(params):
    """Export venue dicts for a single tournament, filtered by selected statuses.
    Shape matches _get_export_stadiums plus a `tournament_status` key."""
    _name, _year, venues = _tournament_venues(params["tournament"])
    out = []
    for v in venues:
        if v["latitude"] is None or v["longitude"] is None:
            continue
        if v["status"] not in params["tstatus"]:
            continue
        country = v.get("country_override") or (v["city"].country if v.get("city") else "")
        out.append({
            "name":       v["name"],
            "team_name":  "",
            "lat":        float(v["latitude"]),
            "lon":        float(v["longitude"]),
            "surface":    "",
            "country":    country,
            "image_url":  "",   # tournament maps use colour-coded points, not club badges
            "tournament_status": v["status"],
            "bid": v.get("bid", ""),
        })
    return out


def _get_development_export_stadiums(params):
    """Export venue dicts for under-development projects, filtered by selected
    statuses. Shape matches _get_export_stadiums plus a `dev_status` key."""
    qs = (
        StadiumDevelopment.objects
        .select_related("stadium__city")
        .exclude(latitude=None).exclude(longitude=None)
    )
    out = []
    for d in qs:
        if d.status not in params["dstatus"]:
            continue
        country = d.country or (
            d.stadium.city.country if d.stadium and d.stadium.city else ""
        )
        out.append({
            "name":       d.name,
            "team_name":  "",
            "lat":        float(d.latitude),
            "lon":        float(d.longitude),
            "surface":    "",
            "country":    country,
            "image_url":  "",   # status-coloured points, not club badges
            "dev_status": d.status,
        })
    return out


def _bbox_with_padding(stadiums, pad=0.06):
    lats = [s["lat"] for s in stadiums]
    lons = [s["lon"] for s in stadiums]
    lat_min, lat_max = min(lats), max(lats)
    lon_min, lon_max = min(lons), max(lons)
    lat_pad = max((lat_max - lat_min) * pad, 0.8)
    lon_pad = max((lon_max - lon_min) * pad, 0.8)
    return (
        lon_min - lon_pad, lat_min - lat_pad,
        lon_max + lon_pad, lat_max + lat_pad,
    )


def _merc_y(lat):
    """Latitude → normalized Mercator Y (0 = north pole, 1 = south pole)."""
    lat = max(min(lat, 85.051), -85.051)
    r = math.radians(lat)
    return (1 - math.log(math.tan(r) + 1 / math.cos(r)) / math.pi) / 2


def _merc_y_inv(y):
    """Inverse: normalized Mercator Y → latitude."""
    return math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * y))))


def _expand_bbox_to_aspect(bbox, W, H):
    """Expand bbox symmetrically so its Mercator aspect ratio matches W:H.
    This ensures the exported image isn't geographically stretched."""
    lon_min, lat_min, lon_max, lat_max = bbox
    merc_span_x = (lon_max - lon_min) / 360.0
    merc_span_y = _merc_y(lat_min) - _merc_y(lat_max)
    if merc_span_x <= 0 or merc_span_y <= 0:
        return bbox
    natural_aspect = merc_span_x / merc_span_y
    target_aspect  = W / H
    if natural_aspect > target_aspect:
        # bbox wider than canvas → expand vertically
        new_span_y   = merc_span_x / target_aspect
        merc_mid     = (_merc_y(lat_min) + _merc_y(lat_max)) / 2
        lat_min = _merc_y_inv(min(merc_mid + new_span_y / 2, 0.9999))
        lat_max = _merc_y_inv(max(merc_mid - new_span_y / 2, 0.0001))
    else:
        # bbox taller than canvas → expand horizontally
        new_span_x_deg = merc_span_y * target_aspect * 360.0
        lon_mid   = (lon_min + lon_max) / 2
        half      = new_span_x_deg / 2
        lon_min   = lon_mid - half
        lon_max   = lon_mid + half
    return (lon_min, lat_min, lon_max, lat_max)


def _load_font(bold=False, size=20):
    """Load a TrueType font, trying Windows names then Linux system paths."""
    candidates = (
        ["arialbd.ttf", "Arial Bold.ttf",
         "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
         "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"]
        if bold else
        ["arial.ttf", "Arial.ttf",
         "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
         "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"]
    )
    for name in candidates:
        try:
            return ImageFont.truetype(name, size)
        except Exception:
            pass
    return ImageFont.load_default()


def _split_main_inset(stadiums):
    # The Iceland inset was removed — everything is drawn on the main map.
    return stadiums, []


def _percentile(sorted_vals, q):
    if not sorted_vals:
        return 0.0
    i = q * (len(sorted_vals) - 1)
    lo, hi = int(math.floor(i)), int(math.ceil(i))
    if lo == hi:
        return sorted_vals[lo]
    return sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * (i - lo)


def _trimmed_bbox(stadiums, pad=0.06, qlon=0.02):
    """Frame the bulk of the points, trimming far E/W longitude outliers (e.g. Iceland in
    the west, Ural Russia in the east) so the broad Europe export isn't stretched across
    empty ocean/Asia. Latitude is kept full so northern/southern grounds still show."""
    lons = sorted(s["lon"] for s in stadiums)
    lats = [s["lat"] for s in stadiums]
    lon_min, lon_max = _percentile(lons, qlon), _percentile(lons, 1 - qlon)
    lat_min, lat_max = min(lats), max(lats)
    lat_pad = max((lat_max - lat_min) * pad, 0.8)
    lon_pad = max((lon_max - lon_min) * pad, 0.8)
    return (lon_min - lon_pad, lat_min - lat_pad, lon_max + lon_pad, lat_max + lat_pad)


def _draw_inset(img, inset_stadiums, params, W, H, country_index, style_key):
    """Draw Iceland inset (top-left) with badges and labels."""
    if not inset_stadiums:
        return img

    IW, IH = 280, 200
    margin = 12
    ix0, iy0 = margin, margin

    inset_bbox = _bbox_with_padding(inset_stadiums, pad=0.25)
    inset_img  = _solid_background(style_key, IW, IH, inset_bbox)

    badges = _prefetch_badges(inset_stadiums, size=16)

    try:
        font_s = ImageFont.truetype("arialbd.ttf", 13)
        font_t = ImageFont.truetype("arial.ttf",   11)
    except Exception:
        font_s = font_t = ImageFont.load_default()

    placed = []
    BR, RW = 8, 2
    rr = BR + RW

    for s in inset_stadiums:
        px, py = _lon_lat_to_px(s["lon"], s["lat"], inset_bbox, IW, IH)
        colour    = _dot_colour(s, params, country_index)
        badge_img = badges.get(s["name"])

        d = ImageDraw.Draw(inset_img)
        d.ellipse([px-rr, py-rr, px+rr, py+rr], fill=(255, 255, 255))
        if badge_img:
            b = badge_img.resize((BR*2, BR*2), Image.LANCZOS)
            mask = Image.new("L", (BR*2, BR*2), 0)
            ImageDraw.Draw(mask).ellipse([0, 0, BR*2-1, BR*2-1], fill=255)
            inset_img.paste(b, (px-BR, py-BR), mask)
        else:
            d.ellipse([px-BR, py-BR, px+BR, py+BR], fill=colour)

        # Simple label: team / stadium, right or left
        label1 = s.get("team_name", "") or ""
        label2 = s["name"]
        tw = max(len(label1)*6, len(label2)*7)
        th = 26
        gap = 8
        lx = px + rr + gap if px + rr + gap + tw < IW - 2 else px - rr - gap - tw
        ly = py - th // 2
        box = (lx, ly, lx + tw, ly + th)
        if not any(not (box[2]<pb[0] or box[0]>pb[2] or box[3]<pb[1] or box[1]>pb[3]) for pb in placed):
            d = ImageDraw.Draw(inset_img)
            d.rounded_rectangle([lx-2,ly-2,lx+tw+2,ly+th+2], radius=3, fill=(8,10,20,210))
            # leader line
            d.line([(px + (rr if lx > px else -rr), py), (lx if lx > px else lx+tw, py)],
                   fill=(255,255,255,160), width=1)
            if label1:
                d.text((lx, ly+2), label1, font=font_t, fill=(180,210,255))
            d.text((lx, ly+14 if label1 else ly+6), label2, font=font_s, fill=(255,255,255))
            placed.append(box)

    d = ImageDraw.Draw(inset_img)
    d.rectangle([(0,0),(IW-1,IH-1)], outline=(160,165,190), width=2)
    try:
        fhdr = ImageFont.truetype("arial.ttf", 12)
    except Exception:
        fhdr = ImageFont.load_default()
    d.text((6, IH-18), "Iceland / Faroe Is.", font=fhdr, fill=(210,215,230))

    img.paste(inset_img, (ix0, iy0))
    return img


def _lon_lat_to_px(lon, lat, bbox, W, H):
    """Mercator projection: lon/lat → pixel coordinates within the export image."""
    lon_min, lat_min, lon_max, lat_max = bbox
    x = (lon - lon_min) / (lon_max - lon_min) * W
    y = (_merc_y(lat) - _merc_y(lat_max)) / (_merc_y(lat_min) - _merc_y(lat_max)) * H
    return int(x), int(y)


def _orth_seg_hits_box(ax, ay, bx, by, box):
    """Intersection test for an axis-aligned (horizontal or vertical) segment
    against a rectangle box=(x0,y0,x1,y1). Leader polylines are orthogonal, so
    this cheap test catches a leader line crossing another label's pill."""
    bx0, by0, bx1, by1 = box
    if ay == by:                                  # horizontal segment
        xlo, xhi = (ax, bx) if ax <= bx else (bx, ax)
        return by0 <= ay <= by1 and xlo <= bx1 and xhi >= bx0
    else:                                         # vertical segment (ax == bx)
        ylo, yhi = (ay, by) if ay <= by else (by, ay)
        return bx0 <= ax <= bx1 and ylo <= by1 and yhi >= by0


def _point_in_ring(lon, lat, ring):
    """Ray-casting point-in-polygon for a single ring of [lon, lat] pairs."""
    inside = False
    n = len(ring)
    j = n - 1
    for i in range(n):
        xi, yi = ring[i][0], ring[i][1]
        xj, yj = ring[j][0], ring[j][1]
        if ((yi > lat) != (yj > lat)) and \
           (lon < (xj - xi) * (lat - yi) / ((yj - yi) or 1e-12) + xi):
            inside = not inside
        j = i
    return inside


def _spotlight_country(img, stadiums, bbox, W, H, dim=165):
    """Dim everything OUTSIDE the country/countries that contain the displayed
    stadiums, and outline those borders, so the selected country stands out.
    Name-independent: identifies the country by which polygon contains the
    stadiums (works even for England → the UK polygon)."""
    pts = [(s["lon"], s["lat"]) for s in stadiums]
    if not pts:
        return img

    mask = Image.new("L", (W, H), 0)
    md = ImageDraw.Draw(mask)
    border_rings = []
    try:
        # Use the hi-res Natural Earth 10m set: one named MultiPolygon per country
        # (Italy incl. Sicily/Sardinia, Serbia incl. Vojvodina, Bosnia whole, Denmark
        # incl. its islands), so the spotlight outline is crisp and never drops a region.
        feats = _load_countries_hi()
    except Exception:
        return img

    for feat in feats:
        geom = feat["geometry"]
        if geom["type"] == "Polygon":
            rings = [geom["coordinates"][0]]
        elif geom["type"] == "MultiPolygon":
            rings = [poly[0] for poly in geom["coordinates"]]
        else:
            continue
        # Does ANY ring of this country contain a displayed stadium?
        matched = False
        for ring in rings:
            rlons = [c[0] for c in ring]; rlats = [c[1] for c in ring]
            rl0, rl1, ra0, ra1 = min(rlons), max(rlons), min(rlats), max(rlats)
            cand = [(lo, la) for lo, la in pts if rl0 <= lo <= rl1 and ra0 <= la <= ra1]
            if cand and any(_point_in_ring(lo, la, ring) for lo, la in cand):
                matched = True
                break
        if not matched:
            continue
        # Draw the WHOLE country (every island / region), not just the part that
        # happens to hold a stadium — so Denmark keeps Jutland, Serbia keeps
        # Vojvodina, Bosnia stays whole, etc.
        for ring in rings:
            pix = [_lon_lat_to_px(lo, la, bbox, W, H) for lo, la in ring]
            if len(pix) >= 3:
                md.polygon(pix, fill=255)
                border_rings.append(pix)

    if not border_rings:
        return img  # no polygon matched — leave the map untouched

    # Dim the outside: paste a dark colour with per-pixel alpha = dim where mask==0
    from PIL import ImageChops
    outside = ImageChops.invert(mask).point(lambda p: dim if p > 127 else 0)
    img.paste(Image.new("RGB", (W, H), (3, 5, 12)), (0, 0), outside)

    # Bright border around the selected country
    d = ImageDraw.Draw(img)
    for pix in border_rings:
        d.line(pix + [pix[0]], fill=(0, 230, 255), width=2)
    return img


def _fetch_one_tile(z, x, y, style_key):
    """Fetch a single 256×256 tile, caching to /tmp only.

    Deliberately does NOT use Django's in-process LocMemCache — holding tile PNG
    bytes in RAM grows the worker's footprint render-after-render and contributes
    to OOM on the 512 MB dyno. The /tmp disk cache is enough and is shared across
    workers on the same instance.
    """
    disk_path = None
    try:
        disk_dir = _os.path.join(_os.path.sep, "tmp", "soe_tiles")
        _os.makedirs(disk_dir, exist_ok=True)
        disk_path = _os.path.join(disk_dir, f"{style_key}_{z}_{x}_{y}.png")
        if _os.path.exists(disk_path):
            return Image.open(disk_path).convert("RGBA")
    except Exception:
        disk_path = None

    url = _TILE_SERVERS[style_key].format(z=z, x=x, y=y)
    headers = {"User-Agent": "StadiumsOfEurope/1.0 (stadiumsofeurope.com)"}
    resp = _requests.get(url, timeout=4, headers=headers)
    resp.raise_for_status()
    if disk_path:
        try:
            with open(disk_path, "wb") as fh:
                fh.write(resp.content)
        except Exception:
            pass
    return Image.open(io.BytesIO(resp.content)).convert("RGBA")


_LAND_COLOURS = {
    "dark":      (38,  46,  72,  255),   # noticeably brighter than bg (18,22,36)
    "light":     (215, 220, 228, 255),
    "topo":      (200, 218, 180, 255),
    "satellite": (28,  44,  28,  255),
}
_BORDER_COLOURS = {
    "dark":      (85, 100, 150, 255),    # strong blue-grey border
    "light":     (155, 162, 175, 255),
    "topo":      (140, 165, 120, 255),
    "satellite": (50,  70,  50,  255),
}

_countries_cache = None
_countries_hi_cache = None

def _load_countries():
    global _countries_cache
    if _countries_cache is None:
        p = Path(__file__).parent / "static" / "data" / "countries_110m.geojson"
        with open(p, encoding="utf-8") as f:
            _countries_cache = json.load(f)["features"]
    return _countries_cache


def _load_countries_hi():
    """High-resolution (Natural Earth 10m, Europe only) borders for the spotlight
    outline, so a selected country looks crisp. Falls back to 110m if absent."""
    global _countries_hi_cache
    if _countries_hi_cache is None:
        p = Path(__file__).parent / "static" / "data" / "countries_hires.geojson"
        try:
            with open(p, encoding="utf-8") as f:
                _countries_hi_cache = json.load(f)["features"]
        except Exception:
            _countries_hi_cache = _load_countries()
    return _countries_hi_cache


def _draw_countries(img, bbox, W, H, style_key, land_color=None):
    """Draw country land + outlines from the bundled Natural Earth 110m dataset."""
    land   = land_color or _LAND_COLOURS.get(style_key, _LAND_COLOURS["dark"])
    border = _BORDER_COLOURS.get(style_key, _BORDER_COLOURS["dark"])
    lon_min, lat_min, lon_max, lat_max = bbox
    pad = 5  # degrees beyond bbox to catch clipped polygons

    d = ImageDraw.Draw(img)
    for feat in _load_countries():
        geom = feat["geometry"]
        rings = []
        if geom["type"] == "Polygon":
            rings = [geom["coordinates"][0]]
        elif geom["type"] == "MultiPolygon":
            rings = [poly[0] for poly in geom["coordinates"]]
        for ring in rings:
            # Check if ring overlaps the extended view bbox at all
            if not any(
                (lon_min - pad) <= lon <= (lon_max + pad) and
                (lat_min - pad) <= lat <= (lat_max + pad)
                for lon, lat in ring
            ):
                continue
            # Project ALL points — Pillow clips naturally; per-point filtering
            # creates broken polygons for rings that cross the bbox edge
            pts = [_lon_lat_to_px(lon, lat, bbox, W, H) for lon, lat in ring]
            if len(pts) >= 3:
                d.polygon(pts, fill=land, outline=border)
    return img


def _solid_background(style_key, W, H, bbox, land_color=None):
    """Sea = style background; land = land_color (user pick) or default land colour."""
    img = Image.new("RGBA", (W, H), _STYLE_BACKGROUNDS[style_key])
    try:
        img = _draw_countries(img, bbox, W, H, style_key, land_color=land_color)
    except Exception:
        pass
    return img


def _make_background(style_key, W, H, bbox, use_tiles=True, land_color=None):
    """Base map matching the live Leaflet CARTO tiles (R1).

    Memory-bounded: pastes each 256×256 tile DIRECTLY into the W×H output image,
    scaled/positioned per the aspect-corrected bbox. Peak memory is just the
    output image + a handful of in-flight tiles — never a giant stitch canvas,
    so it stays well under the 512 MB Render limit (the old stitch+crop approach
    built a ~98 MB intermediate at z=7 and OOM-killed the dyno).
    """
    if not use_tiles or style_key not in _TILE_SERVERS:
        return _solid_background(style_key, W, H, bbox, land_color=land_color)

    lon_min, lat_min, lon_max, lat_max = bbox
    lon_min = max(lon_min, -179.9); lon_max = min(lon_max, 179.9)
    lat_min = max(lat_min, -85.0);  lat_max = min(lat_max, 85.0)

    # Pick the largest zoom where the bbox covers at least the output pixels
    # (so tiles are downscaled → crisp), but cap total tiles to bound HTTP work.
    # For small countries no zoom reaches the output size, so fall back to the
    # HIGHEST affordable zoom (most detail). Picking the lowest zoom here was a
    # bug: a tiny bbox at z=3 makes the per-tile upscale enormous (256→16000px)
    # → ~1 GB allocation → instant OOM 502 (Malta/Cyprus/N. Macedonia).
    MAX_TILES = 160
    z = None
    best_affordable = None
    for z_try in range(8, 2, -1):
        n = 2 ** z_try
        tx_min_f = (lon_min + 180) / 360 * n
        tx_max_f = (lon_max + 180) / 360 * n
        ty_min_f = _merc_y(lat_max) * n
        ty_max_f = _merc_y(lat_min) * n
        ntiles = (int(tx_max_f) - int(tx_min_f) + 1) * (int(ty_max_f) - int(ty_min_f) + 1)
        if ntiles > MAX_TILES:
            continue
        if best_affordable is None:
            best_affordable = z_try          # highest zoom under the tile cap
        span_x = (tx_max_f - tx_min_f) * _TILE_SIZE
        span_y = (ty_max_f - ty_min_f) * _TILE_SIZE
        if span_x >= W or span_y >= H:
            z = z_try                         # crisp: tiles downscale to fit
            break
    if z is None:
        z = best_affordable if best_affordable is not None else 3

    n = 2 ** z
    tx_min_f = (lon_min + 180) / 360 * n
    tx_max_f = (lon_max + 180) / 360 * n
    ty_min_f = _merc_y(lat_max) * n   # lat_max → smaller y (north = top)
    ty_max_f = _merc_y(lat_min) * n

    tx0, tx1 = max(0, int(tx_min_f)), min(n - 1, int(tx_max_f))
    ty0, ty1 = max(0, int(ty_min_f)), min(n - 1, int(ty_max_f))

    # Linear map: tile-pixel space → output (W×H) space
    px_min = tx_min_f * _TILE_SIZE
    py_min = ty_min_f * _TILE_SIZE
    sx = W / ((tx_max_f - tx_min_f) * _TILE_SIZE)
    sy = H / ((ty_max_f - ty_min_f) * _TILE_SIZE)

    # Defense-in-depth: if a single tile would have to be upscaled past ~2× the
    # output (degenerate tiny bbox), the resize would allocate hundreds of MB and
    # OOM the dyno. Fall back to the lightweight diagram background instead.
    if _TILE_SIZE * sx > 2 * W or _TILE_SIZE * sy > 2 * H:
        return _solid_background(style_key, W, H, bbox, land_color=land_color)

    out = Image.new("RGBA", (W, H), _STYLE_BACKGROUNDS[style_key])

    coords = [(tx, ty) for tx in range(tx0, tx1 + 1) for ty in range(ty0, ty1 + 1)]

    def _fetch(coord):
        tx, ty = coord
        try:
            return coord, _fetch_one_tile(z, tx, ty, style_key)
        except Exception:
            return coord, None

    deadline = _time.monotonic() + 18  # leave headroom under Render's 30s
    with ThreadPoolExecutor(max_workers=8) as pool:
        for coord, tile in pool.map(_fetch, coords):
            if _time.monotonic() > deadline:
                break
            if not tile:
                continue
            tx, ty = coord
            # Destination box for this tile in output space
            dx0 = int(round((tx * _TILE_SIZE - px_min) * sx))
            dy0 = int(round((ty * _TILE_SIZE - py_min) * sy))
            dx1 = int(round(((tx + 1) * _TILE_SIZE - px_min) * sx))
            dy1 = int(round(((ty + 1) * _TILE_SIZE - py_min) * sy))
            tw, th = max(1, dx1 - dx0), max(1, dy1 - dy0)
            try:
                resized = tile.resize((tw, th), Image.LANCZOS)
                out.paste(resized, (dx0, dy0))
            except Exception:
                pass
    return out


_BADGE_DISK_CACHE = _os.path.join(_os.path.sep, "tmp", "soe_badges")
try:
    _os.makedirs(_BADGE_DISK_CACHE, exist_ok=True)
except Exception:
    _BADGE_DISK_CACHE = None


def _fetch_badge_image(url, size=20):
    """Download, resize, and cache a badge image to /tmp only (no in-process
    Django cache — see _fetch_one_tile for why)."""
    if not url:
        return None
    key = hashlib.md5(f"{url}_{size}".encode()).hexdigest()

    # 1. Disk cache (/tmp survives between requests on the same dyno)
    disk_path = _os.path.join(_BADGE_DISK_CACHE, f"{key}.png") if _BADGE_DISK_CACHE else None
    if disk_path and _os.path.exists(disk_path):
        try:
            return Image.open(disk_path).convert("RGBA")
        except Exception:
            pass

    # 2. Fetch from web
    try:
        r = _requests.get(url, timeout=3, headers={"User-Agent": "StadiumsOfEurope/1.0"})
        r.raise_for_status()
        img = Image.open(io.BytesIO(r.content)).convert("RGBA")
        w, h = img.size
        if h > w:
            img = img.crop((0, 0, w, w))
        img = img.resize((size, size), Image.LANCZOS)
        if disk_path:
            try:
                img.save(disk_path, format="PNG")
            except Exception:
                pass
        return img
    except Exception:
        return None


def _prefetch_badges(stadiums, size=20):
    """Fetch badge images in parallel with a hard 22-second wall-clock budget.
    Returns whatever loaded in time — uncached badges are skipped gracefully."""
    items = [(s["name"], s.get("image_url", "")) for s in stadiums if s.get("image_url")]
    if not items:
        return {}

    deadline = _time.monotonic() + 22   # hard budget — stay under Render's 30s limit
    result = {}

    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = {pool.submit(_fetch_badge_image, url, size): name for name, url in items}
        try:
            for future in as_completed(futures, timeout=22):
                if _time.monotonic() > deadline:
                    break
                name = futures[future]
                try:
                    img = future.result(timeout=0)
                    if img:
                        result[name] = img
                except Exception:
                    pass
        except Exception:
            pass   # TimeoutError from as_completed — return what we have

    return result


def _dot_colour(stadium, params, country_index):
    if params["color_by"] == "tournament_status":
        return _TOURNAMENT_STATUS_COLOR.get(
            stadium.get("tournament_status", "CANDIDATE"), _DEFAULT_DOT_COLOUR)
    if params["color_by"] == "dev_status":
        return _DEV_STATUS_COLOR.get(
            stadium.get("dev_status", "PLANNING"), _DEFAULT_DOT_COLOUR)
    if params["color_by"] == "bid":
        return _BID_COLOR.get(stadium.get("bid", ""), _DEFAULT_DOT_COLOUR)
    if params["color_by"] == "single":
        return params["single_color"]
    if params["color_by"] == "country":
        idx = country_index.get(stadium["country"], 0)
        return _COUNTRY_PALETTE[idx % len(_COUNTRY_PALETTE)]
    # surface
    return _SURFACE_COLOURS.get(stadium["surface"], _DEFAULT_DOT_COLOUR)


def _draw_dots_and_labels(img, stadiums, params, bbox, W, H, country_index, reserve_boxes=None):
    BADGE_R   = params.get("badge_size", 13)
    RING_W    = 2
    FONT_SZ   = params.get("label_size", 22)
    FONT_SZ2  = max(10, int(FONT_SZ * 0.78))
    PAD_X     = 10
    PAD_Y     = 7
    LINE_GAP  = 3

    # Parse label colour — hex string → RGB tuple
    try:
        lc_hex = params.get("label_color", "#ffffff").lstrip("#")
        label_rgb = tuple(int(lc_hex[i:i+2], 16) for i in (0, 2, 4))
    except Exception:
        label_rgb = (255, 255, 255)
    team_rgb = tuple(min(255, int(c * 0.75) + 40) for c in label_rgb)  # slightly dimmer for team line

    badges = _prefetch_badges(stadiums, size=BADGE_R * 2)

    draw = ImageDraw.Draw(img)
    font_team    = _load_font(bold=False, size=FONT_SZ2)
    font_stadium = _load_font(bold=True,  size=FONT_SZ)

    rr = BADGE_R + RING_W

    placed_boxes  = []
    badge_circles = []

    def _seg_hits_badge(ax, ay, bx, by, own_px, own_py):
        """Return True if segment (ax,ay)→(bx,by) intersects any badge circle
        except the one at (own_px, own_py)."""
        for bcx, bcy, br in badge_circles:
            if bcx == own_px and bcy == own_py:
                continue
            dx, dy = bx - ax, by - ay
            fx, fy = ax - bcx, ay - bcy
            a = dx*dx + dy*dy
            if a == 0:
                continue
            b = 2*(fx*dx + fy*dy)
            c = fx*fx + fy*fy - (br + 3)**2
            disc = b*b - 4*a*c
            if disc < 0:
                continue
            sd = math.sqrt(disc)
            t1 = (-b - sd) / (2*a)
            t2 = (-b + sd) / (2*a)
            if (0 <= t1 <= 1) or (0 <= t2 <= 1):
                return True
        return False

    def _box_overlaps(box, pills=True, badges=True):
        x0, y0, x1, y1 = box
        if pills:
            for pb in placed_boxes:
                if not (x1 < pb[0] or x0 > pb[2] or y1 < pb[1] or y0 > pb[3]):
                    return True
        if badges:
            cx2, cy2 = (x0 + x1) / 2, (y0 + y1) / 2
            hw, hh = (x1 - x0) / 2, (y1 - y0) / 2
            for bcx, bcy, br in badge_circles:
                dx = max(abs(bcx - cx2) - hw, 0)
                dy = max(abs(bcy - cy2) - hh, 0)
                if dx*dx + dy*dy < (br + 4)**2:
                    return True
        return False

    # First pass: tournament maps draw colour-coded POINTS (status colour + white
    # halo, no club badge); all other maps draw the club badge with a white ring.
    tournament_mode = params.get("color_by") == "tournament_status"
    dot_positions = []
    for s in stadiums:
        px, py = _lon_lat_to_px(s["lon"], s["lat"], bbox, W, H)
        colour    = _dot_colour(s, params, country_index)

        if tournament_mode:
            # white halo for contrast on satellite/dark, then the status dot
            draw.ellipse([px - rr, py - rr, px + rr, py + rr], fill=(255, 255, 255))
            draw.ellipse([px - BADGE_R, py - BADGE_R, px + BADGE_R, py + BADGE_R], fill=colour)
        else:
            badge_img = badges.get(s["name"])
            draw.ellipse([px - rr, py - rr, px + rr, py + rr], fill=(255, 255, 255))
            if badge_img:
                mask = Image.new("L", (BADGE_R * 2, BADGE_R * 2), 0)
                ImageDraw.Draw(mask).ellipse([0, 0, BADGE_R * 2 - 1, BADGE_R * 2 - 1], fill=255)
                img.paste(badge_img, (px - BADGE_R, py - BADGE_R), mask)
                draw = ImageDraw.Draw(img)
            else:
                draw.ellipse([px - BADGE_R, py - BADGE_R, px + BADGE_R, py + BADGE_R], fill=colour)

        badge_circles.append((px, py, rr))
        dot_positions.append((px, py, s))

    if not params["labels"]:
        return img

    # Labels never overlap (see placement below). A single league always fits;
    # only very dense multi-league maps drop a few labels that can't be placed
    # cleanly — no-overlap reads far better than stacked labels.

    def _polyline_clear(pts, own_px, own_py, avoid_boxes=True):
        """True if no segment of the orthogonal polyline crosses another badge —
        and, when avoid_boxes, no segment crosses an already-placed label pill."""
        for i in range(len(pts) - 1):
            ax, ay = pts[i]
            bx, by = pts[i + 1]
            if _seg_hits_badge(ax, ay, bx, by, own_px, own_py):
                return False
            if avoid_boxes:
                for pb in placed_boxes:
                    if _orth_seg_hits_box(ax, ay, bx, by, pb):
                        return False
        return True

    def _route(px, py, side, lx, ly, pill_w, pill_h, allow_cross=False, avoid_boxes=True):
        """Build an orthogonal (90°-bend) leader polyline from the badge to the
        pill's near side. Tries a horizontal-first elbow AND a vertical-first
        elbow (the latter lets a badge in a tight cluster escape up/down before
        going sideways). Returns the first route that clears all other badges
        (and, when avoid_boxes, other label pills), or — when allow_cross — the
        horizontal elbow regardless."""
        cy = ly + pill_h / 2                      # pill vertical centre
        if side == "right":
            connect_x = lx                        # pill left edge
            hx = px + rr + 1                       # horizontal anchor on ring
        else:
            connect_x = lx + pill_w               # pill right edge
            hx = px - rr - 1
        # A) horizontal → vertical → horizontal
        bend_x = (hx + connect_x) / 2
        route_h = [(hx, py), (bend_x, py), (bend_x, cy), (connect_x, cy)]
        # B) vertical-first: exit the badge top/bottom toward the pill row, then across
        vy = py - rr - 1 if cy < py else py + rr + 1
        route_v = [(px, vy), (px, cy), (connect_x, cy)]
        for pts in (route_h, route_v):
            if _polyline_clear(pts, px, py, avoid_boxes=avoid_boxes):
                return pts
        return route_h if allow_cross else None

    # Place labels left-to-right so left badges claim left space first
    order = sorted(dot_positions, key=lambda t: t[0])

    # Hard wall-clock budget: label placement is O(n²); for huge selections it
    # could run ~30-50s, blow Render's request timeout, and stack memory across
    # retries → OOM. Stop placing once the budget is spent (remaining labels are
    # dropped, which R3 permits at ≥70 badges; small maps finish well within it).
    label_deadline = _time.monotonic() + 10

    for px, py, s in order:
        if _time.monotonic() > label_deadline:
            break
        team_line    = s.get("team_name", "") or ""
        stadium_line = s["name"]

        try:
            tb1 = draw.textbbox((0, 0), team_line,    font=font_team)
            tw1, th1 = tb1[2] - tb1[0], tb1[3] - tb1[1]
            tb2 = draw.textbbox((0, 0), stadium_line, font=font_stadium)
            tw2, th2 = tb2[2] - tb2[0], tb2[3] - tb2[1]
        except AttributeError:
            tw1, th1 = len(team_line) * 7, FONT_SZ2
            tw2, th2 = len(stadium_line) * 9, FONT_SZ

        show_team = bool(team_line)
        pill_w = max(tw1, tw2) + PAD_X * 2
        pill_h = (th1 + LINE_GAP + th2 if show_team else th2) + PAD_Y * 2

        # R2 side rule: left-half badges → label left, right-half → label right
        primary_side = "left" if px < W / 2 else "right"
        vstep = pill_h + 6

        # Candidate generation: gaps reach most of the canvas WIDTH so labels can
        # be pushed all the way into the far left/right margins (e.g. the empty sea
        # either side of a narrow country), using the whole frame. Rich search +
        # both sides always, since labels are never allowed to overlap.
        maxgap = int(W * 0.60)
        base_gaps = [int(maxgap * f) for f in (1.0, 0.78, 0.60, 0.45, 0.33, 0.24, 0.17, 0.11)]
        base_voffs = [0]
        for k in range(1, 16):
            base_voffs += [-k * vstep, k * vstep]

        # Prefer the natural side (left badge → left) but allow the other side too.
        sides = [primary_side, "right" if primary_side == "left" else "left"]

        EDGE_MARGIN = max(24, int(min(W, H) * 0.035))   # breathing room from edges

        def _search(allow_overlap, allow_cross, avoid_lines):
            best = None
            best_score = None
            # Balance the two side margins: count labels already placed on each
            # half so we can nudge the next one toward the emptier side.
            left_n = sum(1 for b in placed_boxes if (b[0] + b[2]) / 2 < W / 2)
            right_n = len(placed_boxes) - left_n
            for side in sides:
                for voff in base_voffs:
                    for gap in base_gaps:
                        if side == "right":
                            lx = int(px + gap)
                        else:
                            lx = int(px - gap - pill_w)
                        ly = int(py + voff - pill_h / 2)
                        if (lx < EDGE_MARGIN or ly < EDGE_MARGIN
                                or lx + pill_w > W - EDGE_MARGIN
                                or ly + pill_h > H - EDGE_MARGIN):
                            continue
                        box = (lx, ly, lx + pill_w, ly + pill_h)
                        # Never place a label over a reserved overlay area (title,
                        # logo, legend, scale bar, north arrow) — always enforced.
                        if reserve_boxes and any(
                            not (box[2] < rb[0] or box[0] > rb[2] or box[3] < rb[1] or box[1] > rb[3])
                            for rb in reserve_boxes
                        ):
                            continue
                        # A label pill may overlap OTHER pills in the relaxed pass,
                        # but must NEVER cover a badge (badges are the anchors).
                        if _box_overlaps(box, pills=not allow_overlap, badges=True):
                            continue
                        pts = _route(px, py, side, lx, ly, pill_w, pill_h,
                                     allow_cross=allow_cross, avoid_boxes=avoid_lines)
                        if pts is None:
                            continue
                        # Prefer the LEFT/RIGHT margins (the side seas) over the
                        # top/bottom edges: score is mainly horizontal distance to
                        # the nearer side, with a light vertical fallback term.
                        cx2 = (box[0] + box[2]) / 2
                        cy2 = (box[1] + box[3]) / 2
                        edge = min(cx2, W - cx2) + 0.25 * min(cy2, H - cy2)
                        # Gentle balance across the two margins, but a leader-line
                        # length penalty keeps each label NEAR its own badge so we
                        # don't fling an east-side badge's label to the west edge
                        # (which caused labels to collide).
                        crowd = (left_n if cx2 < W / 2 else right_n) * 4
                        linelen = abs(px - cx2) + abs(py - cy2)
                        score = edge + crowd + 0.18 * linelen
                        if best_score is None or score < best_score:
                            best, best_score = (lx, ly, box, pts), score
            return best

        # Labels NEVER overlap. Escalate while keeping pills non-overlapping:
        #  1. clean: line avoids badges AND other label pills
        #  2. line may cross another label pill (but not a badge)
        #  3. line may cross a badge too (pill still doesn't overlap anything)
        # Only if no NON-overlapping pill position exists at all do we drop it.
        chosen = _search(allow_overlap=False, allow_cross=False, avoid_lines=True)
        if chosen is None:
            chosen = _search(allow_overlap=False, allow_cross=False, avoid_lines=False)
        if chosen is None:
            chosen = _search(allow_overlap=False, allow_cross=True, avoid_lines=False)

        if not chosen:
            continue  # no non-overlapping spot anywhere → drop (never stack)

        lx, ly, box, pts = chosen

        # ── Orthogonal leader polyline + pill — sharp 90° corners ──
        draw.line([(int(x), int(y)) for x, y in pts], fill=label_rgb, width=1)
        draw.rounded_rectangle([lx, ly, lx + pill_w, ly + pill_h], radius=5, fill=(8, 10, 20, 220))

        ty = ly + PAD_Y
        if show_team:
            draw.text((lx + PAD_X, ty), team_line, font=font_team, fill=team_rgb)
            ty += th1 + LINE_GAP
        draw.text((lx + PAD_X, ty), stadium_line, font=font_stadium, fill=label_rgb)

        placed_boxes.append(box)

    return img


def _build_legend_entries(params, stadiums):
    """Return list of (colour_tuple, label_str) for the legend."""
    if params["color_by"] == "tournament_status":
        present = {s.get("tournament_status", "CANDIDATE") for s in stadiums}
        return [
            (_TOURNAMENT_STATUS_COLOR[st], _TOURNAMENT_STATUS_LABEL[st])
            for st in ("CONFIRMED", "CANDIDATE", "DISCARDED") if st in present
        ]
    if params["color_by"] == "dev_status":
        present = {s.get("dev_status", "PLANNING") for s in stadiums}
        return [
            (_DEV_STATUS_COLOR[st], _DEV_STATUS_LABEL[st])
            for st in _DEV_STATUSES if st in present
        ]
    if params["color_by"] == "bid":
        present = [b for b in _BID_COLOR if any(s.get("bid") == b for s in stadiums)]
        return [(_BID_COLOR[b], f"{b} bid") for b in present]
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

    d = ImageDraw.Draw(img)
    d.rounded_rectangle([x0, y0, x0 + box_w, y0 + box_h], radius=8, fill=(20, 20, 20, 190))

    for i, (colour, label) in enumerate(entries):
        cy = y0 + padding + i * line_h + dot_r
        cx = x0 + padding + dot_r
        d.ellipse([cx - dot_r, cy - dot_r, cx + dot_r, cy + dot_r], fill=colour)
        d.text((cx + dot_r + 8, cy - 8), label, font=font, fill=(230, 230, 230))

    return img


def _draw_north_arrow(img, W, H):
    d = ImageDraw.Draw(img)
    margin = 20
    cx, cy = W - margin - 18, margin + 30
    d.polygon([(cx, cy - 20), (cx - 8, cy + 4), (cx + 8, cy + 4)], fill=(255, 255, 255, 220))
    d.polygon([(cx, cy - 20), (cx - 8, cy + 4), (cx, cy - 4)], fill=(100, 100, 100, 220))
    d.text((cx - 5, cy + 6), "N", font=_load_font(bold=True, size=14), fill=(255, 255, 255, 220))
    return img


def _draw_title(img, title_text, W, subtitle_text=""):
    font_title    = _load_font(bold=True,  size=32)
    font_subtitle = _load_font(bold=False, size=20)

    d = ImageDraw.Draw(img)
    PAD = 14
    GAP = 6

    def _tw_th(text, font):
        try:
            bb = d.textbbox((0, 0), text, font=font)
            return bb[2] - bb[0], bb[3] - bb[1]
        except AttributeError:
            return len(text) * 16, 28

    tw1, th1 = _tw_th(title_text, font_title)
    tw2, th2 = (_tw_th(subtitle_text, font_subtitle) if subtitle_text else (0, 0))

    box_w = max(tw1, tw2) + PAD * 2
    box_h = th1 + (GAP + th2 if subtitle_text else 0) + PAD * 2

    rx0 = (W - box_w) // 2
    ry0 = 20
    rx1, ry1 = rx0 + box_w, ry0 + box_h

    d.rounded_rectangle([rx0, ry0, rx1, ry1], radius=8, fill=(10, 12, 22, 210))
    tx = rx0 + (box_w - tw1) // 2
    d.text((tx, ry0 + PAD), title_text, font=font_title, fill=(255, 255, 255))
    if subtitle_text:
        sx = rx0 + (box_w - tw2) // 2
        d.text((sx, ry0 + PAD + th1 + GAP), subtitle_text, font=font_subtitle, fill=(0, 220, 255))

    return img


def _title_layout(params, W):
    """Geometry + fonts for the title/subtitle block (top-centre), or None.
    Used both to reserve the area from labels and to draw the translucent box."""
    if not params.get("title"):
        return None
    title_text    = params["title"]
    subtitle_text = params.get("subtitle", "")
    ft = _load_font(bold=True,  size=32)
    fs = _load_font(bold=False, size=20)
    tmp = ImageDraw.Draw(Image.new("RGBA", (1, 1)))

    def _dim(text, font):
        try:
            bb = tmp.textbbox((0, 0), text, font=font)
            return bb[2] - bb[0], bb[3] - bb[1]
        except AttributeError:
            return len(text) * 16, 28

    tw1, th1 = _dim(title_text, ft)
    tw2, th2 = (_dim(subtitle_text, fs) if subtitle_text else (0, 0))
    PAD, GAP = 14, 6
    box_w = max(tw1, tw2) + PAD * 2
    box_h = th1 + (GAP + th2 if subtitle_text else 0) + PAD * 2
    rx0 = (W - box_w) // 2
    ry0 = 20
    return {
        "title": title_text, "subtitle": subtitle_text, "ft": ft, "fs": fs,
        "tw1": tw1, "th1": th1, "tw2": tw2, "th2": th2,
        "x0": rx0, "y0": ry0, "w": box_w, "h": box_h, "PAD": PAD, "GAP": GAP,
    }


def _draw_title_translucent(img, L):
    """Draw the title/subtitle in a TRANSLUCENT rounded box at top-centre so the
    map shows through it (no opaque header bar). Composites only the box region,
    so it's memory-cheap."""
    x0, y0, bw, bh = L["x0"], L["y0"], L["w"], L["h"]
    # Build the box on a small RGBA tile and alpha-composite it over the map,
    # so the fill's alpha actually blends with the map underneath.
    tile = Image.new("RGBA", (bw, bh), (0, 0, 0, 0))
    td = ImageDraw.Draw(tile)
    td.rounded_rectangle([0, 0, bw - 1, bh - 1], radius=8, fill=(10, 12, 22, 140))  # ~55% opacity
    tx = (bw - L["tw1"]) // 2
    td.text((tx, L["PAD"]), L["title"], font=L["ft"], fill=(255, 255, 255))
    if L["subtitle"]:
        sx = (bw - L["tw2"]) // 2
        td.text((sx, L["PAD"] + L["th1"] + L["GAP"]), L["subtitle"], font=L["fs"], fill=(0, 220, 255))
    region = img.crop((x0, y0, x0 + bw, y0 + bh))
    region = Image.alpha_composite(region, tile)
    img.paste(region, (x0, y0))
    return img


def _draw_scale_bar(img, bbox, W, H):
    """Draw a distance scale bar (bottom-centre) showing real-world km, computed
    from the bbox at its centre latitude. Avoids legend (bottom-left), logo
    (bottom-right), north arrow (top-right) and title (top band)."""
    lon_min, lat_min, lon_max, lat_max = bbox
    lat_c = (lat_min + lat_max) / 2.0
    ground_width_m = (lon_max - lon_min) * 111320.0 * max(0.05, math.cos(math.radians(lat_c)))
    if ground_width_m <= 0:
        return img
    m_per_px = ground_width_m / W
    # Target bar ≈ 1/6 of width, rounded to a nice 1/2/5 × 10ⁿ value
    target_m = m_per_px * (W / 6.0)
    exp = math.floor(math.log10(target_m))
    base = 10 ** exp
    for mult in (5, 2, 1):
        if base * mult <= target_m:
            nice_m = base * mult
            break
    else:
        nice_m = base
    bar_px = int(nice_m / m_per_px)
    if bar_px < 30:
        return img
    label = f"{nice_m/1000:g} km" if nice_m >= 1000 else f"{int(nice_m)} m"

    d = ImageDraw.Draw(img)
    font = _load_font(bold=True, size=13)
    try:
        bb = d.textbbox((0, 0), label, font=font)
        lw, lh = bb[2] - bb[0], bb[3] - bb[1]
    except AttributeError:
        lw, lh = len(label) * 8, 14

    pad = 8
    block_w = max(bar_px, lw) + pad * 2
    block_h = lh + 12 + pad * 2
    bx = (W - block_w) // 2
    by = H - block_h - 16
    d.rounded_rectangle([bx, by, bx + block_w, by + block_h], radius=6, fill=(10, 12, 22, 200))
    # bar with end ticks
    bar_y = by + block_h - pad - 4
    bar_x0 = bx + (block_w - bar_px) // 2
    bar_x1 = bar_x0 + bar_px
    d.line([(bar_x0, bar_y), (bar_x1, bar_y)], fill=(255, 255, 255), width=2)
    d.line([(bar_x0, bar_y - 5), (bar_x0, bar_y + 1)], fill=(255, 255, 255), width=2)
    d.line([(bar_x1, bar_y - 5), (bar_x1, bar_y + 1)], fill=(255, 255, 255), width=2)
    d.text((bx + (block_w - lw) // 2, by + pad), label, font=font, fill=(255, 255, 255))
    return img


def _draw_pin_icon(d, cx, cy, R, cyan=(0, 229, 255), dark=(10, 14, 22)):
    """Draw the Stadiums of Europe map-pin mark (pin holding a top-down pitch)
    onto ImageDraw d, centred horizontally at cx with the pin head at cy."""
    # Pin head (filled) + tail triangle
    d.ellipse([cx - R, cy - R, cx + R, cy + R], fill=cyan)
    tw = R * 0.74
    d.polygon([(cx - tw, cy + R * 0.60), (cx + tw, cy + R * 0.60), (cx, cy + R + R * 0.85)], fill=cyan)
    # Dark inset + cyan pitch (ellipse, halfway line, centre circle)
    orx, ory = R * 0.68, R * 0.46
    d.ellipse([cx - orx, cy - ory, cx + orx, cy + ory], fill=dark)
    prx, pry = R * 0.56, R * 0.34
    lw = max(1, int(R * 0.10))
    d.ellipse([cx - prx, cy - pry, cx + prx, cy + pry], outline=cyan, width=lw)
    d.line([(cx, cy - pry), (cx, cy + pry)], fill=cyan, width=lw)
    cr = R * 0.16
    d.ellipse([cx - cr, cy - cr, cx + cr, cy + cr], outline=cyan, width=lw)


def _logo_metrics(W, H):
    """Geometry of the bottom-right logo lockup — shared by the drawing code and
    the label-reservation so labels never land on the watermark."""
    R = 12
    font = _load_font(bold=True, size=20)
    text = "stadiumsofeurope.com"
    tmp = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    try:
        bb = tmp.textbbox((0, 0), text, font=font)
        tw, th = bb[2] - bb[0], bb[3] - bb[1]
    except AttributeError:
        tw, th = len(text) * 11, 20
    PAD, GAP = 12, 12
    icon_w = R * 2
    pill_h = int(R * 2 + R * 0.85 + PAD * 2)
    pill_w = PAD + icon_w + GAP + tw + PAD
    margin = 8                                          # tight into the corner
    lx, ly = W - pill_w - margin, H - pill_h - margin
    return dict(R=R, font=font, text=text, th=th, PAD=PAD, GAP=GAP,
                icon_w=icon_w, pill_w=pill_w, pill_h=pill_h, lx=lx, ly=ly)


def _logo_box(W, H):
    m = _logo_metrics(W, H)
    return (m["lx"] - 6, m["ly"] - 6, W, H)


def _draw_logo(img, W, H):
    """Stamp the pin mark + 'stadiumsofeurope.com' wordmark in the BOTTOM-RIGHT
    corner (Transfermarkt-style), on a translucent pill so it reads over any map."""
    m = _logo_metrics(W, H)
    tile = Image.new("RGBA", (m["pill_w"], m["pill_h"]), (0, 0, 0, 0))
    td = ImageDraw.Draw(tile)
    td.rounded_rectangle([0, 0, m["pill_w"] - 1, m["pill_h"] - 1], radius=12, fill=(9, 12, 20, 180))
    _draw_pin_icon(td, m["PAD"] + m["R"], m["PAD"] + m["R"], m["R"])
    ty = (m["pill_h"] - m["th"]) // 2 - 2
    td.text((m["PAD"] + m["icon_w"] + m["GAP"], ty), m["text"], font=m["font"], fill=(255, 255, 255))
    region = img.crop((m["lx"], m["ly"], m["lx"] + m["pill_w"], m["ly"] + m["pill_h"]))
    region = Image.alpha_composite(region, tile)
    img.paste(region, (m["lx"], m["ly"]))
    return img


def _draw_watermark(img, W, H, text="stadiumsofeurope.com", text_alpha=95, gap=70):
    """Tile a diagonal translucent watermark across the WHOLE image, baked into
    the pixels. Used subtly for the free (branded) download and more strongly for
    the in-page preview. A dark outline keeps it legible on satellite + dark."""
    font = _load_font(bold=True, size=max(24, int(min(W, H) * 0.04)))
    tmp = ImageDraw.Draw(img)
    try:
        bb = tmp.textbbox((0, 0), text, font=font)
        tw, th = bb[2] - bb[0], bb[3] - bb[1]
    except AttributeError:
        tw, th = len(text) * 16, 30
    stamp = Image.new("RGBA", (tw + 28, th + 28), (0, 0, 0, 0))
    sd = ImageDraw.Draw(stamp)
    out_alpha = min(140, int(text_alpha * 0.8))
    for ox, oy in ((-2, 0), (2, 0), (0, -2), (0, 2)):
        sd.text((14 + ox, 14 + oy), text, font=font, fill=(0, 0, 0, out_alpha))
    sd.text((14, 14), text, font=font, fill=(255, 255, 255, text_alpha))
    stamp = stamp.rotate(30, expand=True, resample=Image.BICUBIC)
    sw, sh = stamp.size
    step_x, step_y = sw + gap, sh + gap + 20
    row = 0
    y = -sh
    while y < H + sh:
        x = -sw + (row % 2) * (step_x // 2)
        while x < W + sw:
            img.alpha_composite(stamp, (int(x), int(y)))
            x += step_x
        y += step_y
        row += 1
    return img


# Only ONE map render may run at a time per worker process. Each render allocates
# tens of MB of PIL buffers; with --threads >1 (or multiple workers), simultaneous
# renders stack and OOM-kill the 512 MB Render dyno → HTTP 502. Serializing them
# caps peak memory to a single render regardless of concurrency.
_RENDER_LOCK = _threading.BoundedSemaphore(1)


def _compose_export_image(params):
    """Shared render core for both the free preview and the paid download.
    Returns (PIL RGBA Image, None) or (None, error_message).

    The map fills the whole canvas. When a title is set, its area is reserved so
    no LABEL is placed under it, then the title/subtitle are drawn in a
    TRANSLUCENT box on top — the map shows through, nothing is lost.
    """
    if params.get("layer") == "development":
        stadiums = _get_development_export_stadiums(params)
        params["color_by"] = "dev_status"          # colour points by project status
        if not stadiums:
            return None, "No development projects match the selected statuses."
    elif params.get("tournament"):
        stadiums = _get_tournament_export_stadiums(params)
        # Competing-bid tournaments (Euro 2036) colour by bid; otherwise by venue status.
        params["color_by"] = "bid" if any(s.get("bid") for s in stadiums) else "tournament_status"
        if not stadiums:
            return None, "No venues match the selected tournament/status."
    else:
        stadiums = _get_export_stadiums(params)
        if not stadiums:
            return None, "No stadiums match the selected filters."

    W, H = params["W"], params["H"]
    main_stadiums, inset_stadiums = _split_main_inset(stadiums)
    # Broad, unfiltered Europe export: trim longitude outliers (Iceland / Ural Russia) so
    # the frame stays on Europe. Filtered exports (country/league/tournament/dev/national)
    # keep the full bbox so they're never cropped.
    is_broad = not (params.get("tournament") or params.get("layer") == "development"
                    or params.get("country") or params.get("league")
                    or params.get("surface") or params.get("ownership")
                    or params.get("national") or params.get("national_only"))
    if is_broad and len(stadiums) > 30:
        raw_bbox = _trimmed_bbox(stadiums)
    else:
        raw_bbox = _bbox_with_padding(main_stadiums if main_stadiums else stadiums)
    bbox = _expand_bbox_to_aspect(raw_bbox, W, H)

    country_index = {}
    for s in stadiums:
        country_index.setdefault(s["country"], len(country_index))

    # R1: real CARTO tiles unless a custom land colour selects the diagram view
    use_tiles = params.get("tiles", True) and not params.get("bg_color")
    img = _make_background(params["style_key"], W, H, bbox,
                           use_tiles=use_tiles, land_color=params.get("bg_color"))

    # Spotlight: dim everything outside the selected country and outline it,
    # so badges/labels (drawn next, on top) stay fully bright.
    if params.get("spotlight"):
        img = _spotlight_country(img, main_stadiums, bbox, W, H)

    # Reserve every overlay area from label placement so labels never land on the
    # title, logo, legend, scale bar, or north arrow. Map tiles/badges still
    # render full-canvas underneath these.
    reserves = []
    tlayout = _title_layout(params, W)
    if tlayout:
        M = 8
        reserves.append((tlayout["x0"] - M, tlayout["y0"] - M,
                         tlayout["x0"] + tlayout["w"] + M, tlayout["y0"] + tlayout["h"] + M))
    if params["north"]:
        reserves.append((W - 100, 0, W, 100))                     # top-right
    if params["legend"]:
        reserves.append((0, H - 175, 185, H))                     # bottom-left
    if params.get("scale"):
        reserves.append((W // 2 - 135, H - 80, W // 2 + 135, H))  # bottom-centre
    if params.get("logo"):
        reserves.append(_logo_box(W, H))                          # bottom-right

    img = _draw_dots_and_labels(img, main_stadiums, params, bbox, W, H, country_index,
                                reserve_boxes=reserves)
    if inset_stadiums:
        img = _draw_inset(img, inset_stadiums, params, W, H, country_index, params["style_key"])
    if params["legend"]:
        img = _draw_legend(img, params, stadiums)
    if params["north"]:
        img = _draw_north_arrow(img, W, H)
    if params.get("scale"):
        img = _draw_scale_bar(img, bbox, W, H)
    if params.get("logo"):
        img = _draw_logo(img, W, H)

    if tlayout:
        img = _draw_title_translucent(img, tlayout)

    return img, None


def map_export(request):
    # Light rate-limit: the render lock already bounds memory (one render at a
    # time per worker) and renders take ~2-4s, so a short 3s window is enough to
    # stop rapid-fire spam without making config tweaks feel laggy.
    ip = request.META.get("HTTP_X_FORWARDED_FOR", request.META.get("REMOTE_ADDR", "")).split(",")[0].strip()
    cache_key = f"map_export_ratelimit_{ip}"
    if cache.get(cache_key):
        return JsonResponse({"error": "Please wait a moment before regenerating."}, status=429)
    cache.set(cache_key, True, 3)

    params = _parse_export_params(request)
    # Cap to HD on free tier (512 MB RAM limit — FHD/4K OOM-kills the dyno)
    if params["size_key"] in ("fhd", "4k"):
        params["size_key"] = "hd"
        params["W"], params["H"] = 1280, 720
    log = logging.getLogger(__name__)

    # `tiles=0` forces the flat diagram view even without a custom colour
    if request.GET.get("tiles", "1") == "0":
        params["tiles"] = False

    # Serialize renders to bound peak memory (see _RENDER_LOCK). If the worker is
    # already busy rendering, fail fast with a friendly 429 rather than stacking
    # memory and risking an OOM 502.
    if not _RENDER_LOCK.acquire(timeout=25):
        return JsonResponse({"error": "Server busy rendering another map. Try again in a moment."}, status=429)
    # The PUBLIC endpoint always returns the FREE, branded version: logo on +
    # a baked watermark. The clean (no logo/watermark) version is produced only
    # by the paid path (_render_export_png) after a successful payment, so a clean
    # map can never leak from here.
    params["logo"] = True
    try:
        img, err = _compose_export_image(params)
        if err:
            return JsonResponse({"error": err}, status=400)
        img = _draw_watermark(img, params["W"], params["H"])
        buf = io.BytesIO()
        img.convert("RGB").save(buf, format="PNG", optimize=True)
        buf.seek(0)
    except Exception as e:
        log.error("Export render failed: %s\n%s", e, traceback.format_exc())
        return JsonResponse({"error": "Image render failed.", "detail": str(e)}, status=500)
    finally:
        _RENDER_LOCK.release()

    filename = f"stadiums-map-{params['size_key']}.png"
    response = HttpResponse(buf.read(), content_type="image/png")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    response["Content-Encoding"] = "identity"  # prevent GzipMiddleware from re-encoding PNG
    return response


# ─────────────────────────────────────────────────────────────────────────────
# PAID EXPORT — Stripe pay-per-download
# ─────────────────────────────────────────────────────────────────────────────

EXPORT_PRICE_EUR = 50  # cents (Stripe EUR minimum) — removes watermark + logo


def export_page(request):
    """The /export/ landing page — shows filter UI and watermarked preview."""
    return render(request, "export.html", {
        "stripe_publishable_key": settings.STRIPE_SECRET_KEY.replace("sk_", "pk_") if settings.STRIPE_SECRET_KEY else "",
    })


@require_POST
def export_checkout(request):
    """Create a Stripe Checkout Session and redirect the user to it."""
    if not settings.STRIPE_SECRET_KEY:
        return JsonResponse({"error": "Stripe not configured."}, status=503)

    try:
        body = json.loads(request.body)
    except Exception:
        return JsonResponse({"error": "Invalid JSON."}, status=400)

    # Build filter param string that will be stored and used at download time
    allowed_keys = {
        "country", "league", "ownership", "surface", "type",
        "color_by", "style_key", "size_key", "title", "subtitle", "labels",
        "north", "legend", "scale", "spotlight", "logo", "bg_color",
        "label_size", "label_color", "badge_size", "tournament", "tstatus",
        "layer", "dstatus", "national",
    }
    filters = {k: v for k, v in body.items() if k in allowed_keys}
    filters_json = json.dumps(filters)

    stripe.api_key = settings.STRIPE_SECRET_KEY
    base_url = settings.EXPORT_BASE_URL.rstrip("/")

    try:
        session = stripe.checkout.Session.create(
            payment_method_types=["card"],
            line_items=[{
                "price_data": {
                    "currency": "eur",
                    "unit_amount": EXPORT_PRICE_EUR,
                    "product_data": {
                        "name": "Stadium map — clean version",
                        "description": "Removes the watermark + logo. Supports the site. Single use.",
                    },
                },
                "quantity": 1,
            }],
            mode="payment",
            success_url=base_url + "/export/success/?session_id={CHECKOUT_SESSION_ID}",
            cancel_url=base_url + "/export/",
            metadata={"filters_json": filters_json[:500]},  # Stripe metadata limit 500 chars
        )
    except stripe.StripeError as e:
        return JsonResponse({"error": str(e)}, status=502)

    # Persist token — paid=False until webhook confirms. If this write fails,
    # export_success recreates it from the Stripe session metadata as a fallback.
    try:
        ExportToken.objects.create(
            stripe_session=session.id,
            filters_json=filters_json,
            paid=False,
            expires_at=timezone.now() + timedelta(hours=24),
        )
    except Exception as e:
        logging.getLogger(__name__).error(
            "export_checkout: token create failed for %s: %s", session.id, e)

    return JsonResponse({"checkout_url": session.url})


@csrf_exempt
@require_POST
def export_webhook(request):
    """Stripe webhook — reliable second confirmation path. On
    checkout.session.completed it marks the token paid, and UPSERTS it (creates
    from session metadata) if the checkout-time write was lost, so the download
    works even if the success page never loaded."""
    log = logging.getLogger(__name__)
    payload = request.body
    sig    = request.META.get("HTTP_STRIPE_SIGNATURE", "")
    secret = settings.STRIPE_WEBHOOK_SECRET

    if not secret:
        log.error("export_webhook: STRIPE_WEBHOOK_SECRET not set — ignoring event")
        return HttpResponse(status=400)

    stripe.api_key = settings.STRIPE_SECRET_KEY
    try:
        event = stripe.Webhook.construct_event(payload, sig, secret)
    except (ValueError, stripe.SignatureVerificationError) as e:
        log.error("export_webhook: signature/parse failed: %s", e)
        return HttpResponse(status=400)

    if event["type"] == "checkout.session.completed":
        obj = event["data"]["object"]
        session_id = obj["id"]
        updated = ExportToken.objects.filter(stripe_session=session_id).update(paid=True)
        if not updated:
            # Token row missing (checkout write lost) — recreate it from metadata
            filters_json = (obj.get("metadata") or {}).get("filters_json", "{}")
            ExportToken.objects.create(
                stripe_session=session_id,
                filters_json=filters_json,
                paid=True,
                expires_at=timezone.now() + timedelta(hours=24),
            )
            log.warning("export_webhook: recreated missing token for %s", session_id)

    return HttpResponse(status=200)


@require_GET
def export_success(request):
    """Redirect from Stripe success URL — find or create token, show download page."""
    log = logging.getLogger(__name__)
    session_id = request.GET.get("session_id", "")
    if not session_id:
        return redirect("italiastadiaapp:export_page")

    stripe.api_key = settings.STRIPE_SECRET_KEY

    # 1) The token is normally created at checkout time. Look it up first — this
    #    does NOT depend on Stripe being reachable.
    token_obj = ExportToken.objects.filter(stripe_session=session_id).first()

    # 2) Verify payment with Stripe directly (webhook may not have fired). Retry a
    #    couple of times — a transient failure (e.g. during a deploy) must not turn
    #    a real payment into "Session not found".
    stripe_session = None
    last_err = None
    for attempt in range(3):
        try:
            stripe_session = stripe.checkout.Session.retrieve(session_id)
            break
        except Exception as e:
            last_err = e
            _time.sleep(0.6 * (attempt + 1))
    if stripe_session is None:
        log.error("export_success: Stripe retrieve failed for %s: %s", session_id, last_err)

    # 3) If the token row is missing (e.g. checkout DB write was interrupted by a
    #    deploy), recreate it from the Stripe session metadata.
    if token_obj is None and stripe_session is not None:
        filters_json = (stripe_session.metadata or {}).get("filters_json", "{}")
        token_obj = ExportToken.objects.create(
            stripe_session=session_id,
            filters_json=filters_json,
            paid=(stripe_session.payment_status == "paid"),
            expires_at=timezone.now() + timedelta(hours=24),
        )
        log.warning("export_success: recreated missing token for %s", session_id)

    if token_obj is None:
        log.error("export_success: token missing AND Stripe unreachable for %s", session_id)
        return render(request, "export_error.html", {
            "msg": "We couldn't verify your session just now. Your payment is safe — "
                   "please refresh in a few seconds, or contact support with your Stripe receipt."
        })

    # Sync paid status from Stripe if the webhook was delayed
    if not token_obj.paid and stripe_session is not None and stripe_session.payment_status == "paid":
        token_obj.paid = True
        token_obj.save(update_fields=["paid"])

    if not token_obj.paid:
        return render(request, "export_error.html", {
            "msg": "Payment not confirmed yet — please wait a few seconds and refresh this page."
        })

    return render(request, "export_success.html", {"token": str(token_obj.token)})


def _render_export_png(token_obj):
    """Generate the PNG for an ExportToken and return raw bytes."""
    filters = json.loads(token_obj.filters_json)
    if filters.get("size_key") == "4k":
        filters["size_key"] = "hd"   # cap to HD — free tier 512 MB RAM limit

    class _FakeGET:
        def get(self, key, default=""):
            return filters.get(key, default)

    class _FakeRequest:
        GET = _FakeGET()

    params = _parse_export_params(_FakeRequest())
    params["logo"] = False   # paid version is CLEAN — no logo, no watermark
    # Serialize with previews to bound peak memory (see _RENDER_LOCK)
    _RENDER_LOCK.acquire()
    try:
        img, err = _compose_export_image(params)
        if err:
            return None, err
        buf = io.BytesIO()
        img.convert("RGB").save(buf, format="PNG", optimize=True)
    finally:
        _RENDER_LOCK.release()
    return buf.getvalue(), None


@require_GET
def export_download(request, token):
    """Validate token → generate PNG → email it to the buyer → mark used."""
    try:
        token_uuid = uuid.UUID(str(token))
    except ValueError:
        raise Http404

    try:
        token_obj = ExportToken.objects.get(token=token_uuid)
    except ExportToken.DoesNotExist:
        raise Http404

    already_used_msg = ("This download link has already been used. Check your email — "
                        "the map was sent after your first click.")
    if not token_obj.paid:
        return render(request, "export_error.html", {"msg": "Payment not confirmed."}, status=402)
    if token_obj.used:
        return render(request, "export_error.html", {"msg": already_used_msg}, status=410)
    if timezone.now() > token_obj.expires_at:
        return render(request, "export_error.html", {"msg": "This download link has expired."}, status=410)

    # Atomically CLAIM the single-use token: only one concurrent request can flip
    # used False→True, so a double-click can't generate/email the map twice.
    claimed = ExportToken.objects.filter(
        token=token_uuid, paid=True, used=False
    ).update(used=True)
    if not claimed:
        return render(request, "export_error.html", {"msg": already_used_msg}, status=410)

    # Get buyer email from Stripe
    buyer_email = ""
    stripe.api_key = settings.STRIPE_SECRET_KEY
    try:
        session = stripe.checkout.Session.retrieve(token_obj.stripe_session)
        buyer_email = session.customer_details.email or ""
    except Exception:
        pass

    # Generate PNG. If it fails, RELEASE the claim so the buyer can retry.
    png_bytes, err = _render_export_png(token_obj)
    if err:
        ExportToken.objects.filter(token=token_uuid).update(used=False)
        return render(request, "export_error.html", {"msg": err})

    # Email PNG to buyer
    filename = "stadiums-of-europe-map.png"
    if buyer_email:
        try:
            mail = EmailMessage(
                subject="Your Stadiums of Europe Map",
                body=(
                    "Hi,\n\nThank you for your purchase!\n\n"
                    "Your map is attached to this email as a high-resolution PNG.\n\n"
                    "— Stadiums of Europe\n"
                    "stadiumsofeurope.com"
                ),
                from_email=settings.DEFAULT_FROM_EMAIL,
                to=[buyer_email],
            )
            mail.attach(filename, png_bytes, "image/png")
            mail.send(fail_silently=True)
        except Exception:
            pass

    # Also return the file directly in the response
    response = HttpResponse(png_bytes, content_type="image/png")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    response["Content-Encoding"] = "identity"
    return response


@require_GET
def export_options(request):
    """Return available countries and leagues for autocomplete on the export page.

    The export filters match country on `city.country` (free text) and league on
    `teams.league.name`, so leagues_by_country MUST be keyed by `city.country`
    (NOT the Country model name) or selections like 'Czech Republic' won't line
    up with the league grouping.
    """
    countries = (
        City.objects.exclude(country="")
        .values_list("country", flat=True)
        .distinct()
        .order_by("country")
    )

    # Map city.country → leagues whose teams play at stadiums in that country,
    # mirroring the actual export filter relationship.
    rows = (
        Team.objects
        .exclude(league__isnull=True)
        .exclude(is_national=True)            # national sides aren't a selectable league
        .exclude(stadium__city__country="")
        .values_list("stadium__city__country", "league__name")
        .distinct()
    )
    leagues_by_country = {}
    leagues_set = set()
    for country, league_name in rows:
        if not country or not league_name:
            continue
        leagues_set.add(league_name)
        leagues_by_country.setdefault(country, [])
        if league_name not in leagues_by_country[country]:
            leagues_by_country[country].append(league_name)
    for c in leagues_by_country:
        leagues_by_country[c].sort()

    # Tournaments present in the data (Stadium + StadiumDevelopment tournaments JSON)
    tour_map = {}   # slug -> label
    for obj in list(Stadium.objects.exclude(tournaments=[]).only("tournaments")) + \
               list(StadiumDevelopment.objects.exclude(tournaments=[]).only("tournaments")):
        for entry in (obj.tournaments or []):
            nm = entry.get("tournament", "")
            if nm:
                tour_map.setdefault(slugify(nm), nm)
    tournaments = [{"slug": s, "label": tour_map[s]} for s in sorted(tour_map, key=lambda k: tour_map[k])]

    return JsonResponse({
        "countries":          list(countries),
        "leagues":            sorted(leagues_set),
        "leagues_by_country": leagues_by_country,
        "tournaments":        tournaments,
        "dev_statuses": [
            {"value": s, "label": _DEV_STATUS_LABEL[s]} for s in _DEV_STATUSES
        ],
    })
