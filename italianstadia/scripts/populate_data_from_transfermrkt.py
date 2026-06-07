import json
import requests
from bs4 import BeautifulSoup
import django
import os
import sys
import logging
import re
import time
from datetime import datetime, date
from urllib.parse import urljoin
import logging


from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.by import By
from selenium.common.exceptions import TimeoutException, NoSuchElementException
from webdriver_manager.chrome import ChromeDriverManager

from urllib.parse import urljoin

# --------------------------------------------------
# Utils functions
# --------------------------------------------------


HEADERS = {
    "User-Agent": "ItalianStadiaBot/1.0 (learning project; contact: example@example.com)"
}


def get_soup(url):
    try:
        response = requests.get(url, headers=HEADERS, timeout=20)
        response.raise_for_status()
        return BeautifulSoup(response.text, "html.parser")
    except Exception as e:
        logging.error(f"Error loading Wikipedia page {url}: {e}")
        return None


def clean_text(value):
    if not value:
        return None

    value = re.sub(r"\[\d+\]", "", value)
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def get_infobox(soup):
    if not soup:
        return None

    return (
        soup.find("table", class_="infobox")
        or soup.find("table", class_="vcard")
        or soup.find("table", class_="infobox vcard")
    )


def get_infobox_value(soup, labels):
    infobox = get_infobox(soup)
    if not infobox:
        return None

    labels = [label.lower() for label in labels]

    for row in infobox.find_all("tr"):
        header = row.find("th")
        data = row.find("td")

        if not header or not data:
            continue

        header_text = clean_text(header.get_text(" ", strip=True))
        if not header_text:
            continue

        header_text_lower = header_text.lower()

        if any(label in header_text_lower for label in labels):
            return clean_text(data.get_text(" ", strip=True))

    return None


def extract_first_int(value):
    if not value:
        return None

    # captures 1,362,863 or 1362863, but avoids 181.67
    match = re.search(r"\d{1,3}(?:,\d{3})+|\d{4,}", value)

    if not match:
        return None

    return int(match.group(0).replace(",", ""))
    #
def extract_year(value):
    if not value:
        return None

    match = re.search(r"\b(18|19|20)\d{2}\b", value)
    return int(match.group(0)) if match else None


# --------------------------------------------------
# Django setup
# --------------------------------------------------

project_path = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
sys.path.append(project_path)

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "italianstadia.settings")
django.setup()

from italiastadiaapp.models import City, Country, League, Stadium, Team


# --------------------------------------------------
# Logging
# --------------------------------------------------

def log_field(entity, name, field, value, source=None, reason=None):
    if value not in [None, "", 0]:
        logging.info(f"[{entity}: {name}] {field} → {value} ({source})")
    else:
        logging.warning(
            f"[{entity}: {name}] {field} → NOT FOUND"
            + (f" ({reason})" if reason else "")
        )

log_file = "scraping_transfermarkt.log"

if os.path.exists(log_file):
    os.remove(log_file)

logging.basicConfig(
    filename=log_file,
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)


# --------------------------------------------------
# League resolution
# --------------------------------------------------

def resolve_league(config):
    """get_or_create Country and League from the JSON league config block."""
    country, _ = Country.objects.get_or_create(
        name=config["country"],
        defaults={"code": config["country_code"]},
    )
    league, _ = League.objects.get_or_create(
        name=config["name"],
        country=country,
        defaults={"division_level": config["division_level"]},
    )
    return league


# --------------------------------------------------
# Helpers
# --------------------------------------------------

def create_driver():
    service = Service(ChromeDriverManager().install())
    return webdriver.Chrome(service=service)

def extract_city_population(soup):
    if not soup:
        logging.warning("[City population] No soup provided")
        return None

    infobox = get_infobox(soup)

    if not infobox:
        logging.warning("[City population] No infobox found")
        return None

    candidate_population = None

    for row in infobox.find_all("tr"):
        header = row.find("th")
        data = row.find("td")

        if not header or not data:
            continue

        header_text = clean_text(header.get_text(" ", strip=True))
        data_text = clean_text(data.get_text(" ", strip=True))

        if not header_text or not data_text:
            continue

        header_lower = header_text.lower()
        data_lower = data_text.lower()

        logging.info(f"[City population DEBUG] row header='{header_text}' value='{data_text}'")

        # Skip obvious non-population values
        if any(word in data_lower for word in ["km", "sq mi", "/km", "billion", "utc", "cfa"]):
            continue

        if any(word in header_lower for word in ["density", "rank", "demonym", "time zone", "postal", "area code"]):
            continue

        # Skip metro if you want city/comune population, not metro population
        if "metro" in header_lower:
            continue

        number = extract_first_int(data_text)

        if not number:
            continue

        # City populations should usually be at least 1,000
        if number < 1000:
            continue

        # Best case: explicit population row
        if "population" in header_lower:
            logging.info(f"[City population] Found from explicit population row '{header_text}': {number}")
            return number

        # Common Wikipedia case: under Population section, row header is just Comune/Municipality
        if any(word in header_lower for word in ["comune", "municipality", "city", "total"]):
            candidate_population = number
            logging.info(f"[City population] Candidate from row '{header_text}': {number}")

    if candidate_population:
        logging.info(f"[City population] Found from municipality/comune candidate: {candidate_population}")
        return candidate_population

    logging.warning("[City population] NOT FOUND in infobox")
    return None

def accept_consent_if_present(driver):
    """Handle Transfermarkt's Sourcepoint consent dialog.

    Strategy:
    1. Check at page level first (fast — no iframe switch).
    2. If not found, scan the first 5 iframes only (consent frame is
       always near the top; skipping the rest avoids 50-100 s delays on
       ad-heavy pages).
    3. After any successful click, switch back robustly and return
       immediately — never continue iterating because the consent click
       often navigates the page and invalidates the window handle.
    """
    CONSENT_XPATH = "//button[contains(text(), 'Accept & continue')]"

    # 1. Page-level check (no iframe needed)
    try:
        btn = WebDriverWait(driver, 3).until(
            EC.element_to_be_clickable((By.XPATH, CONSENT_XPATH))
        )
        btn.click()
        logging.info("Accepted consent popup (page level).")
        time.sleep(2)
        return
    except Exception:
        pass

    # 2. Iframe scan — cap at 5 iframes, 2 s timeout each
    try:
        iframes = driver.find_elements(By.TAG_NAME, "iframe")[:5]
    except Exception:
        return

    for iframe in iframes:
        # Switch into this iframe (skip if handle is stale)
        try:
            driver.switch_to.frame(iframe)
        except Exception:
            continue

        clicked = False
        try:
            btn = WebDriverWait(driver, 2).until(
                EC.element_to_be_clickable((By.XPATH, CONSENT_XPATH))
            )
            btn.click()
            clicked = True
            logging.info("Accepted consent popup (iframe).")
        except Exception:
            pass
        finally:
            # Guard: page may have navigated on click → switch_to can throw
            try:
                driver.switch_to.default_content()
            except Exception:
                pass

        if clicked:
            time.sleep(2)
            return  # Never iterate further after a successful click


