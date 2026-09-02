import csv
import hashlib
import io
import base64
import json
import logging
import math
import os as _os
import re
import threading as _threading
from urllib.parse import urlparse as _urlparse
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
from django.views.decorators.clickjacking import xframe_options_exempt
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


# Old slugs Google still requests (GSC 404 report) whose record was renamed, merged,
# or replaced by the club's current ground. 301 preserves any link value; slugs with
# NO successor stay honest 404s and drop out of the report on their own.
_LEGACY_STADIUM_SLUGS = {
    "lambhagavollur": "lambhagavollurinn",          # renamed (Icelandic definite article)
    "bashkimi-stadium-2": "bashkimi-stadium",       # duplicate record merged
    "milsami-stadium": "csr-orhei",                 # FC Milsami Orhei's current ground record
    "sportpark-skoatterwald": "abe-lenstra-stadion",  # SC Heerenveen's actual stadium
}


def stadium_detail(request, slug):
    if slug in _LEGACY_STADIUM_SLUGS:
        return redirect("italiastadiaapp:stadium_detail",
                        slug=_LEGACY_STADIUM_SLUGS[slug], permanent=True)
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

    # Match stadiums by the city's country OR by the country of any tenant's league , 
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
    # Full list (largest first) for the hub, every ground is an internal link.
    all_stadiums = list(stadiums.order_by(
        F("capacity").desc(nulls_last=True), "name"))
    top10 = [s for s in all_stadiums if s.capacity][:10]
    biggest = top10[0] if top10 else None
    leagues = (
        League.objects.select_related("country")
        .filter(country__name__iexact=name, hidden=False).order_by("division_level")
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


@cache_page(60 * 60)  # 1-hour cache, data changes only when scraper runs
def stadiums_geojson(request):
    """
    GeoJSON endpoint for operational stadiums (server-side filtered queries).

    Optional query parameters (all case-sensitive):
      ?country=Italy         , include only stadiums whose teams play in that country
      ?league=Serie+A        , include only stadiums whose teams play in that league
      ?ownership=PUBLIC      , include only stadiums with that ownership value

    map.js does NOT call this endpoint for the initial map load, it fetches
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
    # Insight views (see /insights/), preset filters reused by the shared insights map JS.
    if param_view == "national":
        # Any ground that hosts a national side (a country's national stadium, even if a
        # club also plays there, e.g. Johan Cruijff ArenA, Rajko Mitić).
        qs = qs.filter(teams__is_national=True).distinct()
    elif param_view == "surface":
        qs = qs.exclude(surface__isnull=True).exclude(surface="")
    elif param_view == "capacity":
        qs = qs.exclude(capacity__isnull=True).exclude(capacity=0)
    elif param_view == "retractable":
        qs = qs.filter(stadium_type="RETRACTABLE")

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


def _map_version():
    p = Path(__file__).parent / "static" / "data" / "stadiums_map.json"
    try:
        return int(p.stat().st_mtime)
    except OSError:
        return 0


_ASSET_V_CACHE = {}

def asset_version(request):
    """Context processor: `asset_v` = newest mtime across static/js, so templates
    can cache-bust script tags with `?v={{ asset_v }}`. Without this the browser
    keeps serving a stale map.js/insights-map.js and JS changes look 'not done'.
    Recomputed live in DEBUG; cached once in prod."""
    if not settings.DEBUG and "v" in _ASSET_V_CACHE:
        return {"asset_v": _ASSET_V_CACHE["v"]}
    js_dir = Path(__file__).parent / "static" / "js"
    try:
        v = int(max(f.stat().st_mtime for f in js_dir.glob("*.js")))
    except (OSError, ValueError):
        v = 0
    _ASSET_V_CACHE["v"] = v
    return {"asset_v": v}


@xframe_options_exempt
@cache_page(60 * 60)
def embed_map(request):
    """Minimal, chrome-free map for embedding on other sites via <iframe>. Each embed is
    a backlink + referral funnel (the attribution link and marker popups point back here)."""
    return render(request, "embed_map.html", {"map_version": _map_version()})


@cache_page(60 * 60)
def map_page(request):
    """Dedicated, clean interactive-map landing page at /map — a stable, descriptive URL
    suitable for linking as an external source (e.g. from Wikipedia)."""
    return render(request, "map_page.html", {"map_version": _map_version()})


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
    city_query = request.GET.get("q", "").strip()
    qs = City.objects.prefetch_related("teams").order_by("-population", "name")
    if selected_country:
        qs = qs.filter(country=selected_country)
    if city_query:
        qs = qs.filter(name__icontains=city_query)
    return render(request, "city_list.html", {
        "cities": qs,
        "countries": _available_countries(),
        "selected_country": selected_country,
        "city_query": city_query,
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

    # Build ordered list of leagues to use as sections, ranked countries first,
    # unranked countries last (nulls_last), then alphabetically within each group.
    leagues_qs = League.objects.select_related("country").filter(hidden=False).order_by(
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
    # Internal linking: other clubs in the same city + same league (boosts crawl
    # depth / topical authority — see GROWTH_PLAN.md indexing pillar).
    same_city = (Team.objects.filter(city=team.city).exclude(id=team.id)
                 .select_related("stadium")[:8]) if team.city else []
    same_league = (Team.objects.filter(league=team.league).exclude(id=team.id)
                   .select_related("stadium")[:8]) if team.league else []
    country_name = (team.league.country.name if team.league and team.league.country
                    else (team.city.country if team.city else ""))
    return render(request, "team_detail.html", {
        "team": team,
        "from_list": from_list is not None,
        "back_country": back_country,
        "same_city_clubs": same_city,
        "same_league_clubs": same_league,
        "related_country": country_name,
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

    leagues_qs = League.objects.select_related("country").filter(hidden=False).order_by(
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
    "capacity", "surface", "ownership", "owner_raw",
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
        "surface": stadium.get_surface_display() if stadium.surface else "",
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


def about(request):
    return render(request, "about.html", {
        "adsense_client": settings.GOOGLE_ADSENSE_CLIENT,
    })


def contact(request):
    return render(request, "contact.html", {
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
                    "badge_url": "",   # future venue, no club crest, drawn as a status dot
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
            "merely hypothetical, UEFA president Aleksander Čeferin has publicly warned that "
            "Italy risks being removed as co-host if its infrastructure plans do not progress.",
            "The Italian race entered its decisive phase on 31 July 2026, the FIGC's deadline "
            "for candidate cities to deliver their dossiers (approved projects, financial "
            "guarantees and proof of UEFA compliance). On 1 August the federation confirmed "
            "what it had received: <strong>13 cities putting forward 16 stadiums</strong>. The "
            "cities are Bari, Bologna, Cagliari, Florence, Genoa, Lecce, Milan, Naples, "
            "Palermo, Rome, Salerno, Turin and Verona; Udine and Reggio Emilia, both mentioned "
            "earlier in the process, did not file.",
            "The count reaches 16 because two cities entered more than one project. Rome "
            "submitted three: the existing Stadio Olimpico, the new Roma ground planned for "
            "Pietralata, and the Stadio Flaminio, Pier Luigi Nervi's derelict 1959 arena, "
            "which Lazio propose to restore and expand to 50,750 seats. Naples submitted two "
            "competing visions: the city council's publicly funded renovation of the Stadio "
            "Diego Armando Maradona, and a privately financed new build pushed by club "
            "president Aurelio De Laurentiis on the former Q8 refinery site at San Giovanni a "
            "Teduccio in the east of the city.",
            "The FIGC will shortlist five stadiums, plus reserves, by mid-September, and UEFA "
            "is expected to ratify the final Italian five in the first week of October 2026. "
            "Of the sixteen, only Turin's Allianz Stadium is tournament-ready today; every "
            "other candidacy depends on a renovation or a new build being delivered on time.",
        ],
        "sources": [
            {"label": "La Gazzetta dello Sport, Euro 2032: which stadiums will host the tournament",
             "url": "https://www.gazzetta.it/Calcio/Europei/31-07-2026/euro-2032-quali-stadi-ospiteranno-il-torneo.shtml"},
            {"label": "Calcio e Finanza, Florence files its official Euro 2032 candidacy (31 July 2026)",
             "url": "https://www.calcioefinanza.it/2026/07/31/candidatura-ufficiale-stadio-franchi-euro-2032/"},
            {"label": "Calcio e Finanza, Italy–Turkey joint candidacy for Euro 2032",
             "url": "https://www.calcioefinanza.it/2023/07/28/gravina-candidatura-italia-turchia-per-euro-2032-svolta-storica/"},
            {"label": "Football Italia, Gravina on Italy, Euro 2032 and Turkey",
             "url": "https://football-italia.net/gravina-italy-lost-euro-2032-turkey-mancini/"},
            {"label": "Reuters, Čeferin threatens to remove Italy as Euro 2032 co-host over infrastructure",
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
             "Each host country will provide five stadiums, ten in total. Both federations "
             "are narrowing longer candidate lists; the final venues are expected to be "
             "ratified by UEFA in early October 2026."),
            ("Which Italian cities are candidates for Euro 2032?",
             "Thirteen cities delivered dossiers to the FIGC by the 31 July 2026 deadline, "
             "covering 16 stadiums: Bari, Bologna, Cagliari, Florence, Genoa, Lecce, Milan, "
             "Naples, Palermo, Rome, Salerno, Turin and Verona. Rome entered three projects "
             "and Naples two. Five will be chosen, with reserves."),
            ("Why are there 16 stadiums but only 13 candidate cities?",
             "Rome submitted three dossiers, the Stadio Olimpico, the new Roma stadium at "
             "Pietralata and a restored Stadio Flaminio, and Naples two, the municipal "
             "renovation of the Stadio Maradona and a privately funded new stadium on the "
             "former Q8 refinery site at San Giovanni a Teduccio."),
            ("Which Italian stadium is ready for Euro 2032 today?",
             "Only Turin's Allianz Stadium currently meets UEFA requirements without further "
             "work; all other Italian candidacies rely on renovations or new builds."),
        ],
    },
    "champions-league-final": {
        "heading": "Champions League final venues, 2026–2030",
        "paragraphs": [
            "Unlike a Euro, the UEFA Champions League final is played at a single, different "
            "stadium every year, chosen by UEFA's Executive Committee a few seasons in advance. "
            "This page maps the venues for the upcoming finals, those already confirmed and "
            "those still being decided between rival candidate cities.",
            "The 2026 final is confirmed for the Puskás Aréna in Budapest, and the 2027 final "
            "for the Estadio Metropolitano (Riyadh Air Metropolitano) in Madrid. The 2028 final "
            "is expected to head to Munich's Allianz Arena, while 2029 is a contest between "
            "London's Wembley Stadium and Barcelona's Camp Nou. The 2030 host has not yet been "
            "announced, bids are still open.",
            "Final proposals for the 2028 and 2029 editions were submitted in mid-2026, with "
            "UEFA's host appointments expected to follow. We will update the map as each "
            "decision is confirmed.",
        ],
        "sources": [
            {"label": "Footbeen, Champions League final venues 2026–2030",
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

    # Bid grouping, for tournaments with competing bids (e.g. Euro 2036). Auto-
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
        # Fixed running order (Poland leads, strongest chances), then by size.
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
                "is_development": v.get("is_development", False),
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
    # Original prose description, used both as a visible on-page intro (good for
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
        "capacity tiers, at least 3 of 50,000–60,000+ seats (for the opening match, "
        "semi-finals and final), 4 of at least 40,000 and 3 of at least 30,000."
    )
    if has_bids:
        # Competing-bids tournament (host not yet chosen).
        intro_parts.append(
            f"{tournament_name} does not yet have a host nation, several rival bids are "
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

        # Standing editorial on the joint-bid trend, long-form, data-aware (the
        # tournament pages are the site's top traffic, so this is worth the words).
        joint = [b for b in bids if b["is_joint"]]
        solo = [b for b in bids if not b["is_joint"]]
        bid_analysis = (
            "The joint, multi-country bid is fast becoming the norm for the European "
            "Championship. Rather than carrying the cost, security and infrastructure "
            "demands alone, national federations are teaming up to spread the financial "
            "risk, pool a wider set of world-class stadiums and strengthen both the appeal "
            "and the likelihood of success of their bid. The last single-nation host was "
            "Germany at UEFA Euro 2024; the next two editions are already co-hosted, Euro "
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
                f"to the tournament, {len(confirmed_venues)} confirmed and "
                f"{len(venues) - len(confirmed_venues)} candidate, mapped with capacities, "
                f"host cities and, where known, how many matches each is set to stage."
            )
        if total_capacity:
            about.append(
                f"Together the confirmed venues seat around {total_capacity:,} spectators.")
        tournament_about = " ".join(about) + req_text
    tournament_intro = " ".join(intro_parts)
    tournament_description = _trim(tournament_intro)

    # UEFA capacity-tier eligibility (Euro hosts must field ~10 grounds: >=3 of 50k+,
    # 4 more of 40k+, 3 more of 30k+ -> cumulative 3 / 7 / 10). Not for competing-bid pages.
    eligibility = None
    if not has_bids:
        cap_v = [v for v in venues if v["status"] != "DISCARDED" and v.get("capacity")]
        for v in cap_v:
            c = v["capacity"]
            v["tier"] = ("60,000+" if c >= 60000 else "50,000+" if c >= 50000
                         else "40,000+" if c >= 40000 else "30,000+" if c >= 30000
                         else "Below 30,000")
        if cap_v:
            def _cnt(th):
                return sum(1 for v in cap_v if v["capacity"] >= th)
            eligibility = {
                "venues": sorted(cap_v, key=lambda v: -(v["capacity"] or 0)),
                "rows": [
                    {"label": "50,000+ seats (opening / semis / final)", "have": _cnt(50000), "need": 3},
                    {"label": "40,000+ seats (cumulative)", "have": _cnt(40000), "need": 7},
                    {"label": "30,000+ seats (cumulative)", "have": _cnt(30000), "need": 10},
                ],
            }
            for r in eligibility["rows"]:
                r["ok"] = r["have"] >= r["need"]

    # Data-aware FAQ (captures "where is <T> / which stadiums / how many / biggest") ,
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
        "eligibility": eligibility,
        "faq": faq,
        "faq_json": json.dumps([{"@type": "Question", "name": f["q"],
                                 "acceptedAnswer": {"@type": "Answer", "text": f["a"]}}
                                for f in faq]),
        "other_tournaments": [t for t in _list_tournaments() if t["slug"] != slug],
    })


# ── Insights (data-story pages: SEO / CTR) ─────────────────────────────────────

# Current dataset season — bump on the August bulk update for the new season.
CURRENT_SEASON = "2026/2027"

_INSIGHTS = [
    {
        "slug": "national-stadiums",
        "icon": "🏟️",
        "accent": "#1d3557,#2a6f97",
        "title": "National stadiums of Europe",
        "blurb": "Each country's main national-team venue, and which are club-free.",
        "url_name": "insight_national",
        "image": "exports/insight_national_card.jpg",
    },
    {
        "slug": "stadium-surfaces",
        "icon": "🌿",
        "accent": "#1b4332,#40916c",
        "title": "Artificial vs natural grass in European stadiums",
        "blurb": "How many grounds use real grass, hybrid pitches or full artificial turf.",
        "url_name": "insight_surface",
        "image": "exports/insight_surface_card.jpg",
    },
    {
        "slug": "stadium-density",
        "icon": "📍",
        "accent": "#3d1e6d,#7b2cbf",
        "title": "Stadium density per population",
        "blurb": "Which countries pack in the most football stadiums per million people.",
        "url_name": "insight_density",
    },
    {
        "slug": "biggest-stadiums",
        "icon": "📏",
        "accent": "#6a2c0f,#c1611f",
        "title": "Biggest & smallest stadiums in Europe",
        "blurb": "The largest football stadiums in Europe by capacity, and the smallest.",
        "url_name": "insight_biggest",
    },
    {
        "slug": "league-capacity",
        "icon": "📊",
        "accent": "#0b3954,#087e8b",
        "title": "Big five leagues: attendance & capacity",
        "blurb": "Average attendance and how full grounds get, plus capacity by league.",
        "url_name": "insight_league_capacity",
    },
    {
        "slug": "clubs-per-city",
        "icon": "🏙️",
        "accent": "#4a1c2e,#a4133c",
        "title": "How many football clubs are in each city?",
        "blurb": "The European cities with the most football clubs, lower tiers included.",
        "url_name": "insight_city_clubs",
    },
    {
        "slug": "retractable-roofs",
        "icon": "🔁",
        "accent": "#2b2d42,#5c677d",
        "title": "Retractable-roof stadiums: Europe vs USA",
        "blurb": "How Europe's retractable-roof grounds compare with the NFL and MLB.",
        "url_name": "insight_retractable_roofs",
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
            "Data insights on European football stadiums, national-team grounds, "
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
        f"Across Europe, <strong>{len(rows)} stadiums</strong> in our dataset host a national "
        f"team, each country's main international venue. <strong>{dedicated}</strong> of them are "
        "used <strong>exclusively</strong> by the national side, while the rest are shared with a "
        f"leading club. Together they seat about <strong>{total_cap:,}</strong> spectators."
    )
    about = (
        "Most countries play their internationals at a stadium that a top club also calls "
        "home, for example the Netherlands at the Johan Cruijff ArenA (Ajax) or Serbia at "
        "the Rajko Mitić Stadium (Red Star). A truly dedicated national ground, used by no "
        "club, is rarer and usually a flagship, Wembley, the Stade de France, the Puskás "
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
        "page_description": _trim(re.sub(r"<[^>]+>", "", intro)),
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
        f"<strong>{pct(counts['GRASS'])}% use natural grass</strong>, "
        f"<strong>{pct(counts['HYBRID'])}%</strong> use a hybrid reinforced pitch and "
        f"<strong>{pct(counts['ARTIFICIAL'])}% are fully artificial</strong>. Artificial "
        "and hybrid surfaces are most common in <strong>colder northern climates</strong> and in "
        "lower divisions, where year-round playability matters more than top-flight regulations."
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
        "out of Europe by Bodø/Glimt, whose synthetic pitch and remarkable home record drew "
        "intense scrutiny, fans and pundits in Italy openly questioned whether UEFA should "
        "ban artificial surfaces in its competitions. So how unusual is Bodø/Glimt's pitch "
        "really? The data is clear: artificial turf is overwhelmingly a Scandinavian "
        "phenomenon, Norway, Finland and Sweden dominate the table below, driven by climate "
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
        "page_description": _trim(re.sub(r"<[^>]+>", "", intro)),
        "hero_image": "exports/insight_surface.png",
    })


@cache_page(60 * 60)
def insight_density(request):
    # TOP-FLIGHT stadiums per million people, by country. Restricting to the top division
    # makes this comparable across countries regardless of how many lower leagues we've
    # scraped, it answers "how many top-tier grounds does a nation support per capita".
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
        "This map ranks European countries by <strong>top-flight football-stadium density</strong>, "
        "the number of first-division grounds per million inhabitants. "
        + (f"<strong>{top['country']}</strong> leads with <strong>{top['per_million']}</strong> "
           f"top-tier stadiums per million people. " if top else "")
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
        "per capita, and Italy's Serie A is at the centre of a long-running debate about "
        "shrinking from 20 clubs to 18, or even 16, to ease fixture congestion, raise quality "
        "and give the national team more rest. England, Spain and Germany have all weighed "
        "similar moves. If Serie A cut to 18, Italy's top-flight density on this map would drop "
        "accordingly, a reminder that these numbers reflect competition design as much as "
        "football culture."
    )
    return render(request, "insight_density.html", {
        "rows": rows, "intro": intro, "about": about, "debate": debate,
        "density_json": json.dumps(density_by_name),
        "others": _insight_others("stadium-density"),
        "page_description": _trim(re.sub(r"<[^>]+>", "", intro)),
    })


_BIG5 = [
    ("Premier League", "England", "https://upload.wikimedia.org/wikipedia/en/f/f2/Premier_League_Logo.svg"),
    ("La Liga", "Spain", "https://upload.wikimedia.org/wikipedia/commons/5/54/LaLiga_EA_Sports_2023_Vertical_Logo.svg"),
    ("Bundesliga", "Germany", "https://upload.wikimedia.org/wikipedia/en/d/df/Bundesliga_logo_%282017%29.svg"),
    ("Serie A", "Italy", "https://upload.wikimedia.org/wikipedia/en/a/ab/Serie_A_ENILIVE_logo.svg"),
    ("Ligue 1", "France", "https://upload.wikimedia.org/wikipedia/commons/7/7b/Logo_Ligue_1_McDonald%27s_2024.svg"),
]


@cache_page(60 * 60)
def insight_league_capacity(request):
    """Big-five attendance vs capacity comparison + average capacity for every league."""
    # All leagues by average stadium capacity (exclude the National Football Team "leagues").
    rows = []
    for l in League.objects.select_related("country").exclude(division_level=0):
        agg = (Stadium.objects.filter(teams__league=l, capacity__gt=0).distinct()
               .aggregate(avg=Avg("capacity"), total=Sum("capacity"), n=Count("id", distinct=True)))
        if not agg["n"]:
            continue
        rows.append({
            "league": l.name, "country": l.country.name if l.country else "",
            "division": l.division_level, "n": agg["n"],
            "avg": int(agg["avg"] or 0), "total": int(agg["total"] or 0),
        })
    rows.sort(key=lambda r: r["avg"], reverse=True)
    max_avg = rows[0]["avg"] if rows else 1
    for r in rows:
        r["bar"] = round(100 * r["avg"] / max_avg) if max_avg else 0

    # Big five: average attendance, average capacity, and how full grounds get.
    big5 = []
    for name, country, logo in _BIG5:
        l = League.objects.filter(name=name, country__name=country).first()
        if not l:
            continue
        clubs = list(Team.objects.filter(league=l).select_related("stadium"))
        atts = [c.average_attendance for c in clubs if c.average_attendance]
        caps = [c.stadium.capacity for c in clubs if c.stadium and c.stadium.capacity]
        ratios = [c.average_attendance / c.stadium.capacity for c in clubs
                  if c.average_attendance and c.stadium and c.stadium.capacity]
        club_rows = sorted([{
            "name": c.name, "badge": c.image_url or "",
            "stadium": c.stadium.name if c.stadium else "",
            "capacity": c.stadium.capacity if c.stadium else 0,
            "attendance": c.average_attendance or 0,
            "fill": round(100 * c.average_attendance / c.stadium.capacity)
                    if (c.average_attendance and c.stadium and c.stadium.capacity) else 0,
        } for c in clubs], key=lambda x: x["attendance"], reverse=True)
        big5.append({
            "league": name, "country": country, "logo": logo, "clubs": len(clubs),
            "avg_att": int(sum(atts) / len(atts)) if atts else 0,
            "avg_cap": int(sum(caps) / len(caps)) if caps else 0,
            "fill": round(100 * sum(ratios) / len(ratios)) if ratios else 0,
            "club_rows": club_rows,
        })
    big5.sort(key=lambda b: b["avg_att"], reverse=True)
    max_att = max((b["avg_att"] for b in big5), default=1) or 1
    for b in big5:
        b["att_bar"] = round(100 * b["avg_att"] / max_att)
    leader = big5[0] if big5 else None
    fullest = max(big5, key=lambda b: b["fill"]) if big5 else None

    intro_html = (
        "How do Europe's <strong>big five</strong> leagues compare on matchday? This page pits "
        "the <strong>Premier League, La Liga, Bundesliga, Serie A and Ligue 1</strong> on "
        "<strong>average attendance</strong> and how full their grounds get, then ranks every "
        "league by average stadium capacity. "
        + (f"<strong>{leader['league']}</strong> draws the biggest crowds at "
           f"<strong>{leader['avg_att']:,}</strong> per game" if leader else "")
        + (f", while <strong>{fullest['league']}</strong> fills the highest share of its seats "
           f"(<strong>{fullest['fill']}%</strong>)." if fullest else ".")
    )
    about_html = (
        "<strong>Average attendance</strong> is the mean home crowd across every club in the "
        "league; <strong>occupancy</strong> is that attendance as a share of stadium capacity. "
        "A league can pull huge crowds yet still have room to grow, or pack out smaller grounds "
        "week after week."
    )
    plain = re.sub(r"<[^>]+>", "", intro_html)
    faq = []
    if leader:
        faq.append(("Which European league has the highest average attendance?",
                    f"{leader['league']} has the highest average attendance among the big five, "
                    f"at about {leader['avg_att']:,} per match."))
    if fullest:
        faq.append(("Which league fills its stadiums the most?",
                    f"{fullest['league']} has the highest occupancy of the big five, filling "
                    f"about {fullest['fill']}% of available seats on average."))
    if rows:
        faq.append(("Which league has the biggest stadiums in Europe?",
                    f"By average stadium capacity, {rows[0]['league']} ({rows[0]['country']}) "
                    f"leads with about {rows[0]['avg']:,} seats per ground."))
    faq = [{"q": q, "a": a} for q, a in faq]
    return render(request, "insight_league_capacity.html", {
        "rows": rows, "big5": big5, "max_att": max_att,
        "intro_html": intro_html, "about_html": about_html,
        "page_description": _trim(plain),
        "others": _insight_others("league-capacity"),
        "faq": faq,
        "faq_json": json.dumps([{"@type": "Question", "name": f["q"],
                                 "acceptedAnswer": {"@type": "Answer", "text": f["a"]}}
                                for f in faq]),
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
        (f"The biggest football stadium in our European dataset is <strong>{top['name']}</strong> "
         f"in {top['city']}, {top['country']}, holding <strong>{top['capacity']:,}</strong> "
         f"spectators. " if top else "")
        + "This page ranks the <strong>largest football stadiums in Europe</strong> by capacity, "
        "the biggest ground in each country, and the smallest grounds in the dataset, on an "
        "interactive map and in sortable tables."
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
        "page_description": _trim(re.sub(r"<[^>]+>", "", intro)),
    })


def _city_clubs_payload():
    """Load the pre-generated static/data/city_clubs.json (built by the
    generate_city_clubs command on every data load). Cheap file read, no
    per-request DB aggregation."""
    path = (Path(settings.BASE_DIR) / "italiastadiaapp" / "static"
            / "data" / "city_clubs.json")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        version = int(path.stat().st_mtime)
    except (OSError, ValueError):
        data, version = {"season": CURRENT_SEASON, "cities": []}, 0
    return data, version


@cache_page(60 * 60)
def insight_city_clubs(request):
    """Cities ranked by how many football clubs are based there (excluding
    national teams), lower divisions included. Reads a precomputed artifact so
    the request does no heavy aggregation; refreshes whenever data is loaded."""
    data, version = _city_clubs_payload()
    rows = data.get("cities", [])
    season = data.get("season", CURRENT_SEASON)
    top = rows[0] if rows else None

    intro = (
        "Have you ever run into a discussion about how many football clubs are within "
        "<strong>London</strong>? Or <strong>Istanbul</strong>? Here you will get your answer. "
        "We list the clubs within a city, <strong>including the lower tier ones</strong>, so you "
        "can see who was right about it."
    )
    if top:
        _leaders = [c["city"] for c in rows if c["count"] == top["count"]]
        _names = (" and ".join(_leaders) if len(_leaders) <= 2
                  else ", ".join(_leaders[:-1]) + " and " + _leaders[-1])
        if len(_leaders) == 1:
            intro += (f" Right now <strong>{_names}</strong> tops our dataset with "
                      f"<strong>{top['count']}</strong> clubs.")
        else:
            intro += (f" Right now <strong>{_names}</strong> are tied at the top with "
                      f"<strong>{top['count']}</strong> clubs each.")
    about = (
        "Every club is counted against the city it is based in, national teams excluded. "
        "Coverage depth varies by country: the <strong>top five leagues</strong> are covered "
        "down to the <strong>third tier</strong>, the <strong>next ten</strong> down to the "
        "<strong>second tier</strong>, and every other country's <strong>top division</strong>. "
        f"Figures reflect the <strong>{season}</strong> season and refresh with the August update."
    )

    by_city = {r["city"].lower(): r for r in rows}
    def _count_for(city):
        r = by_city.get(city.lower())
        return r["count"] if r else None
    faq = []
    for city_name in ("London", "Istanbul"):
        n = _count_for(city_name)
        if n:
            faq.append((f"How many football clubs are in {city_name}?",
                        f"Our dataset lists {n} football clubs based in {city_name} across the "
                        f"divisions we cover ({season} season). See the table for each club."))
        else:
            faq.append((f"How many football clubs are in {city_name}?",
                        f"We list every club based in {city_name} across the divisions we cover; "
                        f"check the table above for the current {season} count."))
    if top:
        leaders = [c["city"] for c in rows if c["count"] == top["count"]]
        if len(leaders) == 1:
            most_a = (f"In our dataset {leaders[0]} has the most, with {top['count']} clubs "
                      f"({season} season).")
        else:
            most_a = (f"In our dataset {' and '.join([', '.join(leaders[:-1]), leaders[-1]]) if len(leaders) > 2 else ' and '.join(leaders)} "
                      f"are tied for the most, with {top['count']} clubs each ({season} season).")
        faq.append(("Which European city has the most football clubs?", most_a))
    faq.append(("Which leagues and divisions are included?",
                "The top five leagues are covered down to the third tier, the next ten countries "
                "down to the second tier, and every other country's top division. All figures are "
                f"for the {season} season."))
    faq = [{"q": q, "a": a} for q, a in faq]

    return render(request, "insight_city_clubs.html", {
        "rows": rows, "season": season, "data_version": version,
        "intro": intro, "about": about, "faq": faq,
        "faq_json": json.dumps([{"@type": "Question", "name": f["q"],
                                 "acceptedAnswer": {"@type": "Answer", "text": f["a"]}}
                                for f in faq]),
        "others": _insight_others("clubs-per-city"),
        "page_description": _trim(re.sub(r"<[^>]+>", "", intro)),
    })


# Curated list of US retractable-roof stadiums (NFL / MLB) for the Europe-vs-USA
# comparison. The USA leans heavily on retractable roofs (climate extremes +
# multi-purpose franchise economics); Europe's are rarer and football-led.
_US_RETRACTABLE_ROOFS = [
    {"name": "AT&T Stadium", "city": "Arlington, TX", "league": "NFL", "capacity": 80000, "year": 2009},
    {"name": "Mercedes-Benz Stadium", "city": "Atlanta, GA", "league": "NFL", "capacity": 71000, "year": 2017},
    {"name": "NRG Stadium", "city": "Houston, TX", "league": "NFL", "capacity": 72220, "year": 2002},
    {"name": "Lucas Oil Stadium", "city": "Indianapolis, IN", "league": "NFL", "capacity": 67000, "year": 2008},
    {"name": "State Farm Stadium", "city": "Glendale, AZ", "league": "NFL", "capacity": 63400, "year": 2006},
    {"name": "T-Mobile Park", "city": "Seattle, WA", "league": "MLB", "capacity": 47000, "year": 1999},
    {"name": "Chase Field", "city": "Phoenix, AZ", "league": "MLB", "capacity": 48686, "year": 1998},
    {"name": "American Family Field", "city": "Milwaukee, WI", "league": "MLB", "capacity": 41900, "year": 2001},
    {"name": "Daikin Park", "city": "Houston, TX", "league": "MLB", "capacity": 41000, "year": 2000},
    {"name": "Globe Life Field", "city": "Arlington, TX", "league": "MLB", "capacity": 40300, "year": 2020},
    {"name": "loanDepot Park", "city": "Miami, FL", "league": "MLB", "capacity": 36000, "year": 2012},
]


@cache_page(60 * 60)
def insight_retractable_roofs(request):
    """Europe vs USA comparison of retractable-roof stadiums."""
    qs = (Stadium.objects.filter(stadium_type="RETRACTABLE")
          .select_related("city").prefetch_related("teams__league__country")
          .order_by("-capacity"))
    europe = []
    for s in qs:
        teams = [t for t in s.teams.all() if not t.is_national]
        country = next((t.league.country.name for t in s.teams.all()
                        if t.league and t.league.country), s.city.country if s.city else "")
        europe.append({
            "name": s.name, "slug": s.slug, "city": s.city.name if s.city else "",
            "country": country, "capacity": s.capacity,
            "team": ", ".join(t.name for t in teams[:2]),
        })
    usa = sorted(_US_RETRACTABLE_ROOFS, key=lambda r: -r["capacity"])
    n_eu, n_us = len(europe), len(usa)
    intro = (
        f"Retractable roofs let a stadium open to the sky in good weather and seal shut against "
        f"rain, snow or heat. They are a <strong>signature of North American sport</strong>: our "
        f"dataset counts <strong>{n_eu}</strong> across Europe, against a roster of "
        f"<strong>{n_us}+</strong> headline venues in the USA's NFL and MLB alone. This page "
        f"compares the two."
    )
    about = (
        "European retractable roofs are almost all football grounds, often built or upgraded for "
        "a World Cup, Euro or Champions League final, and concentrated in colder or wetter climates "
        "(Germany, the Netherlands, Scandinavia) plus a few showpiece national stadiums. The USA "
        "builds them for a different reason: gridiron and baseball franchises play through brutal "
        "summer heat (Texas, Arizona, Florida) and northern winters (Milwaukee, Seattle), and a "
        "closing roof turns a single venue into a year-round, multi-event business. Counts cover "
        "the leagues in our European dataset versus a curated set of the best-known US venues, so "
        "treat the gap as indicative rather than a full census."
    )
    faq = [
        ("How many stadiums in Europe have a retractable roof?",
         f"Our dataset records {n_eu} European football stadiums with a retractable roof, including "
         f"{', '.join(e['name'] for e in europe[:3])}."),
        ("Why does the USA have more retractable-roof stadiums than Europe?",
         "American football and baseball franchises play in extreme heat (Texas, Arizona, Florida) "
         "and harsh winters, and a retractable roof makes a single arena usable year-round for "
         "sport, concerts and conventions, so the economics favour them far more than in Europe."),
        ("What is the biggest retractable-roof stadium in Europe?",
         (f"{europe[0]['name']} in {europe[0]['city']} ({europe[0]['capacity']:,}) is the largest "
          f"in our dataset." if europe else "Not available.")),
    ]
    faq = [{"q": q, "a": a} for q, a in faq]
    return render(request, "insight_retractable_roofs.html", {
        "europe": europe, "usa": usa, "n_eu": n_eu, "n_us": n_us,
        "intro": intro, "about": about, "faq": faq,
        "faq_json": json.dumps([{"@type": "Question", "name": f["q"],
                                 "acceptedAnswer": {"@type": "Answer", "text": f["a"]}}
                                for f in faq]),
        "geojson_url": reverse("italiastadiaapp:stadiums_geojson") + "?view=retractable",
        "others": _insight_others("retractable-roofs"),
        "page_description": _trim(re.sub(r"<[^>]+>", "", intro)),
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

# Tile servers. CARTO's keyless basemaps are NO LONGER USABLE: they now return a
# perfectly valid PNG with "API KEY REQUIRED / carto.com/basemaps/apikey" stamped
# diagonally across it. HTTP 200, right size, right palette — nothing an error check
# would catch. It reached the LIVE MAP and, worse, the paid PNG export, because the
# /tmp tile cache kept serving clean pre-change tiles locally long after production
# had started stamping them.
#
# dark/light therefore move to Esri's Canvas basemaps, which need no key and come
# from the provider this project already uses for `satellite`. Set CARTO_API_KEY to
# go back to CARTO's styling; the key is appended as a query parameter.
_CARTO_KEY = _os.environ.get("CARTO_API_KEY", "").strip()


def _carto(style):
    return (f"https://a.basemaps.cartocdn.com/{style}/{{z}}/{{x}}/{{y}}.png"
            f"?api_key={_CARTO_KEY}")


_ESRI = "https://services.arcgisonline.com/ArcGIS/rest/services"
_TILE_SERVERS = {
    "dark":      _carto("dark_all") if _CARTO_KEY else
                 f"{_ESRI}/Canvas/World_Dark_Gray_Base/MapServer/tile/{{z}}/{{y}}/{{x}}",
    "light":     _carto("light_all") if _CARTO_KEY else
                 f"{_ESRI}/Canvas/World_Light_Gray_Base/MapServer/tile/{{z}}/{{y}}/{{x}}",
    # OSM is fine, but ONLY with the descriptive User-Agent set in _fetch_tile.
    # A browser-ish UA gets an HTTP 200 carrying an "Access blocked / 418" image
    # instead of a map — another failure that looks like success.
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
# Roof / stadium-type colours for the "color by stadium type" export mode.
_TYPE_COLOURS = {
    "OPEN":        (96, 165, 250),   # sky blue
    "RETRACTABLE": (245, 158, 11),   # amber
    "CLOSED":      (139, 92, 246),   # purple
}
_TYPE_LABELS = {"OPEN": "Open", "RETRACTABLE": "Retractable roof", "CLOSED": "Closed"}
# Ownership colours for the "colour by / ring by ownership" export mode.
_OWNERSHIP_COLOURS = {
    "PUBLIC":  (76, 175, 80),    # green
    "PRIVATE": (231, 76, 60),    # red
    "MIXED":   (255, 159, 28),   # amber
}
_OWNERSHIP_LABELS = {"PUBLIC": "Public", "PRIVATE": "Private", "MIXED": "Mixed"}
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


def _parse_frac4(s):
    """Parse 'fx0,fy0,fx1,fy1' (image fractions 0..1) → (x0,y0,x1,y1) normalised
    so x0<x1, y0<y1; returns None if invalid or degenerate."""
    try:
        v = [float(x) for x in str(s).split(",")]
        if len(v) != 4:
            return None
        v = [min(1.0, max(0.0, x)) for x in v]
        x0, x1 = sorted((v[0], v[2]))
        y0, y1 = sorted((v[1], v[3]))
        if (x1 - x0) < 0.02 or (y1 - y0) < 0.02:   # too tiny → ignore
            return None
        return (x0, y0, x1, y1)
    except (ValueError, TypeError):
        return None


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
    if color_by not in ("surface", "country", "single", "type", "ownership", "uefa"):
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
        "ring_by": request.GET.get("ring_by", "").strip().lower(),
        "single_color": single_color,
        "bg_color": bg_color,
        "label_size": label_size,
        "label_color": label_color,
        "badge_size": badge_size,
        "legend": request.GET.get("legend", "0") == "1",
        "north": request.GET.get("north", "0") == "1",
        "scale": request.GET.get("scale", "0") == "1",
        "spotlight": request.GET.get("spotlight", "0") == "1",
        "inset": "auto" if request.GET.get("inset", "0") == "1" else "",
        # Pull far-flung island groups into their own boxes rather than letting
        # them stretch the frame. On by default; islands=0 forces true extent.
        "islands": request.GET.get("islands", "1") != "0",
        # User-drawn inset rectangle as 4 image fractions "fx0,fy0,fx1,fy1" (0..1).
        # When present it overrides the auto cluster and zooms exactly that area.
        "inset_box": _parse_frac4(request.GET.get("inset_box", "")),
        "labels": request.GET.get("labels", "1") == "1",
        "logo": request.GET.get("logo", "0") == "1",
        "tiles": request.GET.get("tiles", "1") != "0",
        "title":    request.GET.get("title", "").strip()[:80],
        "subtitle": request.GET.get("subtitle", "").strip()[:100],
        # filter params
        "surface":   request.GET.get("surface", "").strip().upper(),
        "stadium_type": request.GET.get("stadium_type", "").strip().upper(),
        "country":   request.GET.get("country", "").strip(),
        "league":    request.GET.get("league", "").strip(),
        "ownership": request.GET.get("ownership", "").strip().upper(),
        "tournament": tournament,
        "tstatus":    tstatus,
        "layer":      layer,
        "dstatus":    dstatus,
        "national":   national,
        "national_only": national_only,
        # Inset box width as a fraction of the map. The old fixed 0.24 left the
        # Istanbul cluster (5 grounds) with labels too cramped to read — the box's
        # fonts and badges are all sized from its width, so widening the box
        # enlarges everything inside it. Default is now M.
        # Which corner the detail box sits in. "auto" scores the four; tl/tr/bl/br
        # let the user override when they can see something the scorer cannot.
        "inset_corner": (request.GET.get("inset_corner", "auto").strip().lower()
                         if request.GET.get("inset_corner", "auto").strip().lower()
                         in ("auto", "tl", "tr", "bl", "br") else "auto"),
        "inset_frac": {"s": 0.24, "m": 0.30, "l": 0.38}.get(
            request.GET.get("inset_size", "m").strip().lower(), 0.30),
        # Hand-placed inset labels from the drag editor, keyed by stadium slug.
        "label_pos": _parse_label_overrides(request.GET.get("label_pos", "")),
        # Disc drawn behind each crest: white (default), black, or none.
        "badge_bg": (request.GET.get("badge_bg", "white").strip().lower()
                     if request.GET.get("badge_bg", "white").strip().lower()
                     in ("white", "black", "none") else "white"),
        # UEFA club competition: UCL / UEL / UECL, or ANY for all three.
        "uefa": (request.GET.get("uefa", "").strip().upper()
                 if request.GET.get("uefa", "").strip().upper()
                 in ("UCL", "UEL", "UECL", "ANY") else ""),
        "no_badges":  request.GET.get("no_badges", "0") == "1",
        "surface_known": request.GET.get("surface_known", "0") == "1",
    }


def _draw_rank(s):
    """Sort key deciding which crest sits on top where grounds overlap.

    Badges are painted in list order, so the LAST one drawn wins the overlap. This
    key sorts ASCENDING, meaning the most important ground ends up last, on top.

    Order is: domestic league titles, then capacity, then name.

    Before this existed the order was raw database insertion order, which in
    Rotterdam put Sparta's badge over Feyenoord's purely because Sparta's row was
    created later — no rule at all, and liable to shift on any re-scrape.

    Capacity is the tie-break rather than a second-order nicety: `num_of_titles` is
    0 for most clubs (about two thirds of the table) both legitimately and, in some
    cases, because the Transfermarkt honours scrape missed them — Ajax carried 0
    despite a record 36 Dutch titles. Capacity is populated everywhere and needs no
    external source, so it does the real work whenever honours are absent or equal.

    Titles are read from the CLUB tenants only. A national side shares the ground
    (Wembley, the Puskás) and carries no domestic league count, so including it
    would drag a major club's ground down to 0.
    """
    clubs = [t for t in s.teams.all() if not t.is_national]
    titles = max((t.num_of_titles or 0) for t in clubs) if clubs else 0
    return (titles, s.capacity or 0, s.name or "")


def _get_export_stadiums(params):
    """Return list of dicts for stadiums matching the filter params."""
    qs = Stadium.objects.select_related("city").prefetch_related("teams__league__country")
    # Multi-select: surface / stadium_type / ownership accept a comma-separated list
    # so users can export two or more categories at once (e.g. PRIVATE + MIXED).
    def _multi(v):
        return [x.strip().upper() for x in str(v or "").split(",") if x.strip()]
    surfaces = _multi(params["surface"])
    if surfaces:
        qs = qs.filter(surface__in=surfaces)
    types = _multi(params.get("stadium_type"))
    if types:
        qs = qs.filter(stadium_type__in=types)
    owns = _multi(params["ownership"])
    if owns:
        qs = qs.filter(ownership__in=owns)
    if params.get("surface_known"):
        qs = qs.exclude(surface__isnull=True).exclude(surface="")
    if params["country"]:
        # Match the interactive map (map.js applyFilters), which treats a country as
        # its LEAGUE SYSTEM, not just its borders. Filtering on the stadium's
        # geographic country alone silently dropped FC Vaduz from a "Switzerland"
        # export: Vaduz plays in the Swiss Super League but sits in Liechtenstein,
        # so the map showed 11 of the league's 12 clubs.
        qs = qs.filter(Q(city__country=params["country"])
                       | Q(teams__league__country__name=params["country"])).distinct()
    if params["league"]:
        qs = qs.filter(teams__league__name=params["league"])
    # Continental maps. This is a property of the CLUB, not of where the ground is, so
    # it COMPOSES with any country/league filter instead of replacing it: "Italy +
    # UEFA=ANY" is every Italian club in Europe, "UEFA=UCL" alone is the whole
    # Champions League league phase across the continent.
    if params.get("uefa"):
        want = params["uefa"]
        qs = (qs.filter(teams__european_competition__in=("UCL", "UEL", "UECL"))
              if want == "ANY" else
              qs.filter(teams__european_competition=want)).distinct()
    if params.get("national"):
        qs = qs.filter(teams__is_national=True)
    if params.get("national_only"):
        qs = qs.annotate(
            _nat=Count("teams", filter=Q(teams__is_national=True), distinct=True),
            _club=Count("teams", filter=Q(teams__is_national=False), distinct=True),
        ).filter(_nat__gte=1, _club=0)
    qs = qs.exclude(latitude=None).exclude(longitude=None).distinct()

    ordered = sorted(qs, key=_draw_rank)

    results = []
    for s in ordered:
        country = s.city.country if s.city else ""
        teams = list(s.teams.all())
        # In national mode, prefer the national side's crest/name as the badge.
        primary_team = None
        if params.get("national") or params.get("national_only"):
            primary_team = next((t for t in teams if t.is_national), None)
        if primary_team is None:
            primary_team = next(iter(teams), None)
        # National sides: use the reliable flagcdn flag (non-free Wikipedia crests
        # often fail the server-side badge fetch, see the live map fix).
        if (primary_team and primary_team.is_national and primary_team.league
                and primary_team.league.country and primary_team.league.country.code):
            image_url = (f"https://flagcdn.com/w160/"
                         f"{_country_flag_code(primary_team.league.country.code)}.png")
        else:
            image_url = (primary_team.image_url or "") if primary_team else ""
        team_name  = (primary_team.name or "") if primary_team else ""
        # Shared grounds (San Siro = Milan + Inter, Mapei = Sassuolo + Reggiana,
        # U-Power = Monza + Inter U23) get a combined badge + a joined label.
        # National mode keeps the single national flag.
        if params.get("national") or params.get("national_only"):
            tenants = [{"name": team_name, "image_url": image_url}] if team_name else []
        else:
            clubs = [t for t in teams if not t.is_national]
            # A LEAGUE filter narrows the tenants too. Genoa and Sampdoria share the
            # Luigi Ferraris, so a Serie B map labelled it "Genoa / UC Sampdoria" and
            # drew a combined crest -- naming a Serie A club on a Serie B map. The
            # groundshare is real; its relevance is not, once you have asked for one
            # division. Fall back to all tenants if the filter would empty the ground,
            # which cannot happen here but would leave a bare dot if it ever did.
            if params.get("league"):
                _in_league = [t for t in clubs
                              if t.league and t.league.name == params["league"]]
                clubs = _in_league or clubs
            # A UEFA filter narrows them for exactly the same reason. Cercle Brugge
            # share the Jan Breydel with Club Brugge and Rukh Lviv share the Arena
            # Lviv with Shakhtar, so a Champions League map labelled those grounds
            # "Cercle Brugge KSV / Club Brugge KV" and "Shakhtar Donetsk / Rukh
            # Lviv" -- naming two clubs that are not in the competition, on a map of
            # that competition. The league filter already had this guard; the UEFA
            # filter was added later and did not.
            if params.get("uefa"):
                _want = ({"UCL", "UEL", "UECL"} if params["uefa"] == "ANY"
                         else {params["uefa"]})
                _in_uefa = [t for t in clubs if t.european_competition in _want]
                clubs = _in_uefa or clubs
            tenants = [{"name": t.name, "image_url": (t.image_url or ""),
                        "crest_file": (t.crest_file or "")} for t in clubs[:4]]
            if not tenants and team_name:
                tenants = [{"name": team_name, "image_url": image_url}]
        label_name = " / ".join(t["name"] for t in tenants[:2]) or team_name
        if params.get("no_badges"):
            image_url = ""   # render colour-coded dots instead of club crests
            tenants = []
        # A ground can host two clubs in different competitions; take the highest
        # (UCL > UEL > UECL) so the marker shows the biggest one played there.
        # Derived from `teams`, NOT from `clubs` -- `clubs` only exists on the
        # non-national branch above, and reading it in national mode raised
        # UnboundLocalError and 500'd the whole export.
        _rank = {"UCL": 0, "UEL": 1, "UECL": 2}
        _euro = sorted((t.european_competition for t in teams
                        if not t.is_national and getattr(t, "european_competition", "")),
                       key=lambda c: _rank.get(c, 9))
        results.append({
            "name":         s.name,
            "slug":         s.slug or "",
            "european_competition": _euro[0] if _euro else "",
            "team_name":    label_name,
            "teams":        tenants,
            "city":         s.city.name if s.city else "",
            "lat":          float(s.latitude),
            "lon":          float(s.longitude),
            "surface":      s.surface or "",
            "stadium_type": s.stadium_type or "",
            "ownership":    s.ownership or "",
            "country":      country,
            "image_url":    image_url,
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


def _label_gutter_bbox(bbox, frac=0.19):
    """Widen the frame so the outer `frac` of each side stays empty of markers.

    Labels are laid out in columns hugging the left/right margins, so if the data
    reaches the edge of the frame (e.g. Italy sitting hard against the left side on
    the Euro 2032 map) the pills land on top of the badges. Reserving a gutter is
    the only fix that always works: no vertical placement can save a pill whose
    column overlaps the badge field. Zooms out slightly; aspect is restored by
    _expand_bbox_to_aspect afterwards."""
    lon_min, lat_min, lon_max, lat_max = bbox
    grow = (lon_max - lon_min) * (frac / max(0.1, 1 - 2 * frac))
    return (lon_min - grow, lat_min, lon_max + grow, lat_max)


def _inset_cluster_bbox(stadiums, pad=0.35, floor=0.008):
    """Tight bounding box for the magnifier's source area.

    _bbox_with_padding enforces a 0.8-degree minimum pad, which is right for a
    country map and catastrophic for a magnifier: two grounds 315 m apart (the
    Dundee pair) came out as a 1.6-degree box roughly 180 km across, so the
    "Detail view" showed coastline instead of the two stadiums it existed to
    separate. Here the pad is proportional to the cluster with a small floor
    (~900 m), so the box actually frames the grounds.
    """
    lats = [s["lat"] for s in stadiums]
    lons = [s["lon"] for s in stadiums]
    lat_min, lat_max = min(lats), max(lats)
    lon_min, lon_max = min(lons), max(lons)
    lat_pad = max((lat_max - lat_min) * pad, floor)
    lon_pad = max((lon_max - lon_min) * pad, floor)
    return (lon_min - lon_pad, lat_min - lat_pad,
            lon_max + lon_pad, lat_max + lat_pad)


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


def _cover_bbox_to_aspect(bbox, W, H):
    """Match the canvas aspect by CROPPING the over-long dimension (zoom in to fill),
    rather than padding the short one. Used for the broad Europe export so the frame
    fills the canvas instead of leaving empty ocean/Asia on the left and right."""
    lon_min, lat_min, lon_max, lat_max = bbox
    merc_span_x = (lon_max - lon_min) / 360.0
    my_n, my_s = _merc_y(lat_max), _merc_y(lat_min)   # north (small) .. south (large)
    merc_span_y = my_s - my_n
    if merc_span_x <= 0 or merc_span_y <= 0:
        return bbox
    natural_aspect = merc_span_x / merc_span_y
    target_aspect = W / H
    if natural_aspect < target_aspect:
        # too tall for the canvas → crop top/bottom (latitude)
        new_span_y = merc_span_x / target_aspect
        mid = (my_n + my_s) / 2
        lat_max = _merc_y_inv(mid - new_span_y / 2)
        lat_min = _merc_y_inv(mid + new_span_y / 2)
    else:
        # too wide → crop east/west (longitude)
        new_span_x_deg = merc_span_y * target_aspect * 360.0
        lon_mid = (lon_min + lon_max) / 2
        lon_min = lon_mid - new_span_x_deg / 2
        lon_max = lon_mid + new_span_x_deg / 2
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


def _auto_inset_cluster(stadiums, max_n=6, bbox=None, W=None, H=None, badge_r=13):
    """Pick the knot of grounds to magnify in the inset.

    The inset exists to rescue grounds you CANNOT READ on the main map, so the
    choice is made on actual badge overlap in pixels, not on how many grounds sit
    inside some lat/lon box. Selecting by member count picked the wrong cluster:
    on a Scotland map it magnified four Glasgow grounds that were already legible
    while leaving Dundee's two (315 m apart, badges completely on top of each
    other) and Edinburgh's pair unreadable.

    Grounds are grouped transitively by whether their badges intersect, and the
    group with the most severe overlap wins. A pair is enough — two badges drawn
    on top of one another is exactly the problem the inset solves.
    """
    if len(stadiums) < 4 or not bbox or not W or not H:
        return _auto_inset_cluster_legacy(stadiums, max_n)

    pts = [(s, *_lon_lat_to_px(s["lon"], s["lat"], bbox, W, H)) for s in stadiums]
    touch = (badge_r + 2) * 2                      # centres closer than this => overlap

    # Union-find over the "badges intersect" relation.
    parent = list(range(len(pts)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    overlaps = 0
    for i in range(len(pts)):
        for j in range(i + 1, len(pts)):
            dx, dy = pts[i][1] - pts[j][1], pts[i][2] - pts[j][2]
            if dx * dx + dy * dy < touch * touch:
                overlaps += 1
                a, b = find(i), find(j)
                if a != b:
                    parent[a] = b
    if not overlaps:
        return []                                   # nothing is unreadable — no inset

    groups = {}
    for idx in range(len(pts)):
        groups.setdefault(find(idx), []).append(idx)

    def severity(idxs):
        """How badly this group needs magnifying: TIGHTNESS first (the closest
        pair), then how many pairs overlap.

        Tightness has to lead. Ranking by pair count picked a loose four-ground
        knot whose badges were still individually readable (Glasgow, closest pair
        13 px) over a pair sitting exactly on top of each other (Dundee's two
        grounds, 315 m apart => 0 px). The unreadable pair is the one that needs
        the magnifier.
        """
        # -inf, NOT 0. Tightness is scored as -closest (a squared pixel distance),
        # so every genuine cluster is NEGATIVE while a lone ground scoring 0 would
        # win max() outright — the function then returned [] and no inset was ever
        # drawn. Any real cluster must outrank an isolated ground.
        if len(idxs) < 2:
            return (float("-inf"), 0)
        pairs, closest = 0, float("inf")
        for a in range(len(idxs)):
            for b in range(a + 1, len(idxs)):
                dx = pts[idxs[a]][1] - pts[idxs[b]][1]
                dy = pts[idxs[a]][2] - pts[idxs[b]][2]
                d2 = dx * dx + dy * dy
                if d2 < touch * touch:
                    pairs += 1
                closest = min(closest, d2)
        return (-closest, pairs)

    best = max(groups.values(), key=severity)
    if len(best) < 2:
        return []
    chosen = [pts[i][0] for i in best]
    if len(chosen) > max_n:
        cx = sum(p[1] for p in pts if p[0] in chosen) / len(chosen)
        cy = sum(p[2] for p in pts if p[0] in chosen) / len(chosen)
        pos = {id(p[0]): (p[1], p[2]) for p in pts}
        chosen = sorted(chosen, key=lambda s: (pos[id(s)][0] - cx) ** 2
                        + (pos[id(s)][1] - cy) ** 2)[:max_n]
    return chosen


def _auto_inset_cluster_legacy(stadiums, max_n=6):
    """Lat/lon fallback used when no frame geometry is available (callers that
    have not yet computed the bbox)."""
    if len(stadiums) < 8:
        return []
    centre, near = None, []
    for c in stadiums:
        grp = [s for s in stadiums
               if abs(s["lat"] - c["lat"]) < 0.18 and abs(s["lon"] - c["lon"]) < 0.28]
        if len(grp) > len(near):
            centre, near = c, grp
    if len(near) < 3:
        return []
    if len(near) > max_n:
        near = sorted(near, key=lambda s: (s["lat"] - centre["lat"]) ** 2
                      + (s["lon"] - centre["lon"]) ** 2)[:max_n]
    return near


def _outlier_island_groups(stadiums, max_groups=2, link_deg=4.0, sep_deg=7.0):
    """Split stadiums into (main_body, [outlier_group, ...]).

    A few far-flung grounds otherwise dictate the whole frame: Portugal's league
    includes the Azores and Madeira, which stretch the bbox ~17 degrees west and
    squeeze mainland Portugal into a sliver against the edge. Those groups are
    better shown in their own inset boxes, the way an atlas handles them.

    Single-linkage clustering: grounds within `link_deg` of each other join the
    same cluster. The largest cluster is the main body; clusters lying more than
    `sep_deg` away from it are returned as outlier groups (largest first, capped
    at `max_groups`). Anything closer than that stays on the main map, so this
    never fires for a merely spread-out country.

    Defaults were tuned against the real dataset: at 4.0/7.0 only Portugal
    triggers (Madeira + the Azores). Looser values wrongly split mainland
    countries - Barcelona and Lecce came out as "islands" at 2.5/4.0.
    """
    if len(stadiums) < 3:
        return stadiums, []

    parent = list(range(len(stadiums)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i in range(len(stadiums)):
        for j in range(i + 1, len(stadiums)):
            dlon = stadiums[i]["lon"] - stadiums[j]["lon"]
            dlat = stadiums[i]["lat"] - stadiums[j]["lat"]
            if (dlon * dlon + dlat * dlat) ** 0.5 <= link_deg:
                a, b = find(i), find(j)
                if a != b:
                    parent[a] = b

    clusters = {}
    for idx in range(len(stadiums)):
        clusters.setdefault(find(idx), []).append(stadiums[idx])
    if len(clusters) < 2:
        return stadiums, []

    ordered = sorted(clusters.values(), key=len, reverse=True)
    main = ordered[0]

    def gap_to_main(group):
        return min(((g["lon"] - m["lon"]) ** 2 + (g["lat"] - m["lat"]) ** 2) ** 0.5
                   for g in group for m in main)

    # An outlier only counts as an ISLAND if it belongs to the same country as the
    # main body. Distance alone is not enough: on the Euro 2032 map Turkey sits
    # ~10 degrees from Italy and was pulled into an "island" box, wrecking a
    # two-country map. Madeira and the Azores are Portugal; Turkey is not Italy.
    main_countries = {s.get("country") for s in main if s.get("country")}

    outliers, kept = [], list(main)
    for grp in ordered[1:]:
        grp_countries = {s.get("country") for s in grp if s.get("country")}
        same_country = bool(grp_countries) and grp_countries <= main_countries
        if same_country and gap_to_main(grp) > sep_deg:
            outliers.append(grp)
        else:
            kept.extend(grp)
    if not outliers:
        return stadiums, []

    outliers.sort(key=len, reverse=True)
    for extra in outliers[max_groups:]:          # more groups than boxes: keep on map
        kept.extend(extra)
    return kept, outliers[:max_groups]


def _split_main_inset(stadiums, params=None):
    """When the inset option is on, peel the densest cluster off the main map so
    its labels move into the zoom box. Otherwise everything stays on the main map."""
    if params and params.get("inset") == "auto":
        cluster = _auto_inset_cluster(stadiums)
        if cluster:
            cset = {id(s) for s in cluster}
            main = [s for s in stadiums if id(s) not in cset]
            return main, cluster
    return stadiums, []


def _percentile(sorted_vals, q):
    if not sorted_vals:
        return 0.0
    i = q * (len(sorted_vals) - 1)
    lo, hi = int(math.floor(i)), int(math.ceil(i))
    if lo == hi:
        return sorted_vals[lo]
    return sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * (i - lo)


# Fixed frame for the three continental competitions. These maps are published as a
# set, so they must be the SAME frame every time — a Conference League map that
# reaches Baku and a Champions League map that stops at Vienna do not read as a
# series, and auto-fitting gave exactly that.
#
# The window is Europe plus the two places whose clubs play in UEFA competitions
# without being in Europe: Israel (Hapoel Be'er Sheva sits at 31.3°N, the southern
# limit) and Turkey (Trabzonspor at 39.7°E). It deliberately does NOT stretch to the
# Urals; no Russian club takes part, so nothing is lost by stopping short, and
# reaching for empty Asian landmass shrinks the part anyone is looking at.
# The east edge is 51°E, not the ~46° that "Europe" suggests, and that is deliberate:
# it is the smallest window that already contains EVERY participant, so the widening
# guard below never fires and all three competitions get a pixel-identical frame. At
# 46° the guard fired for Sabah of Baku (49.8°E) and the Champions League map came out
# framed differently from the Europa League one — a fixed frame that moves is not one.
# The corners it buys are sea and Caucasus, both of which sit under the label columns.
#
# The other three edges are each pinned by a real participant, with a little air:
#   west  -11.0  Torreense, Torres Vedras (-9.3°E)
#   south  30.0  Hapoel Be'er Sheva (31.3°N) — the reason the Middle East is in shot
#   north  68.5  Bodø/Glimt (67.3°N)
_UEFA_FRAME = (-11.0, 30.0, 51.0, 68.5)      # lon0, lat0, lon1, lat1


def _uefa_frame_bbox(stadiums):
    """The fixed continental frame, widened only if a ground falls outside it.

    A fixed frame that silently crops is worse than no fixed frame: the label engine
    still draws the club, so the map grows a label pointing off-canvas at nothing —
    which is precisely the defect this replaces. So the constant is a MINIMUM, never
    a clip. Sabah of Baku (49.8°E) is the one participant beyond it today, and this
    is what keeps them on the map instead of quietly off it.
    """
    lon0, lat0, lon1, lat1 = _UEFA_FRAME
    if stadiums:
        m = 0.6                                   # keep an outlier off the very edge
        lon0 = min(lon0, min(s["lon"] for s in stadiums) - m)
        lon1 = max(lon1, max(s["lon"] for s in stadiums) + m)
        lat0 = min(lat0, min(s["lat"] for s in stadiums) - m)
        lat1 = max(lat1, max(s["lat"] for s in stadiums) + m)
    return (lon0, lat0, lon1, lat1)


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


def _inset_layout(inset_stadiums, W, H, main_bbox=None, reserves=None, zoom_bbox=None,
                  width_frac=0.24, bbox_pad=0.35, bbox_floor=0.008,
                  corner="auto", markers=None):
    """Pick the inset box geometry (size + emptiest corner) up front, so the main
    map's label engine can RESERVE it and never draw a label under the inset. When
    `zoom_bbox` is given (a user-drawn rectangle), that exact area is zoomed; else
    the area is derived tightly from the inset grounds."""
    # Every length here scales with the canvas. Absolute pixels made the inset a
    # DIFFERENT FRACTION of an HD canvas than of an FHD one, which shifted the
    # corner-score geometry enough to flip which corner won -- so the free (capped
    # to HD) and paid (full size) exports of the same configuration put the detail
    # box in different corners. The two must differ only by logo and watermark.
    _k = W / float(_REFERENCE_W)
    margin = max(8, int(round(16 * _k)))
    # The source rectangle: an explicit drawn box wins; else hug the grounds.
    cluster_bbox = zoom_bbox or _inset_cluster_bbox(inset_stadiums, pad=bbox_pad,
                                                   floor=bbox_floor)
    # Match the inset box aspect to the drawn area so the zoom isn't distorted.
    aspect = ((cluster_bbox[2] - cluster_bbox[0]) /
              max(1e-6, _merc_y(cluster_bbox[1]) - _merc_y(cluster_bbox[3])) /
              (W / float(H)))
    IW = max(int(round(220 * _k)), int(W * width_frac))
    IH = int(max(int(round(160 * _k)), min(IW * 1.1, IW / max(0.4, min(2.5, aspect)))))
    if main_bbox:
        ax0, ay0 = _lon_lat_to_px(cluster_bbox[0], cluster_bbox[3], main_bbox, W, H)
        ax1, ay1 = _lon_lat_to_px(cluster_bbox[2], cluster_bbox[1], main_bbox, W, H)
        ccx, ccy = (ax0 + ax1) / 2, (ay0 + ay1) / 2
    else:
        ccx, ccy = W / 2, H / 2
    corners = {
        "tl": (margin, margin), "tr": (W - IW - margin, margin),
        "bl": (margin, H - IH - margin), "br": (W - IW - margin, H - IH - margin),
    }
    # The source rectangle on the main map: the inset must never sit on top of the
    # very grounds it is magnifying.
    src_rect = None
    if main_bbox:
        src_rect = (min(ax0, ax1), min(ay0, ay1), max(ax0, ax1), max(ay0, ay1))

    def _overlaps(box, other, pad=0):
        return not (box[2] + pad < other[0] or box[0] - pad > other[2]
                    or box[3] + pad < other[1] or box[1] - pad > other[3])

    def _corner_score(pos):
        """Lower is better: the NEAREST corner that covers nothing.

        `markers` are the other grounds drawn on the main map. Avoiding only the
        magnified cluster was not enough: on the Spain map the box landed in the
        top-left and buried Racing Santander and Deportivo, while the bottom-left
        was empty. A badge hidden under the inset is worse than a longer leader.

        This used to return `dist - penalty` and take the max, i.e. the corner
        FURTHEST from the cluster. On the Austria map that put the Vienna inset in
        the top-left and drew its leader diagonally across the entire country --
        "who the hell draws lines across if it's not necessary", as a reader put
        it. Distance was never the goal; not covering anything was. So: minimise
        the leader length, and let a large penalty rule out any corner that would
        overlap the grounds being magnified or a reserved label column.
        """
        x0, y0 = corners[pos]
        cx, cy = x0 + IW / 2, y0 + IH / 2
        dist = ((cx - ccx) ** 2 + (cy - ccy) ** 2) ** 0.5
        box = (x0, y0, x0 + IW, y0 + IH)
        penalty = sum(10000 for rb in (reserves or []) if _overlaps(box, rb))
        if src_rect and _overlaps(box, src_rect, pad=8):
            penalty += 10000
        # Each ground the box would cover costs more than any leader length can.
        pad = max(10, int(round(12 * _k)))
        penalty += 20000 * sum(
            1 for (mx, my) in (markers or [])
            if box[0] - pad <= mx <= box[2] + pad and box[1] - pad <= my <= box[3] + pad)
        return dist + penalty

    # An explicit choice wins outright; "auto" scores the four corners.
    choice = (corner or "auto").strip().lower()
    pos = choice if choice in corners else min(corners, key=_corner_score)
    ix0, iy0 = corners[pos]
    return {"ix0": ix0, "iy0": iy0, "IW": IW, "IH": IH, "cluster_bbox": cluster_bbox,
            "box": (ix0, iy0, ix0 + IW, iy0 + IH)}


def _label_key(s):
    """Stable identifier for one inset label, used by the drag editor.

    Must survive a re-render: the browser sends back positions keyed by this, and
    a list index would silently reassign every saved position the moment a filter
    changes the stadium set. The stadium slug is unique and stable; tournament and
    development venues have no slug, so their name is slugified as a fallback.
    """
    return (s.get("slug") or "").strip() or slugify(s.get("name", ""))[:60]


def _parse_label_overrides(raw):
    """Parse `label_pos=<key>:<nx>,<ny>;...` into {key: (nx, ny)}.

    Coordinates are the pill's top-left as a FRACTION of the inset box, so a saved
    layout keeps working when the user switches export size -- the whole point of
    the resolution-independent sizing work. Anything unparseable is dropped rather
    than raising: this arrives from a query string and a single bad pair must not
    cost the user their whole map.
    """
    out = {}
    for part in (raw or "").split(";"):
        part = part.strip()
        if not part or ":" not in part:
            continue
        key, _, coords = part.partition(":")
        try:
            nx, ny = (float(v) for v in coords.split(",", 1))
        except (TypeError, ValueError):
            continue
        if not (-0.5 <= nx <= 1.5 and -0.5 <= ny <= 1.5):
            continue          # far outside the box: treat as corrupt, not as intent
        out[key.strip()[:60]] = (nx, ny)
    return out


def _measure_text(draw, text, font, fallback_cw=7):
    """True pixel size of `text`. Shared by the main label engine and the inset —
    the inset used to estimate width as len(text) * font.size * 0.58, which is
    badly wrong for long names and let its pills overrun into each other."""
    try:
        bb = draw.textbbox((0, 0), text, font=font)
        return bb[2] - bb[0], bb[3] - bb[1]
    except AttributeError:
        return len(text) * fallback_cw, getattr(font, "size", 12)


def _wrap_text(draw, text, font, max_w, fallback_cw=7):
    """Greedy word wrap to max_w. Returns [(line, w, h), ...]."""
    words, lines, cur = text.split(), [], ""
    for word in words:
        trial = f"{cur} {word}".strip()
        if cur and _measure_text(draw, trial, font, fallback_cw)[0] > max_w:
            lines.append(cur)
            cur = word
        else:
            cur = trial
    if cur:
        lines.append(cur)
    return [(ln,) + _measure_text(draw, ln, font, fallback_cw)
            for ln in (lines or [text])]


def _draw_inset(img, inset_stadiums, params, W, H, country_index, style_key,
                main_bbox=None, layout=None, show_source=True, header="Detail view",
                draw_labels=True, label_overrides=None, geometry_sink=None):
    """Magnifier inset: render the densest cluster zoomed into a corner box, draw
    a source outline where it sits on the main map, and connect the two. Labels in
    the box are clean because only a few grounds are shown, enlarged."""
    if not inset_stadiums:
        return img
    if layout is None:
        layout = _inset_layout(inset_stadiums, W, H, main_bbox)
    ix0, iy0, IW, IH = layout["ix0"], layout["iy0"], layout["IW"], layout["IH"]
    cluster_bbox = layout["cluster_bbox"]

    # Same background as the main map (satellite/dark tiles), so the zoom reads as
    # a real magnifier of the area rather than a flat green panel.
    use_tiles = params.get("tiles", True) and not params.get("bg_color")
    inset_img = _make_background(style_key, IW, IH, cluster_bbox,
                                 use_tiles=use_tiles,
                                 land_color=params.get("bg_color")).convert("RGBA")
    # Badge radius and label sizes come from the MAIN MAP's settings, not from the
    # inset's own width. Deriving them from IW made the detail view render its
    # badges and text at a different scale from the map around it, which reads as
    # two charts stitched together rather than one map with a magnifier.
    BR = max(9, int(params.get("badge_size", 13)))
    font_s = _load_font(bold=True,  size=max(11, int(params.get("label_size", 22) * 0.82)))
    font_t = _load_font(bold=False, size=max(9, int(params.get("label_size", 22) * 0.64)))
    badges = _prefetch_badges(inset_stadiums, size=BR * 2)

    rr = BR + 2
    badge_bg = _badge_bg_fill(params)
    d = ImageDraw.Draw(inset_img)

    # Pass 1: draw all badges first (so labels, drawn next, are never covered).
    dots = []
    for s in inset_stadiums:
        px, py = _lon_lat_to_px(s["lon"], s["lat"], cluster_bbox, IW, IH)
        colour    = _dot_colour(s, params, country_index)
        badge_img = badges.get(_badge_key(s))
        if badge_bg is not None:
            d.ellipse([px-rr, py-rr, px+rr, py+rr], fill=badge_bg)
        if badge_img:
            b = badge_img.resize((BR*2, BR*2), Image.LANCZOS)
            _paste_badge(inset_img, b, (px-BR, py-BR), BR*2)
        else:
            d.ellipse([px-BR, py-BR, px+BR, py+BR], fill=colour)
        dots.append((px, py, s))
    d = ImageDraw.Draw(inset_img)

    # Pass 2: two-column edge layout. Labels are pushed to the inset's left/right
    # margins and stacked in latitude order, like the main map's column-leader
    # engine. Every ground in the inset IS labelled (mandatory) — no search-and-drop
    # that could silently omit a name.
    #
    # Three things used to make these collide, all fixed here:
    #   * width was estimated as len(text) * font.size * 0.58, which underestimates
    #     long names badly — "Turka Araç Muayene Kocaeli Stadyumu" ran straight into
    #     the opposite column;
    #   * nothing wrapped, so one long name produced one very wide pill;
    #   * when a column ran out of vertical room the stack clamped every remaining
    #     pill to the same bottom position, drawing them on top of each other.
    # Now text is measured with real metrics, wrapped to a width that makes a
    # left/right overlap geometrically impossible, and the font steps down until the
    # tallest column genuinely fits.
    # Pill padding and gaps scale with the export, like label_size and badge_size
    # already do. As fixed pixel counts they made a pill a different FRACTION of
    # the box at each size, so an inset never looked the same on the HD preview as
    # on the FHD file people paid for -- and a hand-placed label clamped to a
    # different spot on each.
    _k = max(0.5, W / float(_REFERENCE_W))
    PAD = max(2, int(round(4 * _k)))
    GAP_MIN = max(2, int(round(3 * _k)))
    ROW_GAP = max(1, int(round(2 * _k)))
    # Keep clear of the "Detail view" header. Every term scales with IW, so the
    # header occupies the same FRACTION of the box at any export size. It used to
    # be `int(IW * 0.03) + 16`, and that absolute 16 made the reserved strip 16.9%
    # of the box at HD but 13.8% at FHD -- which silently moved a hand-placed label
    # between the preview and the paid download, the same defect as the free/paid
    # marker-size mismatch. The multiplier reproduces the old value at HD.
    hdr_h = int(IW * 0.03) + int(IW * 0.0417)
    avail_h = int(IH * 0.992) - hdr_h
    # Two pills plus a centre gutter must fit across the box, so neither column can
    # ever reach the other however long the club name is.
    pill_max_w = int(IW * 0.44)

    def _build(f_stad, f_team):
        """Lay out every label at the given fonts; returns (items, tallest column)."""
        built = []
        for px, py, s in (dots if draw_labels else []):
            rows = []
            team_line = s.get("team_name", "") or ""
            if team_line:
                rows += [(t, f_team, "team", w, h) for t, w, h in
                         _wrap_text(d, team_line, f_team, pill_max_w - 2 * PAD)]
            rows += [(t, f_stad, "stad", w, h) for t, w, h in
                     _wrap_text(d, s["name"], f_stad, pill_max_w - 2 * PAD)]
            tw = max(r[3] for r in rows) + 2 * PAD
            th = sum(r[4] for r in rows) + 2 * PAD + ROW_GAP * (len(rows) - 1)
            built.append({"px": px, "py": py, "rows": rows, "tw": tw, "th": th,
                          "key": _label_key(s), "team": team_line,
                          "stadium": s.get("name", "")})
        by_x = sorted(built, key=lambda it: it["px"])
        half = (len(by_x) + 1) // 2
        left_ids = {id(it) for it in by_x[:half]}
        cols = ([it for it in built if id(it) in left_ids],
                [it for it in built if id(it) not in left_ids])
        tallest = max((sum(it["th"] for it in c) + GAP_MIN * max(0, len(c) - 1)
                       for c in cols), default=0)
        return built, cols, tallest

    # Step the fonts down until the busiest column fits without stacking pills on
    # top of one another. Shrinking text is the lesser evil: the box exists to name
    # these grounds, so an unreadable overlap defeats it entirely.
    f_stad, f_team = font_s, font_t
    items, cols, tallest = _build(f_stad, f_team)
    _step  = max(1, int(round(1 * _k)))
    _floor = max(9, int(round(9 * _k)))
    while tallest > avail_h and getattr(f_stad, "size", 0) > _floor:
        try:
            f_stad = _load_font(bold=True,  size=f_stad.size - _step)
            f_team = _load_font(bold=False,
                                size=max(max(8, int(round(8 * _k))),
                                         f_team.size - _step))
        except Exception:
            break
        items, cols, tallest = _build(f_stad, f_team)

    for side, col in zip(("left", "right"), cols):
        if not col:
            continue
        col.sort(key=lambda it: it["py"])
        total = sum(it["th"] for it in col)
        spread = avail_h - total
        gap = max(GAP_MIN, spread / (len(col) + 1)) if spread > 0 else GAP_MIN
        y = hdr_h + (gap if spread > 0 else 0)
        for it in col:
            # Never clamp two pills to the same spot: keep the running cursor even if
            # that means the last one sits slightly low, which the font-shrink above
            # has already made very unlikely.
            it["ly"] = int(y)
            it["lx"] = 4 if side == "left" else IW - 4 - it["tw"]
            it["side"] = side
            y = it["ly"] + it["th"] + gap

    # A position the user dragged replaces the computed one. It is applied AFTER
    # the automatic pass so an override only moves its own pill: the column stack
    # above stays intact for every label the user did not touch, and clearing one
    # override returns just that label to its automatic slot.
    overrides = label_overrides or {}
    for it in items:
        pos = overrides.get(it["key"])
        if not pos:
            continue
        # Clamp on FRACTIONS of the box, never on the pill's own width or height.
        #
        # Font sizes are integers and the shrink loop steps discretely, so a pill
        # is not exactly the same fraction of the box at every export size. Bounding
        # by `IW - tw` therefore made the limit itself resolution-dependent, and a
        # label dropped near an edge landed somewhere else on the paid file than on
        # the HD preview it was placed on. Bounding by fractions makes the drop
        # point a pure function of what the user dragged.
        #
        # The pill can then overhang; it is clipped by the inset image, which is the
        # right failure -- the browser clamps against the real measured pill before
        # sending, so overhang only happens for a hand-edited URL.
        it["lx"] = int(max(IW * 0.005, min(IW * 0.92, pos[0] * IW)))
        it["ly"] = int(max(hdr_h, min(IH * 0.90, pos[1] * IH)))
        # The leader must leave from whichever edge faces the badge, or a moved
        # pill draws its line out of the far side and back across itself.
        it["side"] = "left" if (it["lx"] + it["tw"] / 2) < it["px"] else "right"

    if geometry_sink is not None:
        for it in items:
            geometry_sink.append({
                "key": it["key"], "team": it["team"], "stadium": it["stadium"],
                # fractions of the INSET box, matching what label_pos expects back
                "x": round(it["lx"] / float(IW), 5),
                "y": round(it["ly"] / float(IH), 5),
                "w": round(it["tw"] / float(IW), 5),
                "h": round(it["th"] / float(IH), 5),
                "anchor_x": round(it["px"] / float(IW), 5),
                "anchor_y": round(it["py"] / float(IH), 5),
                "moved": it["key"] in overrides,
            })

    for it in items:
        lx, ly, tw, th = it["lx"], it["ly"], it["tw"], it["th"]
        # leader from the badge to the pill's inner edge (right edge for a left-column
        # label, left edge for a right-column one) — drawn under the pill.
        inner_x = lx + tw if it["side"] == "left" else lx
        d.line([(it["px"], it["py"]), (inner_x, ly + th // 2)],
               fill=(255, 255, 255, 170), width=1)
        d.rounded_rectangle([lx - 3, ly - 2, lx + tw + 3, ly + th + 2],
                            radius=4, fill=(10, 13, 24, 235))
        yy = ly + PAD
        for text, fnt, kind, _w, hh in it["rows"]:
            d.text((lx + PAD, yy), text, font=fnt,
                   fill=(170, 205, 255) if kind == "team" else (255, 255, 255))
            yy += hh + ROW_GAP

    # Re-draw the badges ON TOP of the pills. In a box this small the label columns
    # unavoidably run over the markers, and a hidden badge defeats the point of the
    # box — better to clip a few characters of text than lose the ground itself.
    for px, py, s_ in dots:
        badge_img = badges.get(_badge_key(s_))
        if badge_bg is not None:
            d.ellipse([px-rr, py-rr, px+rr, py+rr], fill=badge_bg)
        if badge_img:
            b = badge_img.resize((BR*2, BR*2), Image.LANCZOS)
            _paste_badge(inset_img, b, (px-BR, py-BR), BR*2)
        else:
            d.ellipse([px-BR, py-BR, px+BR, py+BR],
                      fill=_dot_colour(s_, params, country_index))

    d.rectangle([(0, 0), (IW-1, IH-1)], outline=(120, 200, 255), width=3)
    try:
        fhdr = _load_font(bold=True, size=max(12, int(IW * 0.03)))
    except Exception:
        fhdr = ImageFont.load_default()
    d.text((8, 6), header, font=fhdr, fill=(190, 225, 255))

    # --- source outline on the main map + connector to the inset box ---
    # Skipped for island groups: they sit OUTSIDE the main frame, so there is no
    # on-map area to outline and a connector would point off the edge.
    if main_bbox and show_source:
        sx0, sy0 = _lon_lat_to_px(cluster_bbox[0], cluster_bbox[3], main_bbox, W, H)
        sx1, sy1 = _lon_lat_to_px(cluster_bbox[2], cluster_bbox[1], main_bbox, W, H)
        md = ImageDraw.Draw(img)
        md.rectangle([sx0, sy0, sx1, sy1], outline=(120, 200, 255), width=2)
        # two connector lines from the source box to the inset box (magnifier look)
        src_cx, src_cy = (sx0 + sx1) / 2, (sy0 + sy1) / 2
        ins_cx, ins_cy = ix0 + IW / 2, iy0 + IH / 2
        if ins_cx < src_cx:   # inset on the left
            md.line([(sx0, sy0), (ix0 + IW, iy0)], fill=(120, 200, 255, 130), width=1)
            md.line([(sx0, sy1), (ix0 + IW, iy0 + IH)], fill=(120, 200, 255, 130), width=1)
        else:                  # inset on the right
            md.line([(sx1, sy0), (ix0, iy0)], fill=(120, 200, 255, 130), width=1)
            md.line([(sx1, sy1), (ix0, iy0 + IH)], fill=(120, 200, 255, 130), width=1)

    img.paste(inset_img, (ix0, iy0), inset_img)
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


def _spotlight_country(img, stadiums, bbox, W, H, dim=165, focus=None):
    """Dim everything OUTSIDE the country/countries that contain the displayed
    stadiums, and outline those borders, so the selected country stands out.

    Containment alone cannot express "the English league", because an English
    league is not confined to England: Cardiff, Swansea and Wrexham are Welsh
    clubs in the EFL, and Berwick-style edge cases aside, letting their grounds
    choose the highlight lights up Wales too. `focus` names the country to
    highlight so those clubs still appear as markers OUTSIDE the lit area, which
    is the honest picture -- they play in England's pyramid, they are not in
    England. Containment stays the fallback when no country filter is set.

    This only became expressible once the border data was split: the bundled set
    had ONE "United Kingdom" polygon, so England, Scotland, Wales and Northern
    Ireland could not be told apart at all. It now carries the four home nations
    as separate Natural Earth map units.
    """
    pts = [(s["lon"], s["lat"]) for s in stadiums]
    if not pts:
        return img

    try:
        # Use the hi-res Natural Earth 10m set: one named MultiPolygon per country
        # (Italy incl. Sicily/Sardinia, Serbia incl. Vojvodina, Bosnia whole, Denmark
        # incl. its islands), so the spotlight outline is crisp and never drops a region.
        feats = _load_countries_hi()
    except Exception:
        return img

    # Precompute each country's outer rings + overall lon/lat bbox once.
    feat_rings = []   # index-aligned with feats: (rings, (lo0, la0, lo1, la1)) or None
    for feat in feats:
        geom = feat["geometry"]
        if geom["type"] == "Polygon":
            rings = [geom["coordinates"][0]]
        elif geom["type"] == "MultiPolygon":
            rings = [poly[0] for poly in geom["coordinates"]]
        else:
            feat_rings.append(None)
            continue
        lo0 = min(c[0] for r in rings for c in r); lo1 = max(c[0] for r in rings for c in r)
        la0 = min(c[1] for r in rings for c in r); la1 = max(c[1] for r in rings for c in r)
        feat_rings.append((rings, (lo0, la0, lo1, la1)))

    def _contains(fi, lo, la):
        entry = feat_rings[fi]
        if not entry:
            return False
        for ring in entry[0]:
            rlons = [c[0] for c in ring]; rlats = [c[1] for c in ring]
            if (min(rlons) <= lo <= max(rlons) and min(rlats) <= la <= max(rlats)
                    and _point_in_ring(lo, la, ring)):
                return True
        return False

    # A named focus wins outright: highlight that country and nothing else, however
    # the grounds fall. Matched on the polygon's own name, so it works for any
    # country and needs no table.
    if focus:
        want = (focus or "").strip().lower()
        named = {i for i, f in enumerate(feats)
                 if (f.get("properties", {}).get("name") or "").strip().lower() == want}
        if named:
            return _spotlight_draw(img, feat_rings, named, bbox, W, H, dim)

    # First pass: which country polygon strictly contains each displayed ground?
    matched = set()
    unmatched = []
    for lo, la in pts:
        hit = None
        for fi in range(len(feat_rings)):
            if _contains(fi, lo, la):
                hit = fi
                break
        if hit is not None:
            matched.add(hit)
        else:
            unmatched.append((lo, la))

    # Coastal / island / delta grounds (e.g. Gazprom Arena on a reclaimed island in
    # the Neva delta) fall just OUTSIDE the simplified 10m coastline, so strict
    # containment misses them. Snap each such ground to the NEAREST country within a
    # small tolerance — a stadium is always close to its own land — so its country
    # still lights up. Name-independent, works for any coastal ground.
    TOL2 = 0.6 ** 2   # squared degrees (~up to a few tens of km); guards against open sea
    for lo, la in unmatched:
        best, bestd = None, TOL2
        for fi, entry in enumerate(feat_rings):
            if not entry:
                continue
            lo0, la0, lo1, la1 = entry[1]
            if lo < lo0 - 0.6 or lo > lo1 + 0.6 or la < la0 - 0.6 or la > la1 + 0.6:
                continue
            for ring in entry[0]:
                for x, y in ring:
                    dd = (x - lo) ** 2 + (y - la) ** 2
                    if dd < bestd:
                        bestd, best = dd, fi
        if best is not None:
            matched.add(best)

    if not matched:
        return img  # no polygon matched, leave the map untouched
    return _spotlight_draw(img, feat_rings, matched, bbox, W, H, dim)


def _spotlight_draw(img, feat_rings, selected, bbox, W, H, dim):
    """Dim everything outside `selected` and trace its border.

    Split out of _spotlight_country so the name-focus path and the containment
    path light the map identically -- the only thing that differs between them is
    WHICH polygons get chosen.
    """
    # Draw the WHOLE of each matched country (every island / region), not just the
    # part that holds a stadium, so Denmark keeps Jutland, Serbia keeps Vojvodina, etc.
    mask = Image.new("L", (W, H), 0)
    md = ImageDraw.Draw(mask)
    border_rings = []
    for fi in selected:
        for ring in feat_rings[fi][0]:
            pix = [_lon_lat_to_px(lo, la, bbox, W, H) for lo, la in ring]
            if len(pix) >= 3:
                md.polygon(pix, fill=255)
                border_rings.append(pix)

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

    Deliberately does NOT use Django's in-process LocMemCache, holding tile PNG
    bytes in RAM grows the worker's footprint render-after-render and contributes
    to OOM on the 512 MB dyno. The /tmp disk cache is enough and is shared across
    workers on the same instance.
    """
    template = _TILE_SERVERS[style_key]
    disk_path = None
    try:
        disk_dir = _os.path.join(_os.path.sep, "tmp", "soe_tiles")
        _os.makedirs(disk_dir, exist_ok=True)
        # The cache key carries a fingerprint of the SOURCE URL, not just the style
        # name. Keyed on the style alone, changing provider kept serving whatever was
        # already on disk -- which on production meant continuing to serve CARTO tiles
        # with "API KEY REQUIRED" stamped across them long after the URL had changed,
        # with no way to tell short of deleting /tmp by hand.
        src = hashlib.md5(template.encode("utf-8")).hexdigest()[:8]
        disk_path = _os.path.join(disk_dir, f"{style_key}_{src}_{z}_{x}_{y}.png")
        if _os.path.exists(disk_path):
            return Image.open(disk_path).convert("RGBA")
    except Exception:
        disk_path = None

    url = template.format(z=z, x=x, y=y)
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
            # Project ALL points, Pillow clips naturally; per-point filtering
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
    output image + a handful of in-flight tiles, never a giant stitch canvas,
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
    # Ceiling is 14, not 8: a small bbox (the magnifier inset, or a small country)
    # needs a HIGH zoom to show any real detail. Capping at 8 meant the "Detail
    # view" was just the main map's coarse tiles blown up — visibly blurry, with
    # no more detail than the map it was magnifying. Large bboxes simply blow
    # MAX_TILES at high zoom and fall through to a lower one, so this costs
    # nothing for continent-scale maps.
    MAX_TILES = 160
    z = None
    best_affordable = None
    for z_try in range(14, 2, -1):
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


