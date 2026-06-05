#!/usr/bin/env python
"""
validate_wiki_urls.py — Pre-flight checker for Wikipedia URLs in league JSON files.

Usage:
    python scripts/validate_wiki_urls.py scripts/data/urls_ekstraklasa.json
    python scripts/validate_wiki_urls.py scripts/data/urls_la_liga.json --timeout 10

Checks every `wikipedia_url` field in the JSON (both team-level and
stadium-level) by sending a HEAD request and following redirects.
Flags any URL that:
  - Returns HTTP 4xx or 5xx
  - Redirects to the Wikipedia "article does not exist" page

Exit codes:
  0 — all URLs valid
  1 — one or more URLs are broken (scraper should NOT be run)
"""

import argparse
import io
import json
import sys
import time
from pathlib import Path
from urllib.parse import unquote
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

# Force UTF-8 on Windows consoles that default to cp1252
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
else:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

# Wikipedia signals a missing article with this path prefix
MISSING_ARTICLE_PATH = "/w/index.php"

HEADERS = {
    "User-Agent": (
        "ItalianStadiaBot/1.0 (https://italianstadia-2.onrender.com; "
        "stadium-map data validation; contact: destavola.marco@gmail.com)"
    )
}

DELAY = 0.5  # seconds between requests — be polite to Wikipedia


def collect_urls(data: dict) -> list[tuple[str, str]]:
    """Return [(label, url), ...] for every wikipedia_url in the JSON."""
    results = []
    league_name = data.get("league", {}).get("name", "?")

    for team in data.get("teams", []):
        team_name = team.get("name", "?")

        if url := team.get("wikipedia_url"):
            results.append((f"[{league_name}] Team: {team_name}", url))

        stadium = team.get("stadium", {})
        if stadium:
            stadium_name = stadium.get("name", "?")
            if url := stadium.get("wikipedia_url"):
                results.append((f"[{league_name}] Stadium: {stadium_name} ({team_name})", url))

            city = stadium.get("city", {})
            if city:
                city_name = city.get("name", "?")
                if url := city.get("wikipedia_url"):
                    results.append((f"[{league_name}] City: {city_name}", url))

    return results


def check_url(url: str, timeout: int) -> tuple[bool, str]:
    """
    Returns (ok: bool, message: str).
    ok=True means the article exists and is reachable.
    """
    try:
        req = Request(url, method="HEAD", headers=HEADERS)
        with urlopen(req, timeout=timeout) as resp:
            final_url = resp.geturl()
            status = resp.status

            # Wikipedia redirects missing articles to /w/index.php?title=...&action=edit
            if MISSING_ARTICLE_PATH in final_url and "action=edit" in final_url:
                return False, f"HTTP {status} but redirected to 'article not found': {final_url}"

            if status >= 400:
                return False, f"HTTP {status}"

            return True, f"HTTP {status}"

    except HTTPError as e:
        return False, f"HTTP {e.code} {e.reason}"
    except URLError as e:
        return False, f"URL error: {e.reason}"
    except Exception as e:  # noqa: BLE001
        return False, f"Error: {e}"


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate Wikipedia URLs in a league JSON file")
    parser.add_argument("json_file", help="Path to urls_<league>.json")
    parser.add_argument("--timeout", type=int, default=15, help="HTTP timeout in seconds (default: 15)")
    parser.add_argument("--skip-cities", action="store_true", help="Skip city Wikipedia URL checks")
    args = parser.parse_args()

    json_path = Path(args.json_file)
    if not json_path.exists():
        print(f"ERROR: File not found: {json_path}", file=sys.stderr)
        return 1

    with json_path.open(encoding="utf-8") as f:
        data = json.load(f)

    all_urls = collect_urls(data)
    if args.skip_cities:
        all_urls = [(label, url) for label, url in all_urls if "City:" not in label]

    league = data.get("league", {}).get("name", json_path.stem)
    print(f"\n{'='*60}")
    print(f"Validating Wikipedia URLs — {league} ({json_path.name})")
    print(f"Total URLs to check: {len(all_urls)}")
    print(f"{'='*60}\n")

    failures: list[tuple[str, str, str]] = []
    for i, (label, url) in enumerate(all_urls, 1):
        ok, msg = check_url(url, args.timeout)
        status_icon = "OK " if ok else "FAIL"
        decoded = unquote(url)
        print(f"  [{i:>3}/{len(all_urls)}] {status_icon}  {label}")
        if not ok:
            print(f"            URL: {decoded}")
            print(f"            Reason: {msg}")
            failures.append((label, url, msg))
        if i < len(all_urls):
            time.sleep(DELAY)

    print(f"\n{'='*60}")
    if failures:
        print(f"RESULT: {len(failures)} BROKEN URL(s) found — DO NOT run the scraper yet!\n")
        for label, url, msg in failures:
            print(f"  BROKEN  {label}")
            print(f"          {unquote(url)}")
            print(f"          {msg}\n")
        print("Fix these URLs in the JSON file, then re-run this validator.")
        print(f"{'='*60}\n")
        return 1
    else:
        print(f"RESULT: All {len(all_urls)} URLs are valid — safe to run the scraper.")
        print(f"{'='*60}\n")
        return 0


if __name__ == "__main__":
    sys.exit(main())