def clean_int(value):
    if not value:
        return None

    cleaned = re.sub(r"\D", "", value)
    if not cleaned:
        return None
    result = int(cleaned)
    return result if result else None

def extract_coordinates_from_wikipedia(soup):
    if not soup:
        logging.error("[Wikipedia] No soup provided for coordinates")
        return None, None

    # Method 1: geo microformat
    geo = soup.find(class_="geo")
    if geo:
        text = geo.get_text(strip=True)

        if ";" in text:
            parts = text.split(";")
        elif "," in text:
            parts = text.split(",")
        else:
            parts = None

        if parts and len(parts) >= 2:
            try:
                return float(parts[0].strip()), float(parts[1].strip())
            except ValueError:
                pass

    else:
        logging.info("[Wikipedia] geo class not found")

    # Method 2: latitude / longitude spans
    lat = soup.find(class_="latitude")
    lon = soup.find(class_="longitude")

    if lat and lon:
        try:
            return dms_to_decimal(lat.get_text(strip=True)), dms_to_decimal(lon.get_text(strip=True))
        except Exception:
            logging.info("[Wikipedia] Error parsing DMS coordinates")
            pass

    else:
        logging.info("[Wikipedia] latitude/longitude span not found")

    # Method 3: coordinates link
    coord_link = soup.find("a", href=re.compile(r"geohack"))
    if coord_link:
        href = coord_link.get("href", "")

        match = re.search(r"params=([0-9\._NSWE-]+)", href)
        if match:
            try:
                return parse_geohack_params(match.group(1))
            except Exception:
                logging.info("[Wikipedia] Error parsing geohack parameters")
    logging.warning(f"[Wikipedia] Coordinates not found for {soup.title.string if soup else 'unknown'}")
    logging.warning("[Wikipedia] All coordinate methods failed")
    return None, None


def dms_to_decimal(value):
    value = value.replace("−", "-")

    direction = None
    for d in ["N", "S", "E", "W"]:
        if d in value:
            direction = d
            value = value.replace(d, "")

    nums = re.findall(r"[-+]?\d+(?:\.\d+)?", value)

    if not nums:
        return None

    degrees = float(nums[0])
    minutes = float(nums[1]) if len(nums) > 1 else 0
    seconds = float(nums[2]) if len(nums) > 2 else 0

    decimal = degrees + minutes / 60 + seconds / 3600

    if direction in ["S", "W"]:
        decimal *= -1

    return decimal


def parse_geohack_params(params):
    parts = params.split("_")

    lat_deg = float(parts[0])
    lat_min = float(parts[1]) if len(parts) > 1 else 0
    lat_sec = float(parts[2]) if len(parts) > 2 else 0
    lat_dir = parts[3]

    lon_deg = float(parts[4])
    lon_min = float(parts[5]) if len(parts) > 5 else 0
    lon_sec = float(parts[6]) if len(parts) > 6 else 0
    lon_dir = parts[7]

    lat = lat_deg + lat_min / 60 + lat_sec / 3600
    lon = lon_deg + lon_min / 60 + lon_sec / 3600

    if lat_dir == "S":
        lat *= -1
    if lon_dir == "W":
        lon *= -1

    return lat, lon


_BADGE_PATTERNS = (
    "badge", "crest", "emblem", "logo", "wappen", "escudo", "shield", "blason",
)

_BAD_BADGE_PATTERNS = (
    "placeholder", "flag", "arrow", "default", "no-picture", "no_picture",
)

def _is_badge_image(src):
    src_lower = src.lower()
    return any(p in src_lower for p in _BADGE_PATTERNS)


_WIKIMEDIA_THUMB_RE = re.compile(
    r'^((?:https?:)?//upload\.wikimedia\.org/wikipedia/\w+)/thumb(/\w/\w{2}/.+?)/\d+px-[^/]+$'
)

def _wikimedia_fullres(url):
    """Convert a Wikimedia thumbnail URL to its full-resolution equivalent."""
    if not url:
        return url
    m = _WIKIMEDIA_THUMB_RE.match(url)
    return (m.group(1) + m.group(2)) if m else url


def _is_valid_badge_url(url):
    """Return False for known placeholder/icon/fallback image URLs."""
    if not url:
        return False
    url_lower = url.lower()
    return not any(p in url_lower for p in _BAD_BADGE_PATTERNS)


# --------------------------------------------------
# Wikidata ownership cross-check (second source)
# --------------------------------------------------