_CREST_DIR = _os.path.join(str(settings.BASE_DIR), "italiastadiaapp",
                          "static", "crests")
_BADGE_DISK_CACHE = _os.path.join(_os.path.sep, "tmp", "soe_badges")
try:
    _os.makedirs(_BADGE_DISK_CACHE, exist_ok=True)
except Exception:
    _BADGE_DISK_CACHE = None


# Wikimedia's user-agent policy: a descriptive agent with contact details.
# A generic string gets rate-limited (HTTP 429) as soon as several crests are
# fetched in one render, which shows up as randomly missing badges.
_BADGE_UA_WIKIMEDIA = "stadiamap/1.0 (destavola.marco@gmail.com)"


# SVGs are rasterised by MediaWiki at this width before being fitted into the badge
# circle. It was 256, which is barely above the 160 we store: a detailed crest lost
# its fine strokes on the way down and looked speckled on the map -- Palermo's gold
# outline broke up and its wordmark turned to mush. Rasterising at 1024 and reducing
# from there keeps those strokes continuous, and costs NOTHING on disk, because what
# we store is still 160.
_SVG_RASTER_W = 1024

def _svg_badge_png_url(svg_url):
    """Resolve an upload.wikimedia.org SVG file to a rasterised PNG thumbnail URL via
    the MediaWiki imageinfo API. Fair-use logos live on the local wiki (…/wikipedia/en/…)
    and free ones on Commons (…/wikipedia/commons/…); query the right host accordingly.
    Returns a PNG url or None."""
    try:
        fname = svg_url.rsplit("/", 1)[-1]
        from urllib.parse import unquote
        title = "File:" + unquote(fname)
        # …/wikipedia/<proj>/… → API host: 'commons' → commons.wikimedia.org, else <proj>.wikipedia.org
        proj = "commons"
        if "/wikipedia/" in svg_url:
            proj = svg_url.split("/wikipedia/", 1)[1].split("/", 1)[0]
        host = "commons.wikimedia.org" if proj == "commons" else f"{proj}.wikipedia.org"
        r = _requests.get(
            f"https://{host}/w/api.php",
            params={"action": "query", "titles": title, "prop": "imageinfo",
                    "iiprop": "url", "iiurlwidth": _SVG_RASTER_W, "format": "json"},
            headers={"User-Agent": _BADGE_UA_WIKIMEDIA}, timeout=15).json()
        for p in r["query"]["pages"].values():
            ii = p.get("imageinfo", [{}])[0]
            return ii.get("thumburl") or None
    except Exception:
        return None
    return None



# Per-host concurrency caps for badge fetches.
#
# _prefetch_badges runs 8 workers. Against Transfermarkt's CDN that is a burst it
# refuses: fetching the 12 Austrian Bundesliga crests one at a time returns 200 for
# every one, while the same 12 through the concurrent prefetch returned ONE badge
# and eleven bare green dots. CLAUDE.md already records the rule for the scraper --
# "run TM fetches SEQUENTIALLY, concurrency triggers 429/502/504" -- but the
# renderer never followed it.
#
# The retry added earlier does not save this case: all three attempts land inside
# the same throttled window. The cap is the fix; the retry covers the isolated 503.
_BADGE_HOST_LIMITS = {
    "tmssl.akamaized.net": 1,
    # Wikimedia now hosts most crests and throttles bursts from one client.
    # 8 workers against it dropped 17 of 18 badges on a cold cache. Its own
    # guidance is serial-ish access with a contact UA; 3 is a compromise that
    # keeps a full league render under a couple of seconds.
    "upload.wikimedia.org": 3,
}
_BADGE_HOST_DEFAULT = 8
_badge_host_sems = {}
_badge_host_lock = _threading.Lock()


def _badge_host_semaphore(url):
    host = _urlparse(url).netloc.lower()
    with _badge_host_lock:
        sem = _badge_host_sems.get(host)
        if sem is None:
            sem = _threading.Semaphore(
                _BADGE_HOST_LIMITS.get(host, _BADGE_HOST_DEFAULT))
            _badge_host_sems[host] = sem
    return sem