def fetch_wikidata_ownership(wikipedia_url):
    """
    Query Wikidata for the 'owned by' (P127) property of a stadium.
    Uses the Wikipedia page to locate the Wikidata entity, then resolves P127 labels.

    Returns the owner name string (English label) or None if not found.
    This is used as a second-source cross-check against Wikipedia's infobox owner field.
    """
    if not wikipedia_url:
        return None

    try:
        from urllib.parse import urlparse, unquote
        host = urlparse(wikipedia_url).netloc        # e.g. en.wikipedia.org
        path = urlparse(wikipedia_url).path          # /wiki/Allianz_Arena
        title = unquote(path.split("/wiki/")[-1])
        api = f"https://{host}/w/api.php"

        # Step 1: get the Wikidata entity ID (Q-number) linked to this Wikipedia page
        resp = requests.get(api, params={
            "action": "query",
            "titles": title,
            "prop": "pageprops",
            "ppprop": "wikibase_item",
            "format": "json",
        }, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        pages = resp.json().get("query", {}).get("pages", {})
        entity_id = None
        for page in pages.values():
            entity_id = page.get("pageprops", {}).get("wikibase_item")
            break

        if not entity_id:
            logging.info(f"[Wikidata] No entity ID for '{title}'")
            return None

        # Step 2: fetch P127 (owned by) claims for the entity
        time.sleep(0.3)
        resp2 = requests.get("https://www.wikidata.org/w/api.php", params={
            "action": "wbgetentities",
            "ids": entity_id,
            "props": "claims",
            "format": "json",
        }, headers=HEADERS, timeout=15)
        resp2.raise_for_status()
        entity = resp2.json().get("entities", {}).get(entity_id, {})
        p127_claims = entity.get("claims", {}).get("P127", [])

        if not p127_claims:
            logging.info(f"[Wikidata] No P127 (owned by) for entity {entity_id} ('{title}')")
            return None

        # Step 3: resolve each owner entity to its English label
        owner_ids = []
        for claim in p127_claims:
            snak = claim.get("mainsnak", {})
            if snak.get("datatype") == "wikibase-item":
                oid = snak.get("datavalue", {}).get("value", {}).get("id")
                if oid:
                    owner_ids.append(oid)

        if not owner_ids:
            return None

        time.sleep(0.3)
        resp3 = requests.get("https://www.wikidata.org/w/api.php", params={
            "action": "wbgetentities",
            "ids": "|".join(owner_ids[:5]),
            "props": "labels",
            "languages": "en",
            "format": "json",
        }, headers=HEADERS, timeout=15)
        resp3.raise_for_status()
        owner_labels = []
        for oid in owner_ids:
            oe = resp3.json().get("entities", {}).get(oid, {})
            label = oe.get("labels", {}).get("en", {}).get("value", "")
            if label:
                owner_labels.append(label)

        result = " / ".join(owner_labels) if owner_labels else None
        if result:
            logging.info(f"[Wikidata] Owner for '{title}': {result}")
        return result

    except Exception as e:
        logging.error(f"[Wikidata] fetch_wikidata_ownership failed for '{wikipedia_url}': {e}")
        return None


# --------------------------------------------------
# Wikimedia Commons multi-image fetch
# --------------------------------------------------

# File names containing these strings are decorative / non-photo and should be skipped
_COMMONS_SKIP = (
    "flag_of", "coat_of", "arms_of", "_logo", "badge", "crest", "emblem",
    "icon", "commons-logo", "wikidata", "wikisource", "wikivoyage",
    "mediawiki", "wikipedia-logo", "red_question", "question_book",
    "ambox", "portal-", "stub", "pictogram", "silhouette",
    "locator", "location", "map_of", "_map.", "carte_", "karte_",
    "kit_", "_kit.", "jersey", "maillot",
)

_HTML_TAG_RE = re.compile(r"<[^>]+>")


def _strip_html(text):
    """Remove HTML tags from a string (used for Wikimedia attribution fields)."""
    return _HTML_TAG_RE.sub("", text or "").strip()


def _wiki_api_base(wikipedia_url):
    """Return the Wikipedia API base URL for the language domain in the given URL."""
    from urllib.parse import urlparse
    host = urlparse(wikipedia_url).netloc  # e.g. en.wikipedia.org
    return f"https://{host}/w/api.php"


def _wiki_page_title(wikipedia_url):
    """Extract the page title from a Wikipedia URL."""
    from urllib.parse import urlparse, unquote
    path = urlparse(wikipedia_url).path  # /wiki/Voith-Arena
    return unquote(path.split("/wiki/")[-1])


def fetch_commons_images(wikipedia_url, primary_image_url=None, max_images=4):
    """
    Query the Wikipedia API to find additional high-quality images for a stadium page.
    Returns a list of {"url": str, "credit": str} dicts (up to max_images).

    Strategy:
      1. GET all File: entries listed on the Wikipedia page (prop=images).
      2. Filter out decorative files (flags, logos, maps, SVG icons).
      3. Fetch imageinfo (URL + author/license) for the survivors.
      4. Skip images smaller than 80 KB (tiny icons).
      5. Skip the file that is already stored as the primary image_url.
    """
    if not wikipedia_url:
        return []

    api = _wiki_api_base(wikipedia_url)
    title = _wiki_page_title(wikipedia_url)
    results = []

    try:
        # --- Step 1: get list of File: entries on the page ---
        resp = requests.get(api, params={
            "action": "query",
            "titles": title,
            "prop": "images",
            "imlimit": 30,
            "format": "json",
        }, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        data = resp.json()

        pages = data.get("query", {}).get("pages", {})
        file_names = []
        for page in pages.values():
            for img in page.get("images", []):
                name = img.get("title", "")  # e.g. "File:Voith-Arena_Innen.jpg"
                name_lower = name.lower()
                # Skip SVG, GIF and known decorative patterns
                if name_lower.endswith(".svg") or name_lower.endswith(".gif"):
                    continue
                if any(p in name_lower for p in _COMMONS_SKIP):
                    continue
                file_names.append(name)

        if not file_names:
            logging.info(f"[Commons] No candidate images for '{title}'")
            return []

        # --- Step 2: batch-fetch imageinfo (up to 50 titles per call) ---
        time.sleep(0.5)  # be polite to the API
        resp2 = requests.get(api, params={
            "action": "query",
            "titles": "|".join(file_names[:20]),  # API max 50, we take 20
            "prop": "imageinfo",
            "iiprop": "url|extmetadata|size",
            "format": "json",
        }, headers=HEADERS, timeout=20)
        resp2.raise_for_status()
        data2 = resp2.json()

        # Build a set of the primary image filename for dedup
        primary_fname = ""
        if primary_image_url:
            primary_fname = primary_image_url.split("/")[-1].lower()

        for page in data2.get("query", {}).get("pages", {}).values():
            if len(results) >= max_images:
                break
            ii = page.get("imageinfo", [{}])[0]
            url = ii.get("url", "")
            size = ii.get("size", 0)

            if not url:
                continue
            # Skip tiny files (icons, watermarks)
            if size and (size < 80_000 or size > 5_000_000):  # skip tiny icons and huge raw files
                continue
            # Skip if same file as primary image
            if primary_fname and url.split("/")[-1].lower() == primary_fname:
                continue

            # Build credit string from extmetadata
            meta = ii.get("extmetadata", {})
            author = _strip_html(meta.get("Artist", {}).get("value", ""))
            license_name = meta.get("LicenseShortName", {}).get("value", "")
            credit_parts = [p for p in [author, "Wikimedia Commons", license_name] if p]
            credit = " / ".join(credit_parts)

            results.append({"url": _wikimedia_fullres(url), "credit": credit})
            logging.info(f"[Commons] Added image: {url} ({size} bytes)")

    except Exception as e:
        logging.error(f"[Commons] fetch_commons_images failed for '{wikipedia_url}': {e}")

    logging.info(f"[Commons] Found {len(results)} extra images for '{title}'")
    return results


def extract_team_id_from_url(url):
    """Extract numeric team ID from a Transfermarkt team URL (/verein/<id>)."""
    match = re.search(r"/verein/(\d+)", url or "")
    return match.group(1) if match else None


def scrape_team_badge(team_url, driver):
    """
    Fetch the club crest from Transfermarkt.

    Priority:
      1. Akamai CDN wappen URL built from team_id (fast, no page parse needed)
      2. .vereins-wappen img DOM element on already-open Selenium page
      3. Any img whose data-src contains 'wappen'
    Returns None if nothing valid found.
    """
    team_id = extract_team_id_from_url(team_url)

    # Method 1: deterministic CDN URL
    if team_id:
        cdn_url = f"https://tmssl.akamaized.net/images/wappen/head/{team_id}.png"
        try:
            resp = requests.get(cdn_url, headers=HEADERS, timeout=10)
            if resp.status_code == 200 and len(resp.content) >= 500 and _is_valid_badge_url(cdn_url):
                logging.info(f"[Badge] CDN wappen OK: {cdn_url} ({len(resp.content)} bytes)")
                return cdn_url
            else:
                logging.info(f"[Badge] CDN wappen skipped: status={resp.status_code} size={len(resp.content)}")
        except Exception as e:
            logging.info(f"[Badge] CDN wappen request failed: {e}")

    # Method 2: .vereins-wappen img on the Transfermarkt page
    try:
        badge_img = driver.find_element(By.CSS_SELECTOR, ".vereins-wappen img")
        src = badge_img.get_attribute("src") or badge_img.get_attribute("data-src") or ""
        if src and _is_valid_badge_url(src):
            logging.info(f"[Badge] DOM .vereins-wappen: {src}")
            return src
    except Exception:
        pass

    # Method 3: any img whose data-src references the wappen CDN
    try:
        badge_img = driver.find_element(By.CSS_SELECTOR, "img[data-src*='wappen']")
        src = badge_img.get_attribute("data-src") or badge_img.get_attribute("src") or ""
        if src and _is_valid_badge_url(src):
            logging.info(f"[Badge] DOM data-src wappen: {src}")
            return src
    except Exception:
        pass

    logging.warning(f"[Badge] No valid badge found for team_url={team_url}")
    return None


def extract_wikipedia_image(soup, page_url, exclude_badges=False):
    if not soup:
        logging.error("[Wikipedia] No soup provided for image extraction")
        return None

    infobox = get_infobox(soup)

    # Method 1: image from infobox
    if infobox:
        for img in infobox.find_all("img"):
            src = img.get("src", "")
            if not src or (exclude_badges and _is_badge_image(src)):
                continue
            if src.startswith("//"):
                return _wikimedia_fullres("https:" + src)
            return _wikimedia_fullres(urljoin(page_url, src))
    else:
        logging.info("[Wikipedia] No infobox found for image extraction")

    # Method 2: Open Graph image (usually a good photo)
    og_image = soup.find("meta", property="og:image")
    if og_image and og_image.get("content"):
        content = og_image["content"]
        if not (exclude_badges and _is_badge_image(content)):
            return _wikimedia_fullres(content)
    else:
        logging.info("[Wikipedia] No Open Graph image found")

    # Method 3: first useful page image
    for img in soup.find_all("img"):
        src = img.get("src", "")

        if not src:
            continue

        if "static/images" in src or (exclude_badges and _is_badge_image(src)):
            continue

        if src.startswith("//"):
            return _wikimedia_fullres("https:" + src)

        return _wikimedia_fullres(urljoin(page_url, src))

    logging.info("[Wikipedia] No useful images found")
    return None

def scrape_wikipedia_summary_and_image(url):
    if not url or not url.startswith("http"):
        return {
            "description": None,
            "image_url": None,
        }

    try:
        response = requests.get(url, timeout=15, headers={
            "User-Agent": "Mozilla/5.0"
        })
        soup = BeautifulSoup(response.text, "html.parser")

        description = None
        image_url = None

        # Description
        paragraphs = soup.select("div.mw-parser-output > p")
        for p in paragraphs:
            text = p.get_text(" ", strip=True)
            if len(text) > 80:
                description = text
                break

        # Method 1: OpenGraph image, often easiest
        og_image = soup.find("meta", property="og:image")
        if og_image and og_image.get("content"):
            image_url = _wikimedia_fullres(og_image["content"])

        # Method 2: infobox image fallback
        if not image_url:
            image = soup.select_one("table.infobox img")
            if image and image.get("src"):
                image_url = image["src"]
                if image_url.startswith("//"):
                    image_url = "https:" + image_url
                elif image_url.startswith("/"):
                    image_url = "https://en.wikipedia.org" + image_url
                image_url = _wikimedia_fullres(image_url)

        return {
            "description": description,
            "image_url": image_url,
        }

    except Exception as e:
        logging.error(f"Error scraping Wikipedia metadata from {url}: {e}")
        return {
            "description": None,
            "image_url": None,
        }


# --------------------------------------------------
# City
# --------------------------------------------------

def scrape_city_from_wikipedia(wikipedia_url):
    soup = get_soup(wikipedia_url)

    if not soup:
        return {}

    population = extract_city_population(soup)

    return {
        "wikipedia_url": wikipedia_url,
        "population": population,
        "image_url": extract_wikipedia_image(soup, wikipedia_url),
    }

def first_valid(*values):
    for value in values:
        if value not in [None, "", 0, "Unknown"]:
            return value
    return None


def scrape_city(city_data, country="Unknown"):
    wikipedia_url = city_data.get("wikipedia_url")
    fallback_name = city_data.get("name")

    # 1. Structured Wikipedia scraping (your resilient function)
    wiki_data = scrape_city_from_wikipedia(wikipedia_url) if wikipedia_url else {}

    # 2. Extra metadata (description + image fallback)
    wiki_meta = scrape_wikipedia_summary_and_image(wikipedia_url) if wikipedia_url else {}

    # 3. Get page for name + country (safe)
    soup = get_soup(wikipedia_url)

    name = fallback_name
    country_from_infobox = None

    if soup:
        try:
            title = soup.find("h1", {"id": "firstHeading"})
            if title:
                name = title.get_text(strip=True)
        except Exception:
            logging.info(f"City name not found, using fallback: {fallback_name}")

        country_from_infobox = get_infobox_value(soup, ["country"])

    # 4. Merge values (priority logic)
    final_name = first_valid(name, fallback_name)
    final_population = wiki_data.get("population") or None
    final_country = first_valid(country_from_infobox, country) or country
    log_field("City", final_name, "population", final_population, "Wikipedia")
    log_field("City", final_name, "image", wiki_data.get("image_url"), "Wikipedia")

    # 5. Save
    city, created = City.objects.update_or_create(
        name=final_name,
        defaults={
            "population": final_population,
            "country": final_country,
            "wikipedia_url": wikipedia_url,
            "description": first_valid(wiki_meta.get("description")),
            "image_url": first_valid(
                wiki_data.get("image_url"),
                wiki_meta.get("image_url")
            ),
        }
    )

    logging.info(f"{'Created' if created else 'Updated'} city: {city.name}")
    return city


# --------------------------------------------------
# Stadium
# --------------------------------------------------

def extract_best_stadium_image(
    transfermarkt_soup=None,
    transfermarkt_url=None,
    wikipedia_soup=None,
    wikipedia_url=None,
):
    transfermarkt_image = None

    if transfermarkt_soup and transfermarkt_url:
        transfermarkt_image = extract_transfermarkt_stadium_image(
            transfermarkt_soup,
            transfermarkt_url
        )

    if transfermarkt_image:
        return transfermarkt_image

    if wikipedia_soup and wikipedia_url:
        return extract_wikipedia_image(wikipedia_soup, wikipedia_url, exclude_badges=True)

    return None


def extract_transfermarkt_stadium_image(soup, page_url):
    if not soup:
        return None

    # 1. Transfermarkt stadium/gallery slider image
    slider_img = soup.select_one("img.slider__img")

    if slider_img:
        src = slider_img.get("src") or slider_img.get("data-src")
        if src:
            if src.startswith("//"):
                return "https:" + src
            return urljoin(page_url, src)

    # 2. Any useful Transfermarkt photo image
    for img in soup.find_all("img"):
        src = img.get("src") or img.get("data-src") or ""

        if not src:
            continue

        src_lower = src.lower()

        if "images/foto" in src_lower:
            if src.startswith("//"):
                return "https:" + src
            return urljoin(page_url, src)

    # 3. Do NOT use og:image unless you want the Transfermarkt logo
    return None

def classify_ownership(owner_raw):
    if not owner_raw:
        return "UNKNOWN"

    text = owner_raw.lower()

    public_keywords = [
        # ── English ──────────────────────────────────────────────────────────
        "city of", "municipality", "municipal", "council", "government",
        "ministry",                # Ministry of Youth and Sports, etc.
        "region", "province", "metropolitan city", "district",
        "town of", "town council",
        "city council", "county council", "district council",
        "metropolitan borough", "london borough", "royal borough",
        "public authority", "public body", "national sports",
        "sports authority", "stadium authority",
        "agglomeration",
        # ── Italian ──────────────────────────────────────────────────────────
        "comune di", "comune", "comunale", "provincia", "città metropolitana",
        "regione ", "ministero", "ente pubblico",
        "sport e salute",          # Italian government sports agency
        "commune of", "commune di",
        # ── German (Germany / Austria / Switzerland) ─────────────────────────
        "stadt ", "stadtwerke", "stadtverwaltung", "stadtgemeinde",
        "gemeinde", "landkreis", "freistaat", "bundesland", "kommunal",
        "freie und hansestadt", "freie hansestadt", "hansestadt",
        "landeshauptstadt", "bezirksamt", "bezirk ", "regionalverband",
        # ── French (France / Belgium / Switzerland) ──────────────────────────
        "commune de", "mairie", "métropole",
        "ville de ", "ville d'",
        "agglomération", "agglomeration",
        "communauté", "communaute",
        "département", "région", "conseil général", "conseil régional",
        "grand paris", "grand lyon",
        # ── Spanish ──────────────────────────────────────────────────────────
        "ayuntamiento", "municipio", "diputación", "patronato municipal",
        "generalitat", "junta de ", "comunidad de", "consell",
        "consejo municipal",
        # ── Portuguese ───────────────────────────────────────────────────────
        "município", "câmara municipal", "câmara ", "câmara de",
        "junta de freguesia", "autarquia",
        "governo regional", "região autónoma",
        # ── Polish ───────────────────────────────────────────────────────────
        "miasto ",                 # miasto Warszawa, miasto Kraków …
        "miasto stołeczne",        # Miasto Stołeczne Warszawa
        "gmina ",                  # Gmina Miejska Kraków
        "urząd miejski",           # Urząd Miejski w …
        "województwo",             # voivodeship
        "powiat ",                 # county
        "skarb państwa",           # State Treasury
        # ── Dutch / Belgian (Flemish) ────────────────────────────────────────
        "gemeente ",               # Gemeente Amsterdam / Rotterdam
        "stad ",                   # Stad Gent / Stad Brugge (trailing space)
        " stad",                   # Göteborgs Stad / Antwerpse Stad (leading space)
        "stadsbestuur", "stadsgewest", "stadseigendom",
        "provinciaal", "provincie ",
        "gewest ",                 # Brussels Hoofdstedelijk Gewest
        # ── Turkish ──────────────────────────────────────────────────────────
        "belediye",                # municipality (all forms: büyükşehir belediyesi …)
        "büyükşehir",              # metropolitan municipality
        "il özel idaresi",         # special provincial administration
        "devlet ",                 # state (Turkish)
        "bakanlı",                 # ministry (bakanlık/bakanlığı — covers all inflected forms)
        # ── Nordic: Norwegian / Danish ───────────────────────────────────────
        "kommune",                 # Oslo Kommune / Københavns Kommune
        "fylke",                   # Norwegian county
        "amt ",                    # Danish county (historical, still used)
        # ── Swedish ──────────────────────────────────────────────────────────
        "stadsförvaltning", "stadsfastigheter",
        "landstinget", "landsting",
        "stockholms stad", "göteborgs stad", "malmö stad",  # explicit major cities
        # ── Finnish ──────────────────────────────────────────────────────────
        "kaupunki",                # city (Helsinki kaupunki …)
        "kunta ",                  # municipality
        # ── Czech / Slovak ───────────────────────────────────────────────────
        "město ",                  # Město Brno, Město Praha
        "statutární město",        # Statutární město Brno
        "obec ",                   # commune / village municipality
        "kraj ",                   # region (Jihomoravský kraj …)
        "krajský",
        # ── Romanian ─────────────────────────────────────────────────────────
        "primăria", "primărie",    # mayor's office / city hall
        "consiliu local",          # local council
        "județ",                   # county
        "municipiu",               # municipality
        "ministerul",              # ministry (Ministerul Transporturilor, Ministerul Tineretului …)
        # ── Croatian / Serbian / Bosnian ─────────────────────────────────────
        "grad ",                   # Grad Zagreb / Grad Beograd
        "gradska ",                # gradska skupština (city assembly) …
        "općina ",                 # municipality (Croatian)
        "skupština",               # assembly
        "kantona",                 # canton (Bosnia)
        # ── Hungarian ────────────────────────────────────────────────────────
        "város ",                  # Miskolc Város Önkormányzata …
        "önkormányzat",            # local government / municipality
        "fővárosi",                # Budapest metropolitan
        # ── Greek (transliterated) ───────────────────────────────────────────
        "dimos ",                  # δήμος → dimos (municipality)
        "dimou",                   # genitive form
    ]

    private_keywords = [
        # ── Club / sport entity patterns (multi-language) ────────────────────
        "football club", "fussball", "fußball", "calcio",
        "fc ", "ac ", "as ", "ss ", "ssc ", "us ", "club",
        # ── Generic company suffixes ─────────────────────────────────────────
        "s.p.a", "srl", "s.r.l.", "ltd", "llc", "group",
        "holding", "invest ", "property", "asset",
        # ── German company forms ─────────────────────────────────────────────
        "gmbh", "g.m.b.h", " ag,", "e.v.", "e. v.",
        # ── French / Spanish ─────────────────────────────────────────────────
        "s.a.", "sarl",
        # ── Spanish / Portuguese sports company ──────────────────────────────
        "s.a.d.", " sad,", "sociedad anónima",
        " lda.", " lda,",
        # ── Polish company forms ─────────────────────────────────────────────
        "sp. z o.o.", "spółka akcyjna",
        # ── Dutch company forms ──────────────────────────────────────────────
        " b.v.", " n.v.", " b.v,", " n.v,",
        # ── Nordic company forms ─────────────────────────────────────────────
        " ab ", " ab,", " oy ", " oy,", " a/s", " asa ",
        # ── Czech / Slovak company forms ─────────────────────────────────────
        " a.s.", " s.r.o.",
        # ── Belgian company forms ────────────────────────────────────────────
        " bvba", " cvba",
    ]

    has_public = any(keyword in text for keyword in public_keywords)

    if has_public:
        has_private = any(keyword in text for keyword in private_keywords)
        return "MIXED" if has_private else "PUBLIC"

    # owner_raw has a value but no public keyword → private by definition
    # (clubs owning their own stadium, unnamed holding companies, etc.)
    # UNKNOWN is reserved for missing/empty owner_raw only.
    return "PRIVATE"

def scrape_stadium_data(wikipedia_url=None, transfermarkt_url=None):
    wikipedia_soup = get_soup(wikipedia_url) if wikipedia_url else None
    transfermarkt_soup = get_soup(transfermarkt_url) if transfermarkt_url else None

    if not wikipedia_soup:
        return {}

    latitude, longitude = extract_coordinates_from_wikipedia(wikipedia_soup)

    capacity_raw = get_infobox_value(wikipedia_soup, ["capacity"])
    opened_raw = get_infobox_value(wikipedia_soup, ["opened", "built", "construction", "opened on"])
    address = get_infobox_value(wikipedia_soup, ["address", "location"])
    owner_raw = get_infobox_value(wikipedia_soup, ["owner"])

    return {
        "wikipedia_url": wikipedia_url,
        "capacity": extract_first_int(capacity_raw),
        "year_of_construction": extract_year(opened_raw),
        "address": address,
        "latitude": latitude,
        "longitude": longitude,
        "image_url": extract_best_stadium_image(
            transfermarkt_soup=transfermarkt_soup,
            transfermarkt_url=transfermarkt_url,
            wikipedia_soup=wikipedia_soup,
            wikipedia_url=wikipedia_url,
        ),
        "owner_raw": owner_raw,
        "ownership": classify_ownership(owner_raw),
    }

def first_valid(*values):
    for value in values:
        if value not in [None, "", 0, "Unknown"]:
            return value
    return None


def _nominatim_lookup(stadium_name, city_name):
    import urllib.parse
    query = urllib.parse.quote(f"{stadium_name}, {city_name}")
    url = f"https://nominatim.openstreetmap.org/search?q={query}&format=json&limit=1"
    try:
        time.sleep(1)  # OSM rate limit: 1 req/s
        resp = requests.get(url, headers={"User-Agent": "ItalianStadia/1.0"}, timeout=10)
        results = resp.json()
        if results:
            lat, lon = float(results[0]["lat"]), float(results[0]["lon"])
            logging.warning(f"[Nominatim] Coords fallback for '{stadium_name}': {lat}, {lon}")
            return lat, lon
    except Exception as e:
        logging.error(f"[Nominatim] Lookup failed for '{stadium_name}': {e}")
    return None, None


def scrape_stadium(stadium_data, city):
    transfermarkt_url = stadium_data.get("transfermarkt_url")
    wikipedia_url = stadium_data.get("wikipedia_url")
    fallback_name = stadium_data.get("name")

    # 1. Scrape Wikipedia first
    wiki_data = scrape_stadium_data(wikipedia_url=wikipedia_url, transfermarkt_url=transfermarkt_url) if wikipedia_url and transfermarkt_url else {}

    # 2. Default values
    name = fallback_name
    capacity = None
    year_of_construction = None
    address = None

    # 3. Scrape Transfermarkt
    driver = create_driver()

    try:
        driver.get(transfermarkt_url)
        time.sleep(2)

        accept_consent_if_present(driver)

        try:
            name_row = WebDriverWait(driver, 15).until(
                EC.presence_of_element_located((By.XPATH, "//th[text()='Name of stadium:']"))
            )
            name = name_row.find_element(By.XPATH, "following-sibling::td").text.strip()
        except Exception:
            logging.info(f"Stadium name not found on Transfermarkt, using fallback: {fallback_name}")

        try:
            capacity_row = WebDriverWait(driver, 15).until(
                EC.presence_of_element_located((By.XPATH, "//th[text()='Total capacity:']"))
            )
            capacity_text = capacity_row.find_element(By.XPATH, "following-sibling::td").text.strip()
            capacity = clean_int(capacity_text)
        except Exception:
            logging.info(f"Capacity not found on Transfermarkt for stadium {name}")

        try:
            built_row = driver.find_element(By.XPATH, "//th[text()='Built:']")
            built_text = built_row.find_element(By.XPATH, "following-sibling::td").text.strip()
            year_of_construction = clean_int(built_text)
        except NoSuchElementException:
            logging.info(f"Year not found on Transfermarkt for stadium {name}")

    except Exception as e:
        logging.error(f"Error scraping stadium {transfermarkt_url}: {e}")

    finally:
        driver.quit()

    # 4. Merge Transfermarkt + Wikipedia + JSON fallback
    final_name = first_valid(name, fallback_name)
    final_capacity = first_valid(capacity, wiki_data.get("capacity"))
    final_year = first_valid(year_of_construction, wiki_data.get("year_of_construction"))
    final_address = first_valid(wiki_data.get("address"), "Unknown")
    final_latitude = wiki_data.get("latitude")
    final_longitude = wiki_data.get("longitude")

    # Nominatim fallback when Wikipedia has no coordinates
    if final_latitude is None or final_longitude is None:
        final_latitude, final_longitude = _nominatim_lookup(final_name, city.name)

    # 5. Ownership — two-source verification (Wikipedia infobox + Wikidata P127)
    #
    #  Priority:
    #    a) Wikipedia infobox owner  (most detailed, free-text)
    #    b) JSON stadium.owner_raw   (manual override for stadiums Wikipedia doesn't cover)
    #    c) Wikidata P127            (structured, used as fallback OR cross-check)
    #
    #  CONTRACT: ownership must NEVER be published as UNKNOWN when any source
    #  has a value. Conflicting sources are logged as WARNING for human review.
    #  Fabricating or guessing ownership is strictly forbidden — it
    #  undermines the credibility of the entire project.

    wiki_owner_raw = first_valid(wiki_data.get("owner_raw"), stadium_data.get("owner_raw"))
    wikidata_owner = fetch_wikidata_ownership(wikipedia_url)

    if wiki_owner_raw and wikidata_owner:
        # Both sources have data — cross-check classifications
        wiki_cls = classify_ownership(wiki_owner_raw)
        wd_cls   = classify_ownership(wikidata_owner)
        if wiki_cls != wd_cls:
            logging.warning(
                f"[Ownership CONFLICT] '{final_name}': "
                f"Wikipedia='{wiki_owner_raw}' ({wiki_cls}) "
                f"vs Wikidata='{wikidata_owner}' ({wd_cls}). "
                f"Using Wikipedia (more specific)."
            )
        else:
            logging.info(f"[Ownership OK] '{final_name}': both sources agree → {wiki_cls}")
        final_owner_raw = wiki_owner_raw          # Wikipedia wins on specificity
    elif wiki_owner_raw:
        logging.info(f"[Ownership] '{final_name}': Wikipedia only → '{wiki_owner_raw}'")
        final_owner_raw = wiki_owner_raw
    elif wikidata_owner:
        logging.info(f"[Ownership] '{final_name}': Wikidata fallback → '{wikidata_owner}'")
        final_owner_raw = wikidata_owner
    else:
        logging.warning(f"[Ownership UNKNOWN] '{final_name}': no owner data from any source")
        final_owner_raw = None

    final_ownership = classify_ownership(final_owner_raw)

    # 6. Fetch gallery images from Wikimedia Commons
    final_image_url = wiki_data.get("image_url")
    extra_images = fetch_commons_images(wikipedia_url, primary_image_url=final_image_url)

    # logging
    log_field("Stadium", final_name, "capacity", final_capacity, "Transfermarkt/Wikipedia")
    log_field("Stadium", final_name, "year", final_year, "Transfermarkt/Wikipedia")
    log_field("Stadium", final_name, "latitude", final_latitude, "Wikipedia")
    log_field("Stadium", final_name, "longitude", final_longitude, "Wikipedia")
    log_field("Stadium", final_name, "image", final_image_url, "Wikipedia")
    log_field("Stadium", final_name, "extra_images", len(extra_images), "Wikimedia Commons")
    log_field("Stadium", final_name, "owner_raw", final_owner_raw, "Wikipedia+Wikidata")
    log_field("Stadium", final_name, "ownership", final_ownership, "Wikipedia+Wikidata")

    # 6. Save to DB
    stadium, created = Stadium.objects.update_or_create(
        name=final_name,
        city=city,
        defaults={
            "capacity": final_capacity,
            "address": final_address,
            "year_of_construction": final_year,
            "wikipedia_url": wikipedia_url,
            "transfermarkt_url": transfermarkt_url,
            "image_url": final_image_url,
            "extra_images": extra_images,
            "latitude": final_latitude,
            "longitude": final_longitude,
            "owner_raw": final_owner_raw,
            "ownership": final_ownership,
        }
    )

    logging.info(f"{'Created' if created else 'Updated'} stadium: {stadium.name}")
    return stadium


# --------------------------------------------------
# Attendance
# --------------------------------------------------

def scrape_average_attendance(attendance_url, season="24/25"):
    """Scrape average attendance for a given season from Transfermarkt.

    Three-tier fallback strategy:

    1. Season XPath — find the row whose <td> descendant text contains the
       season string.  Uses contains(., season) NOT contains(text(), season):
       TM wraps the year in an <a> tag so text() returns nothing.

    2. First odd/even row — if the season string doesn't appear (format
       mismatch), grab the first data row.
       Uses contains(@class, 'odd') NOT @class='odd': TM sometimes adds
       extra classes (e.g. "odd highlighted") that break an exact match.

    3. JavaScript table scan — ultimate fallback when XPath finds no rows at
       all (e.g. TM changed the HTML structure).  Iterates every <tr> in
       the items table and returns the last .rechts cell of the first row
       that actually has .rechts cells.
    """
    if not attendance_url:
        return None

    driver = create_driver()

    try:
        driver.get(attendance_url)
        time.sleep(3)

        accept_consent_if_present(driver)
        time.sleep(2)  # Let the page settle after potential consent-driven navigation

        # Wait for the attendance table to be present at all
        WebDriverWait(driver, 15).until(
            EC.presence_of_element_located((By.XPATH, "//table[contains(@class,'items')]"))
        )

        # ── Strategy 1: exact season row ────────────────────────────────────
        attendance_row = None
        try:
            attendance_row = driver.find_element(
                By.XPATH, f"//tr[td[contains(., '{season}')]]"
            )
        except Exception:
            pass

        # ── Strategy 2: first data row (contains-based class match) ─────────
        if attendance_row is None:
            logging.warning(
                f"Season '{season}' not found in attendance table at {attendance_url}; "
                f"falling back to first data row."
            )
            try:
                # contains(@class,'odd') handles "odd", "odd highlighted", etc.
                attendance_row = driver.find_element(
                    By.XPATH,
                    "(//table[contains(@class,'items')]"
                    "//tr[contains(@class,'odd') or contains(@class,'even')])[1]"
                )
            except Exception:
                pass

        # ── Strategy 3: JavaScript table scan ───────────────────────────────
        if attendance_row is None:
            logging.warning(
                f"XPath row match failed at {attendance_url}; trying JS table scan."
            )
            js_text = driver.execute_script("""
                const table = document.querySelector('table.items');
                if (!table) return '';
                for (const row of table.querySelectorAll('tr')) {
                    const cells = row.querySelectorAll('.rechts');
                    if (cells.length) {
                        return cells[cells.length - 1].textContent.trim();
                    }
                }
                return '';
            """)
            average_attendance = clean_int(js_text) if js_text else None
            logging.info(f"Average attendance (JS fallback): {average_attendance}")
            return average_attendance

        # ── Extract .rechts value from whichever row was found ───────────────
        attendance_text = driver.execute_script(
            """
            const cells = arguments[0].querySelectorAll('.rechts');
            if (!cells.length) return '';
            return cells[cells.length - 1].textContent;
            """,
            attendance_row
        ).strip()

        average_attendance = clean_int(attendance_text)
        logging.info(f"Average attendance extracted: {average_attendance}")
        return average_attendance

    except Exception as e:
        logging.error(f"Error scraping attendance from {attendance_url}: {e}")
        return None

    finally:
        driver.quit()


# --------------------------------------------------
# Team
# --------------------------------------------------

def scrape_team_from_wikipedia(wikipedia_url):
    soup = get_soup(wikipedia_url)

    if not soup:
        return {}

    founded_raw = get_infobox_value(soup, ["founded"])
    manager = get_infobox_value(soup, ["head coach", "manager", "coach"])

    return {
        "wikipedia_url": wikipedia_url,
        "founded_raw": founded_raw,
        "manager": manager,
        "image_url": extract_wikipedia_image(soup, wikipedia_url),
    }

def parse_founded_date(value):
    if not value:
        return None

    value = clean_text(value)

    formats = [
        "%b %d, %Y",   # Dec 16, 1899
        "%B %d, %Y",  # December 16, 1899
        "%d %B %Y",   # 16 December 1899
        "%Y",         # 1899
    ]

    for fmt in formats:
        try:
            parsed = datetime.strptime(value, fmt)
            return parsed.date()
        except Exception:
            pass

    year = extract_year(value)
    if year:
        return date(year, 1, 1)

    return None


def scrape_team(team_data, stadium, city, league, season="24/25"):
    team_name = team_data.get("name")
    team_url = team_data.get("transfermarkt_url")
    attendance_url = team_data.get("transfermarkt_attendance_url")
    wikipedia_url = team_data.get("wikipedia_url")

    # 1. Wikipedia fallback/enrichment
    wiki_data = scrape_team_from_wikipedia(wikipedia_url) if wikipedia_url else {}
    wiki_meta = scrape_wikipedia_summary_and_image(wikipedia_url) if wikipedia_url else {}

    # 2. Derive tier and girone from league (not from JSON)
    manager_name = wiki_data.get("manager")
    founded = parse_founded_date(wiki_data.get("founded_raw"))
    tier = league.division_level
    girone = None
    if league.country.name == "Italy" and league.division_level == 3:
        girone = team_data.get("girone")
    num_of_titles = 0
    tm_badge = None

    # 3. Transfermarkt scraping
    driver = create_driver()

    # Maps country name → nationality adjective used in Transfermarkt award titles
    NATIONALITY_MAP = {
        "Italy": "Italian",
        "Germany": "German",
        "England": "English",
        "Spain": "Spanish",
        "France": "French",
        "Netherlands": "Dutch",
        "Portugal": "Portugese",  # TM uses this misspelling — do not correct
        "Turkey": "Turkish",
        "Scotland": "Scottish",
        "Belgium": "Belgian",
        "Poland": "Polish",
        "Sweden": "Swedish",
        "Norway": "Norwegian",
        "Romania": "Romanian",
    }

    try:
        driver.get(team_url)
        time.sleep(2)

        accept_consent_if_present(driver)

        # Badge / club crest
        tm_badge = scrape_team_badge(team_url, driver)

        nationality = NATIONALITY_MAP.get(league.country.name)
        if not nationality:
            logging.warning(f"[Team: {team_name}] No nationality mapping for country '{league.country.name}' — num_of_titles will be 0. Add it to NATIONALITY_MAP.")
        if nationality:
            try:
                champion_element = WebDriverWait(driver, 10).until(
                    EC.presence_of_element_located(
                        (By.XPATH, f"//a[@title='{nationality} Champion']/span[@class='data-header__success-number']")
                    )
                )
                num_of_titles = clean_int(champion_element.text) or 0
            except Exception:
                num_of_titles = 0

        # JSON fallback for clubs where TM uses a non-standard award label
        if not num_of_titles and team_data.get("num_of_titles"):
            num_of_titles = team_data["num_of_titles"]
            logging.info(f"[Team: {team_name}] num_of_titles → {num_of_titles} (JSON fallback)")

        try:
            founded_element = driver.find_element(By.XPATH, "//span[@itemprop='foundingDate']")
            founded_text = founded_element.text.strip()
            founded_from_transfermarkt = parse_founded_date(founded_text)
            founded = first_valid(founded_from_transfermarkt, founded)
        except Exception:
            logging.info(f"Founded date not found on Transfermarkt for {team_name}; using Wikipedia/JSON fallback")

    except Exception as e:
        logging.error(f"Error scraping team {team_name}: {e}")

    finally:
        driver.quit()

    # 4. Attendance (season string comes from league config)
    average_attendance = scrape_average_attendance(attendance_url, season=season) if attendance_url else None

    # logging
    log_field("Team", team_name, "league", league.name, "league config")
    log_field("Team", team_name, "tier", tier, "league config")
    log_field("Team", team_name, "girone", girone, "league config/JSON")
    log_field("Team", team_name, "founded", founded, "Transfermarkt/Wikipedia")
    log_field("Team", team_name, "stadium", stadium, "Wikipedia")
    log_field("Team", team_name, "manager", manager_name, "Wikipedia")
    log_field("Team", team_name, "num_of_titles", num_of_titles, "Transfermarkt")
    log_field("Team", team_name, "wikipedia_url", wiki_data.get("wikipedia_url"), "Wikipedia")
    log_field("Team", team_name, "transfermarkt_url", team_url, "Transfermarkt")
    log_field("Team", team_name, "average_attendance", average_attendance, "Transfermarkt")
    log_field("Team", team_name, "description", wiki_meta.get("description"), "Wikipedia")
    log_field("Team", team_name, "badge", tm_badge, "Transfermarkt")
    log_field("Team", team_name, "image_url", wiki_data.get("image_url"), "Wikipedia fallback")

    # 5. Save
    team, created = Team.objects.update_or_create(
        name=team_name,
        defaults={
            "founded": founded,
            "tier": tier,
            "girone": girone,
            "league": league,
            "stadium": stadium,
            "manager": manager_name,
            "num_of_titles": num_of_titles,
            "city": city,
            "average_attendance": average_attendance,
            "wikipedia_url": wikipedia_url,
            "transfermarkt_url": team_url,
            "description": first_valid(
                wiki_meta.get("description"),
                wiki_data.get("description")
            ),
            "image_url": first_valid(
                tm_badge,
                wiki_data.get("image_url"),
                wiki_meta.get("image_url")
            ),
        }
    )
    logging.info(f"{'Created' if created else 'Updated'} team: {team.name}")
    return team

# --------------------------------------------------
# Main execution
# --------------------------------------------------

def run(league_slug, season_override=None):
    data_file = os.path.join(
        os.path.dirname(__file__), "data", f"urls_{league_slug.replace('-', '_')}.json"
    )
    logging.info(f"Loading league data from {data_file}")
    with open(data_file, encoding="utf-8") as f:
        data = json.load(f)

    league = resolve_league(data["league"])
    country_name = data["league"]["country"]
    season = season_override or data["league"]["season"]
    logging.info(f"Scraping {league.name} ({country_name}), season {season}")

    for team_data in data["teams"]:
        logging.info("-----------------------------------------")
        logging.info(f"Processing team: {team_data.get('name')}")

        stadium_data = team_data.get("stadium", {})
        city_data = stadium_data.get("city", {})

        city = scrape_city(city_data, country=country_name)
        stadium = scrape_stadium(stadium_data, city)
        team = scrape_team(team_data, stadium, city, league=league, season=season)

        logging.info(f"Finished processing {team.name}")

    _validate_league(league)


def _validate_league(league):
    from italiastadiaapp.models import Team

    teams = list(Team.objects.filter(league=league).select_related("stadium"))
    total = len(teams)

    issues = {
        "missing_badge": [],
        "unknown_ownership": [],
        "missing_capacity": [],
        "missing_coords": [],
        "zero_attendance": [],
    }

    for team in teams:
        if not team.image_url:
            issues["missing_badge"].append(team.name)
        if team.average_attendance is None or team.average_attendance == 0:
            issues["zero_attendance"].append(team.name)
        if team.stadium:
            if team.stadium.ownership == "UNKNOWN":
                issues["unknown_ownership"].append(team.name)
            if not team.stadium.capacity:
                issues["missing_capacity"].append(team.name)
            if team.stadium.latitude is None or team.stadium.longitude is None:
                issues["missing_coords"].append(team.name)

    warnings = sum(
        len(v) for k, v in issues.items() if k != "missing_coords"
    )
    errors = len(issues["missing_coords"])

    lines = [
        f"\n=== Data Quality Report: {league.name} ({total} teams) ===",
        f"  UNKNOWN ownership  : {len(issues['unknown_ownership'])}",
        f"  Missing badge      : {len(issues['missing_badge'])}",
        f"  Missing capacity   : {len(issues['missing_capacity'])}",
        f"  Missing coordinates: {len(issues['missing_coords'])}",
        f"  Zero avg attendance: {len(issues['zero_attendance'])}",
    ]

    detail_map = {
        "unknown_ownership": "ownership=UNKNOWN",
        "missing_badge":     "badge missing",
        "missing_capacity":  "capacity=0/None",
        "missing_coords":    "coords missing",
        "zero_attendance":   "avg_attendance=0",
    }
    for key, label in detail_map.items():
        for name in issues[key]:
            level = "ERROR" if key == "missing_coords" else "WARN "
            lines.append(f"    [{level}] {name:<35} ({label})")

    result_line = f"\nResult: {warnings} warning(s), {errors} error(s)"
    lines.append(result_line)

    report = "\n".join(lines)
    print(report)
    log_fn = logging.error if errors else logging.warning if warnings else logging.info
    log_fn(report)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Scrape Transfermarkt data for a league")
    parser.add_argument(
        "--league", required=True,
        help="League slug matching scripts/data/urls_<slug>.json (e.g. serie-a, premier-league)"
    )
    args = parser.parse_args()
    run(args.league)