def _fit_badge_in_circle(img, size):
    """Scale a crest so ALL of it survives the circular badge mask.

    The old code did `if h > w: crop((0, 0, w, w))` — it took the TOP square of a
    taller-than-wide image, so the bottom of every shield crest was thrown away
    before the mask even ran, and wide crests were squashed to square instead. A
    Reddit reader spotted the result on the Eredivisie map.

    Fitting by bounding box alone is not enough either: the mask is a CIRCLE, so a
    crest scaled to touch the square's edges still loses its corners. This measures
    the farthest opaque pixel from the centre and scales that distance to the circle
    radius, which is exactly right for both shapes — an already-round crest fills
    the circle edge to edge with nothing trimmed (the case the reader called out),
    while a shield or a wordmark shrinks only as much as its corners demand.
    """
    alpha = img.getchannel("A")
    bbox = alpha.getbbox()          # drop fully transparent padding, never artwork
    if bbox:
        img = img.crop(bbox)
        alpha = img.getchannel("A")
    w, h = img.size
    if not w or not h:
        return Image.new("RGBA", (size, size), (0, 0, 0, 0))

    cx, cy = (w - 1) / 2.0, (h - 1) / 2.0
    px = alpha.load()
    step = max(1, int(max(w, h) / 64))   # sampling grid; exact enough at badge sizes
    far = 0.0
    for y in range(0, h, step):
        for x in range(0, w, step):
            if px[x, y] > 24:           # ignore near-transparent antialiasing fringe
                d = math.hypot(x - cx, y - cy)
                if d > far:
                    far = d
    # A full pixel of clearance, not half: LANCZOS ringing spreads the edge slightly
    # and centring an odd-sized result inside an even canvas costs another half pixel,
    # which together were enough to push a round crest back over the mask edge.
    radius = (size / 2.0) - 1.0
    scale = (radius / far) if far > 0 else 1.0
    nw, nh = max(1, round(w * scale)), max(1, round(h * scale))

    out = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    out.paste(img.resize((nw, nh), Image.LANCZOS), ((size - nw) // 2, (size - nh) // 2))
    return out


def _fetch_badge_image(url, size=20):
    """Download, resize, and cache a badge image to /tmp only (no in-process
    Django cache, see _fetch_one_tile for why)."""
    if not url:
        return None

    # Cache key is the ORIGINAL url so an SVG that's already rasterised on disk never
    # re-hits the MediaWiki API. The `v2` is the fitting-algorithm version: bump it
    # whenever _fit_badge_in_circle changes, otherwise every dyno keeps serving the
    # badges it cropped under the old rules and the fix appears not to work.
    key = hashlib.md5(f"{url}_{size}_v2".encode()).hexdigest()

    # 1. Disk cache (/tmp survives between requests on the same dyno)
    disk_path = _os.path.join(_BADGE_DISK_CACHE, f"{key}.png") if _BADGE_DISK_CACHE else None
    if disk_path and _os.path.exists(disk_path):
        try:
            return Image.open(disk_path).convert("RGBA")
        except Exception:
            pass

    # PIL cannot rasterise SVG. Wikimedia renders any SVG to a PNG thumbnail, but the
    # allowed widths are per-file buckets (not arbitrary), so ask the MediaWiki API for
    # a valid thumburl. Only runs on a cache-miss (above), so it's rare. Fixes crests
    # like SBV Vitesse whose Wikipedia logo is an SVG.
    if url.lower().endswith(".svg") and "upload.wikimedia.org" in url:
        url = _svg_badge_png_url(url)
        if not url:
            return None

    # 2. Fetch from web
    try:
        # Wikimedia throttles generic user agents and asks for contact details in
        # the string (the same rule the wiki audits already follow). Crests are
        # increasingly served from Wikipedia rather than Transfermarkt, whose CDN
        # 503s on individual files, so a throttled fetch here means a blank badge.
        # The timeout is also longer for Wikimedia: an SVG is rasterised on their
        # side and 3s was not always enough, which silently produced a bare dot.
        wikimedia = "wikimedia.org" in url or "wikipedia.org" in url
        headers = {"User-Agent": _BADGE_UA_WIKIMEDIA if wikimedia
                   else "StadiumsOfEurope/1.0"}
        timeout = 10 if wikimedia else 3

        # Retry 5xx and 429. Transfermarkt's CDN 503s individual assets at random
        # and Wikimedia rate-limits bursts; a single attempt meant one unlucky
        # request silently dropped that club's badge and the map drew a bare dot
        # instead. Petrolul Ploiesti vanished from a published Romania map exactly
        # this way, while the same URL served fine seconds later. Kept short: this
        # runs inside the render's 22 s badge budget.
        r = None
        with _badge_host_semaphore(url):
            for attempt in range(3):
                r = _requests.get(url, timeout=timeout, headers=headers)
                # An EMPTY 200 counts as a failure. Transfermarkt's CDN soft-blocks
                # by answering 200 with a zero-byte body rather than a 4xx/5xx:
                # raise_for_status() passes, PIL then fails to open the empty buffer,
                # and the outer except swallows it. Eleven of twelve Austrian crests
                # vanished this way while every URL "worked" when checked by status
                # code alone. 200-with-no-image is the signal that matters.
                too_small = len(r.content or b"") < 100
                retryable = r.status_code >= 500 or r.status_code == 429 or (
                    r.status_code == 200 and too_small)
                if not retryable:
                    break
                if attempt < 2:
                    _time.sleep(0.4 * (attempt + 1))
        r.raise_for_status()
        if len(r.content or b"") < 100:
            return None
        img = _fit_badge_in_circle(Image.open(io.BytesIO(r.content)).convert("RGBA"), size)
        if disk_path:
            try:
                img.save(disk_path, format="PNG")
            except Exception:
                pass
        return img
    except Exception:
        return None


# The disc drawn behind a crest. White is the default because most crests are drawn
# to sit on white, and a dark one (Juventus, Napoli, Torino away kits) needs it to
# read at all. Black suits pale/outline crests on a dark map; "none" drops the disc
# entirely for people who want the crest to float on the imagery.
_BADGE_BG = {
    "white": (255, 255, 255),
    "black": (18, 20, 26),
    "none":  None,
}


def _badge_bg_fill(params):
    """Resolve the badge backing colour, or None for no disc at all."""
    return _BADGE_BG.get((params or {}).get("badge_bg", "white"), (255, 255, 255))


def _circle_mask(d):
    """Anti-aliased circular mask of diameter `d`.

    ImageDraw.ellipse writes a hard 0/255 edge, so every badge on the map had a
    visibly stair-stepped rim. Drawing at 4x and reducing gives the edge real
    intermediate alpha, which is what makes a small badge read as a circle rather
    than as a polygon.
    """
    SS = 4
    big = Image.new("L", (d * SS, d * SS), 0)
    ImageDraw.Draw(big).ellipse([0, 0, d * SS - 1, d * SS - 1], fill=255)
    return big.resize((d, d), Image.LANCZOS)


def _paste_badge(dst, badge, xy, diameter):
    """Paste a crest into the circular badge slot, keeping ITS OWN transparency.

    Image.paste(im, box, mask) uses `mask` for alpha and DISCARDS the image's own
    alpha channel. Passing the circle mask alone therefore painted every
    transparent pixel inside the circle as its raw RGB, which in a PNG is almost
    always black -- so the more transparent a crest was, the blacker its badge.
    Juventus (19% opaque) rendered as a solid black disc and Napoli (12%) as a
    navy one; both are legible the moment their alpha is respected.

    Multiplying the two masks keeps the crest's transparency AND crops it to the
    circle, which is what was intended all along.
    """
    from PIL import ImageChops
    mask = ImageChops.multiply(badge.getchannel("A"), _circle_mask(diameter))
    dst.paste(badge, xy, mask)


def _compose_multi_badge(imgs, size):
    """Combine several tenant crests into one badge image (shared grounds).
    2 clubs -> left/right split; 3-4 -> 2x2 quadrants. Circle-masked by the caller."""
    imgs = [i for i in imgs if i is not None]
    if not imgs:
        return None
    if len(imgs) == 1:
        return imgs[0]
    base = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    if len(imgs) == 2:
        h = size // 2
        base.paste(imgs[0].crop((0, 0, h, size)), (0, 0))
        base.paste(imgs[1].crop((h, 0, size, size)), (h, 0))
        ImageDraw.Draw(base).line([(h, 0), (h, size)], fill=(255, 255, 255), width=1)
    else:
        h = size // 2
        for img, (qx, qy) in zip(imgs[:4], [(0, 0), (h, 0), (0, h), (h, h)]):
            base.paste(img.resize((h, h), Image.LANCZOS), (qx, qy))
    return base


# Crests are downloaded and cached at ONE canonical size, then scaled to whatever
# the caller wants. The disk-cache key includes the size, so when the main map
# asked for 26 px and the inset for ~40 px every crest was downloaded TWICE — and
# the inset's second round is what the host throttled, which is why the auto-zoom
# box rendered green dots while the map around it showed badges. One size means
# one download, and the inset now reuses what the map already fetched.
_BADGE_FETCH_SIZE = 160


def _local_crest(fname):
    """Load a committed crest from static/crests/, or None.

    This is the whole point of download_crests: in the steady state every club has
    a local file and a render makes NO network call for badges, so no third party
    can blank them again. Files are already PNG at _BADGE_FETCH_SIZE and already
    fitted to the circular mask, so nothing else has to happen here.
    """
    if not fname or not _CREST_DIR:
        return None
    path = _os.path.join(_CREST_DIR, _os.path.basename(fname))
    if not _os.path.exists(path):
        return None
    try:
        return Image.open(path).convert("RGBA")
    except Exception:
        return None


def _badge_key(s):
    """Key for the prefetched-badge dict.

    NOT the stadium name. Italy has two grounds called "Romeo Menti" -- Vicenza's
    and Juve Stabia's, genuinely distinct venues that share a name -- and keying on
    the name silently collapsed them, so one club wore the other's crest. The slug
    is unique by database constraint; the name falls back only for synthetic rows
    (tournament and development venues) that have no slug.
    """
    return s.get("slug") or s.get("name") or ""


def _prefetch_badges(stadiums, size=20):
    """Fetch tenant badge images in parallel (hard 22 s budget) and compose a
    single badge per stadium, so shared grounds show a combined crest. Returns
    {stadium_name: PIL image} at `size`; uncached badges are skipped gracefully."""
    # Local committed crests first; only what is still missing goes over the wire.
    local, url_set = {}, set()
    for s in stadiums:
        tlist = s.get("teams") or ([{"image_url": s.get("image_url", ""),
                                     "crest_file": s.get("crest_file", "")}]
                                   if s.get("image_url") else [])
        for t in tlist:
            key = t.get("image_url") or t.get("crest_file")
            if not key:
                continue
            img = _local_crest(t.get("crest_file"))
            if img is not None:
                local[key] = img
            elif t.get("image_url"):
                url_set.add(t["image_url"])
    if not url_set and not local:
        return {}

    deadline = _time.monotonic() + 22   # hard budget, stay under Render's 30s limit
    url_imgs = dict(local)
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = {pool.submit(_fetch_badge_image, url, _BADGE_FETCH_SIZE): url
                   for url in url_set}
        try:
            for future in as_completed(futures, timeout=22):
                if _time.monotonic() > deadline:
                    break
                url = futures[future]
                try:
                    img = future.result(timeout=0)
                    if img:
                        url_imgs[url] = img
                except Exception:
                    pass
        except Exception:
            pass   # TimeoutError from as_completed, use what we have

    result = {}
    for s in stadiums:
        tlist = s.get("teams") or ([{"image_url": s.get("image_url", ""),
                                     "crest_file": s.get("crest_file", "")}]
                                   if s.get("image_url") else [])
        imgs = [url_imgs[k] for k in
                ((t.get("image_url") or t.get("crest_file")) for t in tlist)
                if k in url_imgs]
        if imgs:
            composed = _compose_multi_badge(imgs, _BADGE_FETCH_SIZE)
            if composed is not None and size and size != _BADGE_FETCH_SIZE:
                composed = composed.resize((size, size), Image.LANCZOS)
            result[_badge_key(s)] = composed
    return result


# UEFA club competitions. Deliberately NOT the competitions' own brand colours -- all
# three are blue-dominant and would be indistinguishable at dot size; these are chosen
# to separate as badge rings.
_UEFA_COLOURS = {"UCL": (56, 132, 255), "UEL": (255, 138, 32), "UECL": (56, 200, 120)}
_UEFA_LABELS = {"UCL": "Champions League", "UEL": "Europa League",
                "UECL": "Conference League"}


def _category_colour(stadium, mode, params, country_index):
    """Colour for a stadium under a given category `mode` (surface/type/ownership/
    country/single/tournament_status/dev_status/bid). Shared by dot fill and the
    badge ring."""
    if mode == "tournament_status":
        return _TOURNAMENT_STATUS_COLOR.get(
            stadium.get("tournament_status", "CANDIDATE"), _DEFAULT_DOT_COLOUR)
    if mode == "dev_status":
        return _DEV_STATUS_COLOR.get(stadium.get("dev_status", "PLANNING"), _DEFAULT_DOT_COLOUR)
    if mode == "bid":
        return _BID_COLOR.get(stadium.get("bid", ""), _DEFAULT_DOT_COLOUR)
    if mode == "type":
        return _TYPE_COLOURS.get(stadium.get("stadium_type", ""), _DEFAULT_DOT_COLOUR)
    if mode == "uefa":
        return _UEFA_COLOURS.get(stadium.get("european_competition", ""),
                                 _DEFAULT_DOT_COLOUR)
    if mode == "ownership":
        return _OWNERSHIP_COLOURS.get(stadium.get("ownership", ""), _DEFAULT_DOT_COLOUR)
    if mode == "single":
        return params["single_color"]
    if mode == "country":
        idx = country_index.get(stadium["country"], 0)
        return _COUNTRY_PALETTE[idx % len(_COUNTRY_PALETTE)]
    # surface (default)
    return _SURFACE_COLOURS.get(stadium["surface"], _DEFAULT_DOT_COLOUR)


def _dot_colour(stadium, params, country_index):
    return _category_colour(stadium, params["color_by"], params, country_index)


def _draw_dots_and_labels(img, stadiums, params, bbox, W, H, country_index,
                          reserve_boxes=None, no_label_names=None,
                          extra_label_points=None):
    """`extra_label_points` are (px, py, stadium) anchors already in pixel space,
    for grounds whose badge is drawn elsewhere (inside an island inset). They get
    a full-size label in the margin columns with a leader back to the box, instead
    of a cramped label squeezed inside it."""
    BADGE_R   = params.get("badge_size", 13)
    badge_bg  = _badge_bg_fill(params)
    RING_W    = 2
    # Optional coloured ring around club badges (colour-codes a category while the
    # crest stays visible). Validated to a known mode or "".
    ring_by   = params.get("ring_by") if params.get("ring_by") in (
        "ownership", "surface", "type", "country") else ""
    RING_EXTRA = max(3, BADGE_R // 3)
    FONT_SZ   = params.get("label_size", 22)
    FONT_SZ2  = max(10, int(FONT_SZ * 0.78))
    PAD_X     = 10
    PAD_Y     = 7
    LINE_GAP  = 3

    # Parse label colour, hex string → RGB tuple
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

    rr = BADGE_R + (RING_EXTRA if ring_by else RING_W)

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
            badge_img = badges.get(_badge_key(s))
            # Colour the ring/halo by a chosen category (ring_by) so the club crest
            # stays visible but the rim colour-codes ownership/surface/type/etc.
            if ring_by:
                ring_colour = _category_colour(s, ring_by, params, country_index)
                ring_r = BADGE_R + RING_EXTRA
                draw.ellipse([px - ring_r, py - ring_r, px + ring_r, py + ring_r], fill=ring_colour)
                # thin separator between the colour ring and the crest, in the
                # chosen backing so a black-backed badge does not get a white halo
                draw.ellipse([px - BADGE_R - 1, py - BADGE_R - 1,
                              px + BADGE_R + 1, py + BADGE_R + 1],
                             fill=badge_bg or (255, 255, 255))
            elif badge_bg is not None:
                draw.ellipse([px - rr, py - rr, px + rr, py + rr], fill=badge_bg)
            if badge_img:
                _paste_badge(img, badge_img, (px - BADGE_R, py - BADGE_R),
                             BADGE_R * 2)
                draw = ImageDraw.Draw(img)
            else:
                draw.ellipse([px - BADGE_R, py - BADGE_R, px + BADGE_R, py + BADGE_R], fill=colour)

        badge_circles.append((px, py, rr))
        dot_positions.append((px, py, s))
    # Badges for these were already drawn (inside their inset); label them here so
    # they use the same font and margin columns as every other ground.
    for px, py, s in (extra_label_points or []):
        dot_positions.append((px, py, s))

    if not params["labels"]:
        return img

    # Labels never overlap (see placement below). A single league always fits;
    # only very dense multi-league maps drop a few labels that can't be placed
    # cleanly, no-overlap reads far better than stacked labels.

    def _polyline_clear(pts, own_px, own_py, avoid_boxes=True):
        """True if no segment of the orthogonal polyline crosses another badge , 
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
        (and, when avoid_boxes, other label pills), or, when allow_cross, the
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

    # ── Column-leader labelling (general — no per-map tuning) ─────────────────
    # Push every label out to the LEFT or RIGHT margin and stack the labels in the
    # SAME vertical order as their badges. An order-preserving point-to-column
    # matching is planar, so leader lines never cross; pushing labels to the
    # margins also keeps them clear of the badges (no congestion). Reserved overlay
    # areas (title, legend, logo, inset, …) become forbidden vertical bands the
    # column skips. Works for any selection without tuning.
    EDGE = max(20, int(min(W, H) * 0.03))
    GAPY = max(6, int(FONT_SZ * 0.35))

    # Cap how wide a label may get. Names like "Stadion Miejski im. Marszałka Józefa
    # Piłsudskiego" run half the frame on one line, so they reach across the map and
    # sit on top of the badges however they're stacked vertically. Wrapping them
    # keeps every pill inside its margin column, where it can't cover anything.
    MAX_PILL_W = max(160, int(W * 0.23))

    # Module-level helpers, shared with the inset so both label layouts measure and
    # wrap text identically.
    def _measure(text, font, fallback_cw):
        return _measure_text(draw, text, font, fallback_cw)

    def _wrap(text, font, max_w, fallback_cw):
        return _wrap_text(draw, text, font, max_w, fallback_cw)

    # Keyed on the unique slug, NOT the stadium name. Vicenza and Juve Stabia both
    # play at a "Romeo Menti"; with Juve Stabia's in the inset, a name-keyed skip set
    # suppressed VICENZA's label on the main map too, leaving an unnamed badge and a
    # Serie B map that silently showed 19 of its 20 clubs.
    skip = no_label_names or set()
    items = []
    inner_w = MAX_PILL_W - PAD_X * 2
    for px, py, s in dot_positions:
        if _badge_key(s) in skip:
            continue                            # badge already drawn; label lives in the inset
        team_line, stadium_line = (s.get("team_name", "") or ""), s["name"]
        rows = []                                # [(text, font, fill_key, w, h)]
        if team_line:
            for ln, w, h in _wrap(team_line, font_team, inner_w, 7):
                rows.append((ln, font_team, "team", w, h))
        for ln, w, h in _wrap(stadium_line, font_stadium, inner_w, 9):
            rows.append((ln, font_stadium, "stadium", w, h))
        pill_w = max(r[3] for r in rows) + PAD_X * 2
        pill_h = sum(r[4] for r in rows) + LINE_GAP * (len(rows) - 1) + PAD_Y * 2
        items.append(dict(px=px, py=py, rows=rows, pill_w=pill_w, pill_h=pill_h))

    # Split the labels into the two columns. Default: MEDIAN x, so roughly half go
    # each side. But when the badges form two clearly separated horizontal groups
    # (e.g. a two-country tournament map: Italy west, Turkey east), split at the
    # LARGEST x-gap instead — every west-group label goes left and every east-group
    # label right, which reads far better than mixing the groups. General rule, no
    # per-map tuning: the gap split only kicks in when the widest gap between
    # neighbouring badges is big in absolute terms AND dominates typical spacing.
    by_x = sorted(items, key=lambda it: it["px"])
    mid = len(by_x) // 2
    if len(by_x) >= 6:
        gaps = [(by_x[i + 1]["px"] - by_x[i]["px"], i + 1) for i in range(len(by_x) - 1)]
        # Only splits that stay reasonably BALANCED. Requiring just 2-per-side let
        # the gap split fire on island anchors sitting far right, throwing all 15
        # mainland labels into one column until it overflowed the frame. A genuine
        # two-group map (Italy/Turkey) splits near the middle anyway.
        lo, hi = max(2, int(len(by_x) * 0.35)), min(len(by_x) - 2, int(len(by_x) * 0.65))
        cand = [(g, i) for g, i in gaps if lo <= i <= hi]
        if cand:
            gsize, gidx = max(cand)
            others = sorted(g for g, _ in gaps)
            typical = others[len(others) // 2] or 1
            if gsize > W * 0.15 and gsize > 4 * typical:
                mid = gidx
    left_col = by_x[:mid]
    right_col = by_x[mid:]

    def _bands_for(col_x0, col_x1):
        """Vertical [y0,y1] intervals the column must skip (reserved boxes that
        overlap the column's x-range), sorted top-down."""
        return sorted((rb[1], rb[3]) for rb in (reserve_boxes or [])
                      if not (rb[2] < col_x0 or rb[0] > col_x1))


    def _place_column(col, side):
        if not col:
            return
        maxw = max(it["pill_w"] for it in col)
        col_x0 = EDGE if side == "left" else W - EDGE - maxw
        bands = _bands_for(col_x0, col_x0 + maxw)
        # Each pill hugs its own margin: left column left-aligned at EDGE, right
        # column RIGHT-aligned so its right edge sits at W-EDGE. Aligning every
        # right-hand pill to the widest one instead would push short labels far
        # into the map, covering badges.
        def _x_for(it):
            return EDGE if side == "left" else W - EDGE - it["pill_w"]
        col.sort(key=lambda it: it["py"])       # order-preserving → leaders don't cross
        # Build the FREE vertical segments (the column minus reserved bands), then
        # pack labels across them with an even gap. Packing into the real free space
        # means nothing cascades off the frame, so labels never silently drop.
        free, y = [], EDGE
        for b0, b1 in sorted((max(b0, EDGE), min(b1, H - EDGE)) for b0, b1 in bands):
            if b0 > y:
                free.append([y, b0])
            y = max(y, b1)
        if y < H - EDGE:
            free.append([y, H - EDGE])
        if not free:
            return
        free_total = sum(e - s for s, e in free)
        total_h = sum(it["pill_h"] for it in col)
        n = len(col)
        gap = max(GAPY, (free_total - total_h) / (n + 1)) if free_total > total_h else GAPY
        seg = 0
        cursor = free[0][0] + (gap if free_total > total_h else 0)
        for it in col:
            x0, h = _x_for(it), it["pill_h"]
            # jump to the next free segment if this label won't fit in the current one
            while seg < len(free) and cursor + h > free[seg][1]:
                seg += 1
                if seg < len(free):
                    cursor = free[seg][0]
            if seg >= len(free):
                # Out of free space: keep the label (a missing label is worse than a
                # tight fit) pinned inside the frame rather than dropping it.
                cursor = min(cursor, H - EDGE - h)
                seg = len(free) - 1
            # Never let a pill run off the bottom edge.
            it["ly"] = int(max(EDGE, min(cursor, H - EDGE - h)))
            it["lx"], it["side"] = x0, side
            cursor = it["ly"] + h + gap

    _place_column(left_col, "left")
    _place_column(right_col, "right")

    # Leaders first (under the pills), then the pills + text.
    for it in items:
        if it.get("lx") is None:
            continue
        lx, ly, pw, ph = it["lx"], it["ly"], it["pill_w"], it["pill_h"]
        if it["side"] == "left":
            inner_x, bx = lx + pw, it["px"] - rr
        else:
            inner_x, bx = lx, it["px"] + rr
        draw.line([(bx, it["py"]), (inner_x, int(ly + ph / 2))], fill=label_rgb, width=1)

    for it in items:
        if it.get("lx") is None:
            continue
        lx, ly, pw, ph = it["lx"], it["ly"], it["pill_w"], it["pill_h"]
        draw.rounded_rectangle([lx, ly, lx + pw, ly + ph], radius=5, fill=(8, 10, 20, 220))
        ty = ly + PAD_Y
        for text, font, kind, _w, h in it["rows"]:
            draw.text((lx + PAD_X, ty), text, font=font,
                      fill=team_rgb if kind == "team" else label_rgb)
            ty += h + LINE_GAP

    return img


def _build_legend_entries(params, stadiums):
    """Return list of (colour_tuple, label_str) for the legend. A coloured badge
    ring (ring_by) drives the legend when set; otherwise the dot colour (color_by)."""
    mode = params.get("ring_by") if params.get("ring_by") in (
        "ownership", "surface", "type", "country") else params["color_by"]
    if mode == "tournament_status":
        present = {s.get("tournament_status", "CANDIDATE") for s in stadiums}
        return [
            (_TOURNAMENT_STATUS_COLOR[st], _TOURNAMENT_STATUS_LABEL[st])
            for st in ("CONFIRMED", "CANDIDATE", "DISCARDED") if st in present
        ]
    if mode == "dev_status":
        present = {s.get("dev_status", "PLANNING") for s in stadiums}
        return [
            (_DEV_STATUS_COLOR[st], _DEV_STATUS_LABEL[st])
            for st in _DEV_STATUSES if st in present
        ]
    if mode == "bid":
        present = [b for b in _BID_COLOR if any(s.get("bid") == b for s in stadiums)]
        return [(_BID_COLOR[b], f"{b} bid") for b in present]
    if mode == "single":
        return [(params["single_color"], "Stadium")]
    if mode == "uefa":
        present = {s.get("european_competition", "") for s in stadiums}
        entries = [(_UEFA_COLOURS[c], _UEFA_LABELS[c])
                   for c in ("UCL", "UEL", "UECL") if c in present]
        if "" in present:
            entries.append((_DEFAULT_DOT_COLOUR, "Not in Europe"))
        return entries
    if mode == "ownership":
        present = {s.get("ownership", "") for s in stadiums}
        entries = [(_OWNERSHIP_COLOURS[o], _OWNERSHIP_LABELS[o])
                   for o in ("PUBLIC", "PRIVATE", "MIXED") if o in present]
        if "UNKNOWN" in present or "" in present:
            entries.append((_DEFAULT_DOT_COLOUR, "Unknown"))
        return entries
    if mode == "type":
        present = {s.get("stadium_type", "") for s in stadiums}
        entries = [(_TYPE_COLOURS[t], _TYPE_LABELS[t])
                   for t in ("OPEN", "RETRACTABLE", "CLOSED") if t in present]
        if "" in present:
            entries.append((_DEFAULT_DOT_COLOUR, "Unknown"))
        return entries
    if mode == "surface":
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
        font = _load_font(bold=False, size=14)
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
    """Geometry of the bottom-right logo lockup, shared by the drawing code and
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


# Basemap attribution required by each tile provider's terms of use. Every
# published or exported map must carry the credit for the imagery it actually
# uses — Esri, OpenStreetMap and CARTO all require visible attribution.
_TILE_ATTRIBUTION = {
    "satellite": "Imagery © Esri, Maxar, Earthstar Geographics",
    # dark/light follow whichever provider _TILE_SERVERS actually resolved to, so
    # the credit can never drift from the imagery. Crediting CARTO on an Esri tile
    # would be both wrong and a licence breach.
    "dark":      ("© OpenStreetMap contributors, © CARTO" if _CARTO_KEY
                  else "© Esri, HERE, Garmin, © OpenStreetMap contributors"),
    "light":     ("© OpenStreetMap contributors, © CARTO" if _CARTO_KEY
                  else "© Esri, HERE, Garmin, © OpenStreetMap contributors"),
    "topo":      "© OpenStreetMap contributors",
}


def _source_text(params):
    """Credit line: our data sources plus the basemap attribution for the style
    actually rendered. Tile attribution is dropped when tiles are switched off
    (solid background), because then no provider imagery is shown."""
    # Crests now come from Wikipedia and Wikimedia Commons, not Transfermarkt, so
    # the credit says so. Stadium, club and attendance data still comes from
    # Wikipedia and Transfermarkt, which is why Transfermarkt stays on the line.
    text = "Data: Wikipedia & Transfermarkt  ·  Crests: Wikipedia & Wikimedia Commons"
    uses_tiles = params.get("tiles", True) and not params.get("bg_color")
    if uses_tiles:
        attr = _TILE_ATTRIBUTION.get(params.get("style_key"))
        if attr:
            text += f"  ·  {attr}"
    return text


def _draw_source(img, W, H, legend_entries=0, text=None):
    """Small data-source + basemap-attribution credit in the BOTTOM-LEFT corner.
    When a legend is present (also bottom-left) the credit stacks just above it
    so they don't overlap."""
    text = text or "Data: Wikipedia & Transfermarkt  ·  Crests: Wikipedia & Wikimedia Commons"
    font = _load_font(bold=False, size=13)
    d = ImageDraw.Draw(img)
    try:
        bb = d.textbbox((0, 0), text, font=font)
        tw, th = bb[2] - bb[0], bb[3] - bb[1]
    except AttributeError:
        tw, th = len(text) * 7, 14
    PAD, margin = 7, 16
    pill_w, pill_h = tw + PAD * 2, th + PAD * 2
    # Reserve room for the legend box (padding*2 + entries*line_h) when shown.
    legend_h = (12 * 2 + legend_entries * 22 + 10) if legend_entries else 0
    x0 = margin
    y0 = H - margin - pill_h - legend_h
    tile = Image.new("RGBA", (pill_w, pill_h), (0, 0, 0, 0))
    td = ImageDraw.Draw(tile)
    td.rounded_rectangle([0, 0, pill_w - 1, pill_h - 1], radius=8, fill=(9, 12, 20, 170))
    td.text((PAD, PAD - 1), text, font=font, fill=(220, 220, 220))
    region = img.crop((x0, y0, x0 + pill_w, y0 + pill_h))
    img.paste(Image.alpha_composite(region, tile), (x0, y0))
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


# Label and badge pixel sizes are authored against this canvas width and scaled
# from it, so a map looks identical at HD, FHD and 4K.
_REFERENCE_W = 1280


def _compose_export_image(params):
    """Shared render core for both the free preview and the paid download.
    Returns (PIL RGBA Image, None) or (None, error_message).

    The map fills the whole canvas. When a title is set, its area is reserved so
    no LABEL is placed under it, then the title/subtitle are drawn in a
    TRANSLUCENT box on top, the map shows through, nothing is lost.
    """
    # Label and badge sizes are stored as pixels at the HD reference width, and
    # scaled to whatever canvas is actually being drawn. Without this the SAME
    # configuration produced two different-looking maps: the free endpoint caps
    # fhd to 1280x720 while the paid download renders the full 1920x1080, so a
    # 16 px label was proportionally a third smaller on the file people had paid
    # for. The paid map must differ from the free one only by the logo and the
    # watermark, never in layout.
    _scale = params["W"] / float(_REFERENCE_W)
    if abs(_scale - 1.0) > 0.01:
        params["label_size"] = max(8, int(round(params.get("label_size", 22) * _scale)))
        params["badge_size"] = max(6, int(round(params.get("badge_size", 13) * _scale)))

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
    # Broad, unfiltered Europe export: trim longitude outliers (Iceland / Ural Russia) so
    # the frame stays on Europe. Filtered exports (country/league/tournament/dev/national)
    # keep the full bbox so they're never cropped.
    is_broad = not (params.get("tournament") or params.get("layer") == "development"
                    or params.get("country") or params.get("league")
                    or params.get("surface") or params.get("ownership")
                    or params.get("uefa")
                    or params.get("national") or params.get("national_only"))
    if params.get("uefa") and not (params.get("country") or params.get("league")):
        # A whole continental competition gets the fixed frame, so the three maps
        # are a matching set. EXPAND to aspect, never _cover_bbox_to_aspect: cover
        # crops to fill the canvas, and cropping is what put Barcelona, Real Madrid,
        # Roma and Galatasaray outside the frame while their labels still pointed at
        # them from the margin.
        #
        # Narrowed by country or league it is no longer a continental map — "Italy in
        # the Champions League" wants Italy — so those fall through to the normal fit.
        bbox = _expand_bbox_to_aspect(_uefa_frame_bbox(stadiums), W, H)
    elif is_broad and len(stadiums) > 30:
        # Trim E/W outliers, hard-clamp to a European longitude window (so Iceland in the
        # west and central/eastern Russia never widen the frame), then crop-to-fill.
        tb = _trimmed_bbox(stadiums)
        tb = (max(tb[0], -11.0), tb[1], min(tb[2], 45.0), tb[3])
        bbox = _cover_bbox_to_aspect(tb, W, H)
    else:
        # Far-flung island groups (Madeira, the Azores) otherwise dictate the frame
        # and squash the mainland into a sliver. Frame the main body and give each
        # island group its own box. This is ALWAYS on: an over-extended frame is a
        # legibility defect, not a preference, and those grounds would otherwise be
        # unreadable dots in an ocean. Set islands=0 to force one true-extent frame.
        frame_stadiums = stadiums
        if params.get("islands", True):
            main_body, island_groups = _outlier_island_groups(stadiums)
            if island_groups:
                frame_stadiums = main_body
        raw_bbox = _bbox_with_padding(frame_stadiums)
        if params.get("labels"):
            # Keep the left/right label columns clear of the markers.
            raw_bbox = _label_gutter_bbox(raw_bbox)
        bbox = _expand_bbox_to_aspect(raw_bbox, W, H)

    # Inset grounds + zoom area: a user-drawn box (image fractions over the map)
    # wins and zooms exactly that area; otherwise the auto cluster is used.
    inset_stadiums, inset_zoom_bbox = [], None
    ibox = params.get("inset_box")
    if ibox:
        lon0 = bbox[0] + ibox[0] * (bbox[2] - bbox[0])
        lon1 = bbox[0] + ibox[2] * (bbox[2] - bbox[0])
        myt, myb = _merc_y(bbox[3]), _merc_y(bbox[1])
        lat_hi = _merc_y_inv(myt + ibox[1] * (myb - myt))   # fy=0 is the top → high lat
        lat_lo = _merc_y_inv(myt + ibox[3] * (myb - myt))
        inset_zoom_bbox = (lon0, lat_lo, lon1, lat_hi)
        inset_stadiums = [s for s in stadiums
                          if lon0 <= s["lon"] <= lon1 and lat_lo <= s["lat"] <= lat_hi][:8]
    elif params.get("inset") == "auto":
        # Island groups already have their own boxes; the magnifier only competes
        # for space, so fall back to it only when there are no islands.
        _, island_groups = (_outlier_island_groups(stadiums)
                            if params.get("islands", True) else (stadiums, []))
        if not island_groups:
            inset_stadiums = _auto_inset_cluster(
                stadiums, bbox=bbox, W=W, H=H, badge_r=params.get("badge_size", 13))

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
        img = _spotlight_country(img, stadiums, bbox, W, H,
                                 focus=params.get("country") or None)

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
        reserves.append((0, H - 205, 200, H))                     # bottom-left (legend + source)
    else:
        reserves.append((0, H - 44, 235, H))                      # bottom-left source credit
    if params.get("scale"):
        reserves.append((W // 2 - 135, H - 80, W // 2 + 135, H))  # bottom-centre
    if params.get("logo"):
        reserves.append(_logo_box(W, H))                          # bottom-right

    # Island groups: each gets its own box, and those grounds are drawn ONLY there
    # (they lie outside the main frame, so a badge on the main map would be clipped
    # or land in the wrong place).
    island_layouts = []
    if params.get("islands", True):
        _, island_groups = _outlier_island_groups(stadiums)
        for grp in island_groups:
            # Narrower than a magnifier inset: two of these plus the label columns
            # have to share the frame. Framed MUCH wider than a magnifier though —
            # a magnifier wants to separate two grounds 300 m apart, whereas an
            # island box is only useful if you can see the island's shape and place
            # it geographically. The ~0.45 degree floor (~50 km each side) fits
            # Madeira and Sao Miguel, both roughly 60 km long.
            lay = _inset_layout(grp, W, H, main_bbox=bbox, reserves=reserves,
                                width_frac=0.17, bbox_pad=1.2, bbox_floor=0.45)
            reserves.append(lay["box"])
            island_layouts.append((grp, lay))
    island_names = {s["name"] for grp, _ in island_layouts for s in grp}
    main_stadiums = [s for s in stadiums if s["name"] not in island_names]

    # Reserve the inset box BEFORE labels so no main-map label is hidden under it.
    inset_layout = None
    if inset_stadiums:
        # Every ground on the main map is an obstacle: the box must not be placed
        # on top of a badge just because that corner is closer.
        _markers = [_lon_lat_to_px(s["lon"], s["lat"], bbox, W, H) for s in stadiums]
        inset_layout = _inset_layout(inset_stadiums, W, H, main_bbox=bbox, reserves=reserves,
                                     zoom_bbox=inset_zoom_bbox,
                                     width_frac=params.get("inset_frac", 0.30),
                                     corner=params.get("inset_corner", "auto"),
                                     markers=_markers)
        reserves.append(inset_layout["box"])

    # Islands FIRST, badges only: their labels are handled by the main engine below
    # so they get the same font size and margin columns as every other ground —
    # inside a box this small a label is unreadably cramped. The leader points back
    # into the box, so the tie to the island stays clear.
    island_anchors = []
    for grp, lay in island_layouts:
        header = grp[0].get("city") or grp[0].get("country") or "Detail view"
        img = _draw_inset(img, grp, params, W, H, country_index, params["style_key"],
                          main_bbox=bbox, layout=lay, show_source=False,
                          header=str(header), draw_labels=False)
        for s in grp:
            bx, by = _lon_lat_to_px(s["lon"], s["lat"], lay["cluster_bbox"],
                                    lay["IW"], lay["IH"])
            island_anchors.append((lay["ix0"] + bx, lay["iy0"] + by, s))

    # Draw ALL badges on the main map (incl. the inset cluster, so those grounds
    # still show in place); only their LABELS move into the zoom box.
    inset_names = {_badge_key(s) for s in inset_stadiums}
    img = _draw_dots_and_labels(img, main_stadiums, params, bbox, W, H, country_index,
                                reserve_boxes=reserves, no_label_names=inset_names,
                                extra_label_points=island_anchors)
    if inset_stadiums:
        img = _draw_inset(img, inset_stadiums, params, W, H, country_index,
                          params["style_key"], main_bbox=bbox, layout=inset_layout,
                          label_overrides=params.get("label_pos"),
                          geometry_sink=params.get("_geometry_sink"))
        if params.get("_geometry_sink") is not None and inset_layout:
            params["_inset_box"] = {
                "x": inset_layout["ix0"] / float(W), "y": inset_layout["iy0"] / float(H),
                "w": inset_layout["IW"] / float(W), "h": inset_layout["IH"] / float(H)}
    legend_n = 0
    if params["legend"]:
        img = _draw_legend(img, params, stadiums)
        legend_n = len(_build_legend_entries(params, stadiums))
    if params["north"]:
        img = _draw_north_arrow(img, W, H)
    if params.get("scale"):
        img = _draw_scale_bar(img, bbox, W, H)
    if params.get("logo"):
        img = _draw_logo(img, W, H)
    # data-source + basemap attribution credit
    img = _draw_source(img, W, H, legend_entries=legend_n, text=_source_text(params))

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
    # Cap to HD on free tier (512 MB RAM limit, FHD/4K OOM-kills the dyno)
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
    # Collect inset label boxes during THIS render and ship them back on the same
    # response. A separate geometry endpoint would mean a second full compose per
    # preview, and this box is memory-capped enough already -- FHD and 4K are
    # downgraded to HD above precisely because the free tier OOMs otherwise.
    params["_geometry_sink"] = []
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
    # Inset label geometry for the drag editor. Base64 because header values are
    # latin-1 and these carry club names like "Beşiktaş" and "Fenerbahçe"; raw
    # UTF-8 in a header raises UnicodeEncodeError and would 500 the preview.
    try:
        geo = json.dumps({"inset": params.get("_inset_box"),
                          "labels": params.get("_geometry_sink") or []},
                         ensure_ascii=False, separators=(",", ":"))
        response["X-Inset-Labels"] = base64.b64encode(
            geo.encode("utf-8")).decode("ascii")
    except Exception:
        pass          # the map is the product; never fail a render over metadata
    return response


# ─────────────────────────────────────────────────────────────────────────────
# PAID EXPORT, Stripe pay-per-download
# ─────────────────────────────────────────────────────────────────────────────

EXPORT_PRICE_EUR = 50  # cents (Stripe EUR minimum), removes watermark + logo


def export_page(request):
    """The /export/ landing page, shows filter UI and watermarked preview."""
    return render(request, "export.html", {
        "stripe_publishable_key": settings.STRIPE_SECRET_KEY.replace("sk_", "pk_") if settings.STRIPE_SECRET_KEY else "",
        # GA4 ecommerce events report value in major units, Stripe charges in cents.
        "export_price_eur": f"{EXPORT_PRICE_EUR / 100:.2f}",
    })


# Every parameter that survives into the PAID download. The preview is rendered
# straight from the query string, but the paid file is rebuilt later from this token,
# so anything missing here is SILENTLY DROPPED and the customer gets a different map
# from the one they previewed and bought.
#
# That is not hypothetical. `uefa` was added for the continental maps and never added
# here, so paying for a Conference League map returned every ground in Europe — about
# a thousand clubs instead of thirty-two. Six more were missing with it: national_only,
# tiles, dot_color, surface_known, and the size/style aliases.
#
# test_export_token_keys asserts this covers every key _parse_export_params reads, so
# the next parameter added without touching this list fails the build instead of a
# customer's download.
_EXPORT_TOKEN_KEYS = {
    "country", "league", "ownership", "surface", "surface_known", "stadium_type",
    "uefa", "national", "national_only",
    "color_by", "ring_by", "no_badges", "dot_color",
    "style", "style_key", "size", "size_key", "tiles",
    "title", "subtitle", "labels",
    "north", "legend", "scale", "spotlight", "logo", "bg_color", "inset", "inset_box",
    "inset_size", "inset_corner", "label_pos", "badge_bg",
    "islands",
    "label_size", "label_color", "badge_size", "tournament", "tstatus",
    "layer", "dstatus",
}


@require_POST
def export_checkout(request):
    """Create a Stripe Checkout Session and redirect the user to it."""
    if not settings.STRIPE_SECRET_KEY:
        return JsonResponse({"error": "Stripe not configured."}, status=503)

    try:
        body = json.loads(request.body)
    except Exception:
        return JsonResponse({"error": "Invalid JSON."}, status=400)

    filters = {k: v for k, v in body.items() if k in _EXPORT_TOKEN_KEYS}
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
                        "name": "Stadium map, clean version",
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

    # Persist token, paid=False until webhook confirms. If this write fails,
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
    """Stripe webhook, reliable second confirmation path. On
    checkout.session.completed it marks the token paid, and UPSERTS it (creates
    from session metadata) if the checkout-time write was lost, so the download
    works even if the success page never loaded."""
    log = logging.getLogger(__name__)
    payload = request.body
    sig    = request.META.get("HTTP_STRIPE_SIGNATURE", "")
    secret = settings.STRIPE_WEBHOOK_SECRET

    if not secret:
        log.error("export_webhook: STRIPE_WEBHOOK_SECRET not set, ignoring event")
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
            # Token row missing (checkout write lost), recreate it from metadata
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
    """Redirect from Stripe success URL, find or create token, show download page."""
    log = logging.getLogger(__name__)
    session_id = request.GET.get("session_id", "")
    if not session_id:
        return redirect("italiastadiaapp:export_page")

    stripe.api_key = settings.STRIPE_SECRET_KEY

    # 1) The token is normally created at checkout time. Look it up first, this
    #    does NOT depend on Stripe being reachable.
    token_obj = ExportToken.objects.filter(stripe_session=session_id).first()

    # 2) Verify payment with Stripe directly (webhook may not have fired). Retry a
    #    couple of times, a transient failure (e.g. during a deploy) must not turn
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
            "msg": "We couldn't verify your session just now. Your payment is safe, "
                   "please refresh in a few seconds, or contact support with your Stripe receipt."
        })

    # Sync paid status from Stripe if the webhook was delayed
    if not token_obj.paid and stripe_session is not None and stripe_session.payment_status == "paid":
        token_obj.paid = True
        token_obj.save(update_fields=["paid"])

    if not token_obj.paid:
        return render(request, "export_error.html", {
            "msg": "Payment not confirmed yet, please wait a few seconds and refresh this page."
        })

    return render(request, "export_success.html", {
        "token": str(token_obj.token),
        "export_price_eur": f"{EXPORT_PRICE_EUR / 100:.2f}",
        "stripe_session": session_id,
    })


def _render_export_png(token_obj):
    """Generate the PNG for an ExportToken and return raw bytes."""
    filters = json.loads(token_obj.filters_json)
    if filters.get("size_key") == "4k":
        filters["size_key"] = "hd"   # cap to HD, free tier 512 MB RAM limit

    class _FakeGET:
        def get(self, key, default=""):
            return filters.get(key, default)

    class _FakeRequest:
        GET = _FakeGET()

    params = _parse_export_params(_FakeRequest())
    params["logo"] = False   # paid version is CLEAN, no logo, no watermark
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

    already_used_msg = ("This download link has already been used. Check your email, "
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
                    ",  Stadiums of Europe\n"
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
        .exclude(league__hidden=True)         # incomplete divisions aren't offered
        .exclude(stadium__city__country="")
        .values_list("stadium__city__country", "league__name")
        # NOT distinct: the rows are counted per club below to decide which country
        # runs each league. Collapsing them makes every cross-border league a 1-1
        # tie, which is exactly how one club in Oswestry put the Cymru Premier in
        # England's dropdown.
    )
    # Offer a league only under the country that RUNS it, decided by where most of
    # its clubs' grounds are.
    #
    # Grouping on the stadium's country alone put the Cymru Premier in England's
    # dropdown, because The New Saints play at Park Hall in Oswestry -- one Welsh
    # club, one English ground, and the whole Welsh league appeared under England.
    # It is not an isolated case: Cardiff, Swansea and Wrexham put the EFL
    # Championship under Wales, Vaduz put the Swiss Super League under
    # Liechtenstein, Derry City put the League of Ireland under Northern Ireland,
    # and FC Andorra put the Segunda División under Andorra. Every one of those
    # selections produces a map of two or three clubs that nobody wants.
    #
    # Deciding by majority rather than by League.country keeps the keys as
    # `city.country` free text, which the export filter matches on -- switching to
    # the Country model's name would break countries whose two spellings differ
    # ("Czechia" vs "Czech Republic"), the exact trap the docstring warns about.
    from collections import Counter, defaultdict
    homes = defaultdict(Counter)
    leagues_set = set()
    for country, league_name in rows:
        if not country or not league_name:
            continue
        leagues_set.add(league_name)
        homes[league_name][country] += 1

    leagues_by_country = {}
    for league_name, counts in homes.items():
        top = max(counts.values())
        # a tie means the league genuinely straddles a border; list it under each
        for country in (c for c, n in counts.items() if n == top):
            leagues_by_country.setdefault(country, []).append(league_name)
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

    # The three European club competitions belong in the same picker, because to
    # anyone using the page they are simply more tournaments. They are NOT stored
    # the same way: Euro 2028 lives in Stadium.tournaments (a JSON list on the
    # ground), while these live on Team.european_competition (a property of the
    # CLUB, since a club carries its competition to whatever ground it plays at).
    # Two different filters, one control — so the slug is prefixed and the page
    # sends it as `uefa=` rather than `tournament=`.
    #
    # Only offered once clubs actually carry the field. It stays empty until the
    # play-offs resolve, and an empty "Champions League" option would render a map
    # with nothing on it.
    _uefa_present = set(
        Team.objects.exclude(european_competition="")
        .exclude(european_competition__isnull=True)
        .values_list("european_competition", flat=True).distinct()
    )
    for code in ("UCL", "UEL", "UECL"):
        if code in _uefa_present:
            tournaments.append({
                "slug": f"uefa:{code}",
                "label": f"UEFA {_UEFA_LABELS[code]} {CURRENT_SEASON.replace('/20', '/')}",
            })
    if len(_uefa_present & {"UCL", "UEL", "UECL"}) > 1:
        tournaments.append({
            "slug": "uefa:ANY",
            "label": f"All European competitions {CURRENT_SEASON.replace('/20', '/')}",
        })

    return JsonResponse({
        "countries":          list(countries),
        "leagues":            sorted(leagues_set),
        "leagues_by_country": leagues_by_country,
        "tournaments":        tournaments,
        "dev_statuses": [
            {"value": s, "label": _DEV_STATUS_LABEL[s]} for s in _DEV_STATUSES
        ],
    })
