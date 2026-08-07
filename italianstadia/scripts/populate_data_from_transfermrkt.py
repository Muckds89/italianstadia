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


# Localized infobox row labels for the native-language Wikipedia fallback. When a
# stadium's wikipedia_url points at a non-English edition (tr./ru./…), English
# labels like "owner" never match the infobox, leaving ownership UNKNOWN even
# though the data is right there (e.g. Turkish "Sahibi"). `infobox_labels()`
# merges English + the page-language synonyms.
_INFOBOX_LABELS = {
    "capacity": {"tr": ["kapasite"], "ru": ["вместимость"], "de": ["kapazität", "plätze"],
                 "es": ["aforo", "capacidad"], "it": ["capienza", "capacità"],
                 "fr": ["capacité"], "pt": ["capacidade"]},
    "opened":   {"tr": ["açılış", "yapım"], "ru": ["открыт", "построен", "открытие"],
                 "de": ["eröffnung", "baubeginn"], "es": ["inauguración", "apertura"],
                 "it": ["inaugurazione"], "fr": ["inauguration", "ouverture"],
                 "pt": ["inauguração"]},
    "address":  {"tr": ["yer", "adres", "konum"], "ru": ["местоположение", "расположение", "адрес"],
                 "de": ["ort", "adresse", "lage"], "es": ["ubicación", "dirección"],
                 "it": ["ubicazione", "indirizzo"], "fr": ["adresse", "localisation"],
                 "pt": ["localização", "endereço"]},
    "owner":    {"tr": ["sahibi", "sahip"], "ru": ["владелец", "собственник"],
                 "de": ["eigentümer", "besitzer"], "es": ["propietario"], "it": ["proprietario"],
                 "fr": ["propriétaire"], "pt": ["proprietário"]},
    "operator": {"tr": ["işletmeci", "işletmen"], "ru": ["оператор", "эксплуатант"],
                 "de": ["betreiber"], "es": ["operador"], "it": ["gestore"],
                 "fr": ["exploitant", "gestionnaire"], "pt": ["operador"]},
    "surface":  {"tr": ["zemin"], "ru": ["покрытие", "газон"], "de": ["spielfläche", "rasen"],
                 "es": ["césped", "superficie"], "it": ["terreno", "manto"],
                 "fr": ["pelouse", "surface"], "pt": ["gramado", "piso"]},
}


def wiki_lang(wikipedia_url):
    """Language subdomain of a Wikipedia URL (en, tr, ru …); 'en' if unknown."""
    try:
        from urllib.parse import urlparse
        host = urlparse(wikipedia_url).netloc
        sub = host.split(".")[0]
        return sub if sub and sub != "www" else "en"
    except Exception:
        return "en"


def infobox_labels(field, lang):
    """English label(s) for `field` plus the page-language synonyms."""
    base = {"capacity": ["capacity"], "opened": ["opened", "built", "construction", "opened on"],
            "address": ["address", "location"], "owner": ["owner"], "operator": ["operator"],
            "surface": ["surface", "pitch", "playing surface"]}[field]
    return base + _INFOBOX_LABELS.get(field, {}).get(lang, [])


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

    # captures 1,362,863 / 1.362.863 (dot thousands, e.g. Turkish "9.800") / 1362863,
    # but avoids decimals like 181.67 (the fractional group is not exactly 3 digits)
    match = re.search(r"\d{1,3}(?:[.,]\d{3})+|\d{4,}", value)

    if not match:
        return None

    return int(match.group(0).replace(",", "").replace(".", ""))
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
    try:
        os.remove(log_file)
    except PermissionError:
        # On Windows the file may still be held open by a previous run.
        # Truncate in-place so the next run starts with a clean log.
        with open(log_file, "w"):
            pass

logging.basicConfig(
    filename=log_file,
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)


# --------------------------------------------------
# League resolution
# --------------------------------------------------

def normalize_season(season):
    """Canonical display form for a season string: '25/26' -> '2025/26'.
    Accepts '25/26', '2025/26' and '2025/2026'; returns '' for empty input."""
    s = (season or "").strip()
    if not s or "/" not in s:
        return s
    start, _, end = s.partition("/")
    start, end = start.strip(), end.strip()
    if len(start) == 2:
        start = f"20{start}"
    if len(end) == 4:
        end = end[2:]
    return f"{start}/{end}"


def resolve_league(config):
    """Resolve Country and League from the JSON league config block.

    Country has two UNIQUE columns (code and name), so it must be reconciled
    against BOTH: a plain update_or_create(code=...) crashes with
    "UNIQUE constraint failed: country.name" when a row already exists under
    the same NAME but a different/blank code (e.g. seeded from
    initial_data.json before codes were assigned). Match on code first, then
    fall back to name, then create — and keep both fields in sync.
    """
    code, name = config["country_code"], config["country"]
    country = (Country.objects.filter(code=code).first()
               or Country.objects.filter(name=name).first())
    if country is None:
        country = Country.objects.create(code=code, name=name)
    elif country.code != code or country.name != name:
        country.code, country.name = code, name
        country.save(update_fields=["code", "name"])
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
    """Chrome with stability flags. The bare driver intermittently dies with
    'session not created from disconnected: unable to connect to renderer' —
    Chrome launches but its renderer crashes. These flags fix the usual causes
    (shared-memory exhaustion, GPU/sandbox issues, devtools origin check).
    Set HEADLESS=1 to run without a visible window."""
    options = webdriver.ChromeOptions()
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")   # avoid /dev/shm renderer crash
    options.add_argument("--disable-gpu")
    options.add_argument("--remote-allow-origins=*")  # new Chrome / older driver handshake
    options.add_argument("--disable-extensions")
    options.add_argument("--no-first-run")
    options.add_argument("--disable-background-networking")
    options.add_argument("--window-size=1920,1080")
    if os.environ.get("HEADLESS") == "1":
        options.add_argument("--headless=new")
    # Quieten DevTools/USB log spam on Windows
    options.add_experimental_option("excludeSwitches", ["enable-logging"])
    service = Service(ChromeDriverManager().install())
    return webdriver.Chrome(service=service, options=options)


# Transfermarkt intermittently returns a Cloudflare/gateway error page (502/503/504)
# under load — the page loads with HTTP 200 in Selenium but the body is the error,
# so element lookups silently fail and every team ends up with 0 titles. Detect the
# gateway-error body and retry with exponential backoff before giving up.
_GATEWAY_MARKERS = (
    "502 bad gateway", "bad gateway",
    "503 service", "service temporarily unavailable", "service unavailable",
    "504 gateway", "gateway time-out", "gateway timeout",
    "error code 502", "error code 503", "error code 520", "error code 521",
    "error code 522", "error code 524",
    "just a moment",  # Cloudflare challenge interstitial
)


def _is_gateway_error(driver):
    try:
        title = (driver.title or "").lower()
        # Only sniff the start of the body; full source can be large.
        body = (driver.page_source or "")[:4000].lower()
    except Exception:
        return False
    blob = title + " " + body
    return any(m in blob for m in _GATEWAY_MARKERS)


def get_with_retry(driver, url, retries=5, base_delay=4):
    """driver.get(url) with backoff on Transfermarkt 502/503/504 gateway pages."""
    for attempt in range(1, retries + 1):
        try:
            driver.get(url)
        except Exception as exc:
            if attempt == retries:
                raise
            delay = base_delay * attempt
            logging.warning(f"[HTTP] get failed ({exc}) for {url} — retry {attempt}/{retries} in {delay}s")
            time.sleep(delay)
            continue
        if not _is_gateway_error(driver):
            return True
        if attempt == retries:
            logging.error(f"[HTTP] gateway error persisted after {retries} attempts: {url}")
            return False
        delay = base_delay * attempt
        logging.warning(f"[HTTP] gateway error (502/503/504) for {url} — retry {attempt}/{retries} in {delay}s")
        time.sleep(delay)
    return False

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

        # City populations should usually be at least 1,000 and never exceed 50M
        # (values above 50M are scraping artefacts — e.g. area codes, GDP figures)
        # Values in the year range 1800-2100 are census/founding years, not populations
        if number < 1000 or number > 50_000_000 or 1800 <= number <= 2100:
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

# What KIND of thing owns the ground, from the owner entity's P31 (instance of).
# Wikidata returns owners as bare entity labels — "Kortrijk", "Lommel", "Barcelona" —
# with no wording for classify_ownership's keywords to match, so every one of them
# used to fall through to PRIVATE. That published municipally owned grounds as
# privately owned. The entity's TYPE disambiguates what its name cannot:
# "Barcelona" the football club vs "Kortrijk" the municipality.
_WD_PUBLIC_KINDS = (
    "municipalit", "city", "town", "commune", "province", "state", "government",
    "public", "district", "county", "capital", "borough", "region",
    "local authority", "principality", "prefecture", "canton", "federal",
)
# Wikidata type labels that contain a public-sounding word but describe a PRIVATE
# entity. Removed before the public test, which matches on substrings.
_WD_FALSE_PUBLIC = (
    "public company", "public limited company", "publicly traded company",
    "public joint-stock company", "public joint stock company",
    "real estate",
)
_WD_PRIVATE_KINDS = (
    "football club", "association football club", "sports club", "sports team",
    "business", "enterprise", "company", "corporation", "organization",
    "organisation", "société", "holding",
)


def _wd_kind_from_types(type_labels):
    """PUBLIC / PRIVATE / None from an owner entity's 'instance of' labels."""
    joined = " ; ".join(type_labels).lower()
    # Strip phrases that only LOOK public before testing, because the public test
    # runs first and matches on substrings. ArcelorMittal, which owns the Otelul
    # Stadium in Galati, is typed "business ; enterprise ; public company" —
    # "public company" means publicly TRADED, yet it matched "public" and the
    # stadium of a private steel company was classified as publicly owned. Same
    # trap in "real estate", which contains "state".
    # Rewritten to "company", not deleted: these phrases ARE evidence of a private
    # commercial owner, and a type like "public joint-stock company" has nothing
    # else in it — deleting outright would return None and lose that signal.
    for phrase in _WD_FALSE_PUBLIC:
        joined = joined.replace(phrase, " company ")
    if any(k in joined for k in _WD_PUBLIC_KINDS):
        return "PUBLIC"
    if any(k in joined for k in _WD_PRIVATE_KINDS):
        return "PRIVATE"
    return None


def fetch_wikidata_ownership(wikipedia_url):
    """
    Query Wikidata for the 'owned by' (P127) property of a stadium.
    Uses the Wikipedia page to locate the Wikidata entity, then resolves P127 labels
    AND each owner's P31 (instance of) so the owner's type is known, not just its name.

    Returns (owner_label_or_None, kind_or_None) where kind is "PUBLIC"/"PRIVATE"
    derived from the owner entity type. Used as a second source and cross-check
    against Wikipedia's infobox owner field.
    """
    if not wikipedia_url:
        return None, None

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
            return None, None

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
            return None, None

        # Step 3: resolve each owner entity to its English label
        owner_ids = []
        for claim in p127_claims:
            snak = claim.get("mainsnak", {})
            if snak.get("datatype") == "wikibase-item":
                oid = snak.get("datavalue", {}).get("value", {}).get("id")
                if oid:
                    owner_ids.append(oid)

        if not owner_ids:
            return None, None

        time.sleep(0.3)
        resp3 = requests.get("https://www.wikidata.org/w/api.php", params={
            "action": "wbgetentities",
            "ids": "|".join(owner_ids[:5]),
            "props": "labels|claims",
            "languages": "en",
            "format": "json",
        }, headers=HEADERS, timeout=15)
        resp3.raise_for_status()
        owner_entities = resp3.json().get("entities", {})
        owner_labels, type_ids = [], []
        for oid in owner_ids:
            oe = owner_entities.get(oid, {})
            label = oe.get("labels", {}).get("en", {}).get("value", "")
            if label:
                owner_labels.append(label)
            for c in oe.get("claims", {}).get("P31", []):
                tid = c.get("mainsnak", {}).get("datavalue", {}).get("value", {}).get("id")
                if tid and tid not in type_ids:
                    type_ids.append(tid)

        # Resolve the owner's "instance of" targets to labels so the owner's TYPE
        # decides public vs private — a bare name like "Kortrijk" cannot.
        kind = None
        if type_ids:
            time.sleep(0.3)
            resp4 = requests.get("https://www.wikidata.org/w/api.php", params={
                "action": "wbgetentities",
                "ids": "|".join(type_ids[:10]),
                "props": "labels",
                "languages": "en",
                "format": "json",
            }, headers=HEADERS, timeout=15)
            resp4.raise_for_status()
            tents = resp4.json().get("entities", {})
            type_labels = [tents.get(t, {}).get("labels", {}).get("en", {}).get("value", "")
                           for t in type_ids[:10]]
            kind = _wd_kind_from_types([t for t in type_labels if t])

        result = " / ".join(owner_labels) if owner_labels else None
        if result:
            logging.info(f"[Wikidata] Owner for '{title}': {result}"
                         + (f" [type => {kind}]" if kind else " [type unresolved]"))
        return result, kind

    except Exception as e:
        logging.error(f"[Wikidata] fetch_wikidata_ownership failed for '{wikipedia_url}': {e}")
        return None, None


def fetch_wikidata_coordinates(wikipedia_url):
    """Language-independent coordinate fallback. Resolve the Wikipedia page to its
    Wikidata entity and read P625 (coordinate location). This works even when the
    linked (e.g. English) article carries no geo markup but the native-language
    edition does — both share one Wikidata item, and P625 is populated from any
    edition. Returns (lat, lon) floats or (None, None)."""
    if not wikipedia_url:
        return None, None
    try:
        from urllib.parse import urlparse, unquote
        host = urlparse(wikipedia_url).netloc
        title = unquote(urlparse(wikipedia_url).path.split("/wiki/")[-1])
        resp = requests.get(f"https://{host}/w/api.php", params={
            "action": "query", "titles": title, "prop": "pageprops",
            "ppprop": "wikibase_item", "format": "json",
        }, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        pages = resp.json().get("query", {}).get("pages", {})
        entity_id = next((p.get("pageprops", {}).get("wikibase_item")
                          for p in pages.values()), None)
        if not entity_id:
            return None, None
        time.sleep(0.3)
        resp2 = requests.get("https://www.wikidata.org/w/api.php", params={
            "action": "wbgetentities", "ids": entity_id, "props": "claims",
            "format": "json",
        }, headers=HEADERS, timeout=15)
        resp2.raise_for_status()
        claims = (resp2.json().get("entities", {}).get(entity_id, {})
                  .get("claims", {}).get("P625", []))
        for claim in claims:
            val = claim.get("mainsnak", {}).get("datavalue", {}).get("value", {})
            lat, lon = val.get("latitude"), val.get("longitude")
            if lat is not None and lon is not None:
                logging.info(f"[Wikidata] P625 coords for '{title}': {lat}, {lon}")
                return float(lat), float(lon)
        return None, None
    except Exception as e:
        logging.error(f"[Wikidata] fetch_wikidata_coordinates failed for '{wikipedia_url}': {e}")
        return None, None


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
        " county",                 # administrative county (e.g. Klaipėda County, County Dublin)
        " parish",                 # rural municipality in Baltic/Nordic countries (e.g. Saue Parish)
        "metropolitan borough", "london borough", "royal borough",
        "public authority", "public body", "national sports",
        "sports authority", "stadium authority",
        "sports organ",                # sports organisation / sports organization (e.g. Cyprus Sports Organisation)
        "sport organ",                 # sport organisation / sport organization (singular — e.g. Cyprus Sport Organisation)
        "olympic committee",           # Hellenic Olympic Committee (Karaiskakis Stadium)
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
        "land ",                  # Land Salzburg, Land Tirol, Land Steiermark (Austrian federal states)
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
        "concello ",                # Galician city council (Concello de A Coruña, etc.)
        "cabildo ",                 # Canary Islands island council (Cabildo de Gran Canaria, etc.)
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
        "stad ",                   # Stad Gent / Stad Brugge / Stad Antwerpen (prefix form)
        # NB: do NOT add " stad" (leading space) — it substring-matches the WORD
        # "Stadium"/"Stadion"/"Stade" and wrongly tagged 9 privately/company-owned
        # grounds PUBLIC (e.g. "…Stadionbetriebs AG", "Millennium Stadium plc").
        # The rare Swedish suffix form ("Göteborgs Stad") uses a manual owner_raw override.
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
        "ministerstvo",            # ministry (Ministerstvo obrany ČR, Ministerstvo školství …)
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
        # ── Slovenian ────────────────────────────────────────────────────────
        "mestna občina",           # city municipality (e.g. Mestna občina Ljubljana)
        "občina ",                 # municipality (e.g. Občina Domžale, Občina Ajdovščina)
        "javni zavod",             # public institution (e.g. Javni zavod Šport Ljubljana)
        # ── Hungarian ────────────────────────────────────────────────────────
        "város ",                  # Miskolc Város Önkormányzata …
        "önkormányzat",            # local government / municipality
        "fővárosi",                # Budapest metropolitan
        # ── Greek (transliterated) ───────────────────────────────────────────
        "dimos ",                  # δήμος → dimos (municipality)
        "dimou",                   # genitive form
        # ── Lithuanian ───────────────────────────────────────────────────────
        "savivaldybė",             # municipality (e.g. Šiaulių miesto savivaldybė)
        "savivaldybes",            # genitive form
        "miesto savivaldybė",      # city municipality
        "rajono savivaldybė",      # district municipality
        # ── Albanian ─────────────────────────────────────────────────────────
        "bashkia ",                # municipality (Bashkia Vlorë, Bashkia Tiranë …)
        "bashkie",                 # genitive / other forms
        "komuna ",                 # commune / municipality
        # ── Russian / Ukrainian / Bulgarian / Serbian (Cyrillic) ─────────────
        "муницип",                 # муниципальное образование / муниципалитет
        "город ",                  # «Город Тула» (МО «Город Тула»), city of …
        "городск",                 # городской / городская (municipal)
        "област",                  # область / областной (oblast / region)
        "администрац",             # администрация (city administration)
        "правительств",            # government (правительство Москвы …)
        "министерств",             # ministry
        "департамент",             # department (sports department)
        "край ", "краев",          # krai (region)
        "общин",                   # община (Bulgarian/Serbian municipality)
        "громад",                  # громада (Ukrainian municipality)
        "міськ",                   # міська рада (Ukrainian city council)
        "державн",                 # state (Ukrainian/Bulgarian)
        "скупштина",               # assembly (Serbian Cyrillic)
        "општина",                 # municipality (Serbian/Macedonian Cyrillic)
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

_ROOF_RETRACTABLE = ("retractable roof", "convertible roof", "sliding roof", "movable roof",
                     "açılır kapanır çatı", "açılır çatı", "ausfahrbares dach", "раздвижн",
                     "tetto retrattile", "techo retráctil", "toit rétractable")
_ROOF_CLOSED = ("domed stadium", "geodesic dome", "fully enclosed", "fully-enclosed",
                "indoor arena", "indoor stadium", "fixed closed roof", "enclosed roof",
                "kapalı stadyum", "estadio cubierto", "stadio coperto")


def classify_roof(text):
    """Classify a stadium's roof from page text -> RETRACTABLE / CLOSED / OPEN.
    Football grounds are open-air by default; only positive roof evidence overrides.
    Returns OPEN (not None) so the value persists across re-scrapes."""
    if not text:
        return "OPEN"
    t = text.lower()
    if any(w in t for w in _ROOF_RETRACTABLE):
        return "RETRACTABLE"
    if any(w in t for w in _ROOF_CLOSED):
        return "CLOSED"
    return "OPEN"


def _page_roof_text(soup):
    """Infobox text + first paragraphs, for roof-keyword detection."""
    if not soup:
        return ""
    ib = get_infobox(soup)
    intro = " ".join(p.get_text(" ", strip=True)
                     for p in soup.select("div.mw-parser-output > p")[:4])
    return ((ib.get_text(" ", strip=True) if ib else "") + " " + intro)


def classify_surface(text):
    """Map a multilingual infobox surface value to GRASS / ARTIFICIAL / HYBRID,
    or None. Covers English + the native-fallback languages (tr 'doğal çim',
    ru 'газон', de 'rasen', es 'césped', it 'erba', fr 'pelouse', pt 'grama')."""
    if not text:
        return None
    t = text.lower()
    hybrid = ("hybrid", "hibrit", "desso", "grassmaster", "ibrido", "híbrido", "hybride",
              "гибрид")
    artificial = ("artificial", "synthetic", "astroturf", "3g", "4g", "suni", "sentetik",
                  "kunstrasen", "искусствен", "sintétic", "sintetic", "synthétique",
                  "artificiel")
    grass = ("grass", "natural", "doğal çim", "çim", "rasen", "césped", "cesped", "erba",
             "naturale", "pelouse", "gazon", "grama", "relva", "газон", "трав")
    if any(w in t for w in hybrid):
        return "HYBRID"
    if any(w in t for w in artificial):
        return "ARTIFICIAL"
    if any(w in t for w in grass):
        return "GRASS"
    return None


# League country -> Wikipedia language subdomain, for the English->native infobox
# fallback. Only the languages we actually scrape need entries; unknown -> no fallback.
COUNTRY_WIKI_LANG = {
    "Russia": "ru", "Turkey": "tr", "Ukraine": "uk", "Belarus": "be", "Poland": "pl",
    "Germany": "de", "Spain": "es", "Italy": "it", "France": "fr", "Portugal": "pt",
    "Netherlands": "nl", "Greece": "el", "Romania": "ro", "Czechia": "cs", "Austria": "de",
    "Switzerland": "de", "Belgium": "nl", "Denmark": "da", "Croatia": "hr", "Cyprus": "el",
    "Serbia": "sr", "Hungary": "hu", "Bulgaria": "bg", "Slovakia": "sk", "Slovenia": "sl",
    "Norway": "no", "Sweden": "sv", "Finland": "fi", "Iceland": "is", "Estonia": "et",
    "Latvia": "lv", "Lithuania": "lt", "Moldova": "ro", "North Macedonia": "mk",
    "Albania": "sq", "Montenegro": "sr", "Luxembourg": "fr", "Malta": "mt",
    "Azerbaijan": "az", "Armenia": "hy", "Georgia": "ka", "Israel": "he", "Kosovo": "sq",
    "Bosnia and Herzegovina": "bs",
}


def fetch_langlink(wikipedia_url, target_lang):
    """Return the URL of the same article in `target_lang` via the Wikipedia
    langlinks API, or None. Lets us cross from an English stadium page to the
    native-language edition (which often carries owner/capacity the en page lacks)."""
    if not wikipedia_url or not target_lang:
        return None
    try:
        from urllib.parse import urlparse, unquote, quote
        host = urlparse(wikipedia_url).netloc
        title = unquote(urlparse(wikipedia_url).path.split("/wiki/")[-1])
        r = requests.get(f"https://{host}/w/api.php", headers=HEADERS, params={
            "action": "query", "prop": "langlinks", "lllang": target_lang,
            "titles": title, "format": "json", "redirects": 1,
        }, timeout=15)
        r.raise_for_status()
        for page in r.json().get("query", {}).get("pages", {}).values():
            for ll in page.get("langlinks", []):
                native_title = ll.get("*")
                if native_title:
                    return f"https://{target_lang}.wikipedia.org/wiki/{quote(native_title.replace(' ', '_'))}"
    except Exception as e:
        logging.error(f"[Langlink] failed for '{wikipedia_url}' -> {target_lang}: {e}")
    return None


def _extract_infobox_fields(soup, lang):
    """Pull the infobox fields we care about from one soup, using `lang` labels."""
    return {
        "capacity": extract_first_int(get_infobox_value(soup, infobox_labels("capacity", lang))),
        "year_of_construction": extract_year(get_infobox_value(soup, infobox_labels("opened", lang))),
        "surface": classify_surface(get_infobox_value(soup, infobox_labels("surface", lang))),
        "address": get_infobox_value(soup, infobox_labels("address", lang)),
        "owner_raw": get_infobox_value(
            soup, infobox_labels("owner", lang) + infobox_labels("operator", lang)),
    }


def scrape_stadium_data(wikipedia_url=None, transfermarkt_url=None, native_lang=None):
    wikipedia_soup = get_soup(wikipedia_url) if wikipedia_url else None
    transfermarkt_soup = get_soup(transfermarkt_url) if transfermarkt_url else None

    if not wikipedia_soup:
        return {}

    latitude, longitude = extract_coordinates_from_wikipedia(wikipedia_soup)

    # Use the page's own language for infobox labels so a native-language URL
    # (tr./ru./…) reads owner/capacity/etc., not just en.
    lang = wiki_lang(wikipedia_url)
    fields = _extract_infobox_fields(wikipedia_soup, lang)

    # English->native fallback: if the page is NOT already the country's language
    # and key fields are still missing, follow the langlink to the native article
    # and fill the gaps there (e.g. en 'Arsenal Stadium (Tula)' has no owner, but
    # ru 'Арсенал (стадион, Тула)' does).
    missing = [k for k in ("owner_raw", "capacity", "surface", "year_of_construction", "address")
               if not fields.get(k)]
    if native_lang and lang != native_lang and missing:
        native_url = fetch_langlink(wikipedia_url, native_lang)
        if native_url:
            native_soup = get_soup(native_url)
            if native_soup:
                nf = _extract_infobox_fields(native_soup, native_lang)
                filled = []
                for k in missing:
                    if nf.get(k):
                        fields[k] = nf[k]
                        filled.append(k)
                if filled:
                    logging.info(f"[Native fallback] {native_url}: filled {filled}")

    return {
        "wikipedia_url": wikipedia_url,
        "capacity": fields["capacity"],
        "year_of_construction": fields["year_of_construction"],
        "surface": fields["surface"],
        "stadium_type": classify_roof(_page_roof_text(wikipedia_soup)),
        "address": fields["address"],
        "latitude": latitude,
        "longitude": longitude,
        "image_url": extract_best_stadium_image(
            transfermarkt_soup=transfermarkt_soup,
            transfermarkt_url=transfermarkt_url,
            wikipedia_soup=wikipedia_soup,
            wikipedia_url=wikipedia_url,
        ),
        "owner_raw": fields["owner_raw"],
        "ownership": classify_ownership(fields["owner_raw"]),
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


def scrape_stadium(stadium_data, city, native_lang=None):
    transfermarkt_url = stadium_data.get("transfermarkt_url")
    wikipedia_url = stadium_data.get("wikipedia_url")
    fallback_name = stadium_data.get("name")

    # 1. Scrape Wikipedia first
    wiki_data = scrape_stadium_data(wikipedia_url=wikipedia_url, transfermarkt_url=transfermarkt_url,
                                    native_lang=native_lang) if wikipedia_url and transfermarkt_url else {}

    # 2. Default values
    name = fallback_name
    capacity = None
    year_of_construction = None
    address = None

    # 3. Scrape Transfermarkt
    driver = create_driver()

    try:
        get_with_retry(driver, transfermarkt_url)
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
    # JSON name takes priority over TM: TM often shows sponsorship/old names (e.g.
    # "Party-Rent-Arena" for VictoriArena); the JSON is manually curated and correct.
    final_name = first_valid(fallback_name, name)
    final_capacity = first_valid(capacity, wiki_data.get("capacity"), stadium_data.get("capacity"))
    final_year = first_valid(year_of_construction, wiki_data.get("year_of_construction"))
    final_address = first_valid(wiki_data.get("address"), "Unknown")
    final_latitude = wiki_data.get("latitude")
    final_longitude = wiki_data.get("longitude")

    # Wikidata P625 fallback — language-independent. Catches the case where the
    # linked (English) article has no geo markup but the native-language edition
    # does: both share one Wikidata item, so P625 still resolves coordinates.
    if final_latitude is None or final_longitude is None:
        wd_lat, wd_lon = fetch_wikidata_coordinates(wikipedia_url)
        if wd_lat is not None and wd_lon is not None:
            final_latitude, final_longitude = wd_lat, wd_lon

    # Nominatim fallback when Wikipedia + Wikidata both have no coordinates
    if final_latitude is None or final_longitude is None:
        final_latitude, final_longitude = _nominatim_lookup(final_name, city.name)

    # JSON hardcoded fallback — last resort when both Wikipedia and Nominatim fail.
    # Set "latitude"/"longitude" in the stadium JSON entry for stadiums where:
    #   - Wikipedia has no geo markup (e.g. Sepsi Arena — Wikipedia maintenance
    #     category "Articles missing coordinates without coordinates on Wikidata")
    #   - Nominatim has a transient failure or doesn't recognise the name
    # Source values from OpenStreetMap (way ID) or Google Maps — always verify.
    if final_latitude is None or final_longitude is None:
        json_lat = stadium_data.get("latitude")
        json_lon = stadium_data.get("longitude")
        if json_lat is not None and json_lon is not None:
            final_latitude  = json_lat
            final_longitude = json_lon
            logging.info(
                f"[Coords] '{final_name}': Wikipedia + Nominatim both failed; "
                f"using JSON hardcoded coords ({final_latitude}, {final_longitude})"
            )
        else:
            logging.error(
                f"[Coords MISSING] '{final_name}': all three coordinate sources failed "
                f"(Wikipedia, Nominatim, JSON). Add 'latitude'/'longitude' to the "
                f"stadium entry in the JSON file to fix this."
            )

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
    wikidata_owner, wikidata_kind = fetch_wikidata_ownership(wikipedia_url)

    if wiki_owner_raw and wikidata_owner:
        # Both sources have data — cross-check classifications
        wiki_cls = classify_ownership(wiki_owner_raw)
        # Wikidata labels are bare entity names with no keywords to match, so trust
        # the owner's entity TYPE (P31) over a keyword scan of its name.
        wd_cls   = wikidata_kind or classify_ownership(wikidata_owner)
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
        logging.info(f"[Ownership] '{final_name}': Wikidata fallback → '{wikidata_owner}'"
                     + (f" (entity type → {wikidata_kind})" if wikidata_kind else ""))
        final_owner_raw = wikidata_owner
    else:
        logging.warning(f"[Ownership UNKNOWN] '{final_name}': no owner data from any source")
        final_owner_raw = None

    final_ownership = classify_ownership(final_owner_raw)
    # When the owner came from Wikidata, its label is a bare entity name ("Kortrijk",
    # "Lommel") with nothing for the keyword list to match, so classify_ownership
    # defaults it to PRIVATE — publishing municipally owned grounds as private. The
    # entity's own type (P31) is authoritative here, so it overrides the keyword guess.
    # Wikipedia-sourced text keeps keyword classification: it is the more specific source.
    if final_owner_raw == wikidata_owner and wikidata_kind and not wiki_owner_raw:
        if final_ownership != wikidata_kind:
            logging.info(
                f"[Ownership] '{final_name}': '{wikidata_owner}' has no public keyword "
                f"but its Wikidata type says {wikidata_kind} → using {wikidata_kind}"
            )
        final_ownership = wikidata_kind

    # 6. Fetch gallery images from Wikimedia Commons
    # A JSON stadium.image_url wins over the scraped one — manual override for
    # grounds whose Wikipedia infobox/og:image is missing or a poor hero (e.g.
    # Windsor Park's thin redevelopment panorama).
    final_image_url = stadium_data.get("image_url") or wiki_data.get("image_url")
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
    # LOCK GUARD: never overwrite a manually-corrected stadium. If a locked row
    # matches this team (by Wikipedia URL + city, or name + city), leave it
    # completely untouched so the weekly auto-scrape can't undo the fix.
    locked = None
    if wikipedia_url:
        locked = Stadium.objects.filter(wikipedia_url=wikipedia_url, city=city, locked=True).first()
    if locked is None:
        locked = Stadium.objects.filter(name=final_name, city=city, locked=True).first()
    if locked is not None:
        logging.info(f"[Locked] Skipping '{locked.name}' — manually corrected, scraper won't touch it.")
        return locked

    # Shared-venue deduplication: if another team already produced a Stadium row
    # with the same Wikipedia URL in the same city (e.g. Jan Breydel, Stelios
    # Kyriakides, Arena Națională), reuse that row instead of creating a duplicate.
    # Only the transfermarkt_url column is overwritten — all scraped data stays intact.
    # Exception: if the shared stadium has UNKNOWN ownership and the JSON provides
    # an owner_raw fallback, apply it now so repeated scrapes can resolve UNKNOWN.
    if wikipedia_url:
        shared = Stadium.objects.filter(wikipedia_url=wikipedia_url, city=city).first()
        if shared:
            update_fields = ["transfermarkt_url"]
            shared.transfermarkt_url = transfermarkt_url
            # Correct a stale name: if Wikipedia now returns a different name for
            # the same article, trust the fresh scrape over the old DB value.
            if final_name and shared.name != final_name:
                logging.info(
                    f"Shared stadium: correcting name '{shared.name}' -> '{final_name}' "
                    f"(Wikipedia: {wikipedia_url})"
                )
                shared.name = final_name
                update_fields.append("name")
            if shared.ownership == "UNKNOWN":
                json_owner = stadium_data.get("owner_raw")
                if json_owner and not shared.owner_raw:
                    shared.owner_raw = json_owner
                    shared.ownership = classify_ownership(json_owner)
                    update_fields += ["owner_raw", "ownership"]
            # Re-evaluate ownership when keyword additions would change the result
            # (self-heals after public_keywords list is expanded)
            elif shared.owner_raw:
                reclassified = classify_ownership(shared.owner_raw)
                if reclassified != shared.ownership:
                    logging.info(
                        f"Shared stadium '{shared.name}': ownership reclassified "
                        f"{shared.ownership} -> {reclassified} "
                        f"(owner_raw='{shared.owner_raw}')"
                    )
                    shared.ownership = reclassified
                    update_fields += ["ownership"]
            # Update capacity from Wikipedia when a fresh scrape returns a better value
            # (fixes stale JSON-fallback values; only fires when Wikipedia has data)
            wiki_cap = wiki_data.get("capacity")
            if wiki_cap and wiki_cap != shared.capacity:
                old_cap = shared.capacity
                shared.capacity = wiki_cap
                update_fields.append("capacity")
                logging.info(
                    f"Shared stadium '{shared.name}': updated capacity "
                    f"{old_cap} -> {wiki_cap} (Wikipedia)"
                )
            # Apply JSON hardcoded capacity when the existing stadium still has none
            # (city-page Wikipedia URLs have no capacity data; JSON value is authoritative)
            elif shared.capacity is None:
                json_cap = stadium_data.get("capacity")
                if json_cap is not None and json_cap > 0:
                    shared.capacity = json_cap
                    update_fields.append("capacity")
                    logging.info(
                        f"Shared stadium '{shared.name}': applied JSON hardcoded "
                        f"capacity ({json_cap}) — was null in DB"
                    )
            # Apply JSON hardcoded coords when the existing stadium has none
            # (happens when Wikipedia + Nominatim both failed on the first scrape)
            if shared.latitude is None or shared.longitude is None:
                json_lat = stadium_data.get("latitude")
                json_lon = stadium_data.get("longitude")
                if json_lat is not None and json_lon is not None:
                    shared.latitude  = json_lat
                    shared.longitude = json_lon
                    update_fields += ["latitude", "longitude"]
                    logging.info(
                        f"Shared stadium '{shared.name}': applied JSON hardcoded "
                        f"coords ({json_lat}, {json_lon}) — was null in DB"
                    )
            # Backfill surface when missing (from the fresh scrape's infobox)
            if not shared.surface:
                new_surface = stadium_data.get("surface") or wiki_data.get("surface")
                if new_surface:
                    shared.surface = new_surface
                    update_fields.append("surface")
            # Backfill roof type when missing
            if not shared.stadium_type:
                new_type = stadium_data.get("stadium_type") or wiki_data.get("stadium_type")
                if new_type:
                    shared.stadium_type = new_type
                    update_fields.append("stadium_type")
            shared.save(update_fields=update_fields)
            logging.info(
                f"Shared stadium — reused existing '{shared.name}' "
                f"(Wikipedia: {wikipedia_url})"
            )
            return shared

    stadium, created = Stadium.objects.update_or_create(
        name=final_name,
        city=city,
        defaults={
            "capacity": final_capacity,
            "address": final_address,
            "year_of_construction": final_year,
            "surface": stadium_data.get("surface") or wiki_data.get("surface"),
            "stadium_type": stadium_data.get("stadium_type") or wiki_data.get("stadium_type"),
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
        get_with_retry(driver, attendance_url)
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
                // Iterate ALL rows; return the first .rechts cell that holds a
                // parseable positive integer.  Rows with '-', '0' or empty cells
                // (common for promoted/relegated clubs' transition seasons) are
                // skipped so Strategy 3 isn't defeated by a single bad row.
                const table = document.querySelector('table.items');
                if (!table) return '';
                for (const row of table.querySelectorAll('tr')) {
                    const cells = row.querySelectorAll('.rechts');
                    if (cells.length) {
                        const text = cells[cells.length - 1].textContent.trim();
                        const digits = text.replace(/\\D/g, '');
                        if (digits && parseInt(digits, 10) > 0) return text;
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

    # LOCK GUARD: never overwrite a manually-corrected team's wiki/TM links,
    # crest, name, etc. — BUT attendance changes every season and was not part
    # of the manual fix, so a locked team still gets ONLY its average_attendance
    # refreshed. Everything else is left untouched.
    locked = Team.objects.filter(name=team_name, city=city, locked=True).first()
    if locked is None and team_url:
        locked = Team.objects.filter(transfermarkt_url=team_url, locked=True).first()
    if locked is not None:
        att_url = attendance_url or locked.transfermarkt_url
        if att_url:
            att = scrape_average_attendance(att_url, season=season)
            if att and att != locked.average_attendance:
                locked.average_attendance = att
                locked.save(update_fields=["average_attendance"])
                logging.info(f"[Locked] '{locked.name}': refreshed attendance -> {att} (only field touched)")
            else:
                logging.info(f"[Locked] '{locked.name}': locked; attendance unchanged.")
        else:
            logging.info(f"[Locked] Skipping team '{locked.name}' — manually corrected (no attendance url).")
        return locked

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
        "Czechia": "Czech",
        "Austria": "Austrian",
        "Switzerland": "Swiss",
        "Denmark": "Danish",
        "Greece": "Greek",
        "Croatia": "Croatian",
        "Cyprus": "Cypriot",
        "Serbia": "Serbian",
        "Hungary": "Hungarian",
        "Bulgaria": "Bulgarian",
        "Slovakia": "Slovak",
        "Slovenia": "Slovenian",
        "Ireland": "Irish",
        # New leagues added 2026-06
        "Moldova": "Moldavian",
        "Ukraine": "Ukrainian",
        "Bosnia and Herzegovina": "Bosnian-Herzegovinian",
        "North Macedonia": "Macedonian",
        "Albania": "Albanian",
        "Latvia": "Latvian",
        "Lithuania": "Lithuanian",
        "Estonia": "Estonian",
        "Iceland": "Icelandic",
        "Finland": "Finnish",
        "Montenegro": "Montenegrian",
        "Luxembourg": "Luxembourgian",
        "Malta": "Maltese",
        "Wales": "Welsh",
        # New leagues 2026-06-20
        "Belarus": "Belarusian",
        "Russia": "Russian",
        "Azerbaijan": "Azerbaijani",
        "Armenia": "Armenian",
        "Kosovo": "Kosovan",
        "Israel": "Israeli",
        "Georgia": "Georgian",
    }

    try:
        get_with_retry(driver, team_url)
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

    # JSON fallback for attendance when TM scraping returns nothing
    # (e.g. newly-promoted clubs whose 25/26 TM page shows '-' for that season,
    #  or clubs that TM hasn't yet populated with current-season data).
    # Set "average_attendance" in the team's JSON entry as a last-resort override.
    if average_attendance is None and team_data.get("average_attendance"):
        average_attendance = team_data["average_attendance"]
        logging.info(
            f"[Team: {team_name}] average_attendance → {average_attendance} (JSON fallback)"
        )

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
    native_lang = COUNTRY_WIKI_LANG.get(country_name)
    season = season_override or data["league"]["season"]
    # Stamp the league with the season this scrape reflects, so the site can show
    # per-league freshness while other leagues still carry last season's data.
    display_season = normalize_season(season)
    if display_season and league.season != display_season:
        league.season = display_season
        league.save(update_fields=["season"])
    logging.info(f"Scraping {league.name} ({country_name}), season {season}"
                 + (f" [native fallback: {native_lang}.wikipedia]" if native_lang else ""))

    for team_data in data["teams"]:
        logging.info("-----------------------------------------")
        logging.info(f"Processing team: {team_data.get('name')}")

        stadium_data = team_data.get("stadium", {})
        city_data = stadium_data.get("city", {})

        city = scrape_city(city_data, country=country_name)
        stadium = scrape_stadium(stadium_data, city, native_lang=native_lang)
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

    # If every team has 0 titles, the NATIONALITY_MAP adjective is almost certainly wrong.
    all_zero_titles = all((t.num_of_titles or 0) == 0 for t in teams)

    warnings = sum(
        len(v) for k, v in issues.items() if k != "missing_coords"
    )
    errors = len(issues["missing_coords"])
    if all_zero_titles:
        errors += 1

    lines = [
        f"\n=== Data Quality Report: {league.name} ({total} teams) ===",
        f"  UNKNOWN ownership  : {len(issues['unknown_ownership'])}",
        f"  Missing badge      : {len(issues['missing_badge'])}",
        f"  Missing capacity   : {len(issues['missing_capacity'])}",
        f"  Missing coordinates: {len(issues['missing_coords'])}",
        f"  Zero avg attendance: {len(issues['zero_attendance'])}",
    ]

    if all_zero_titles:
        lines.append(f"  [ERROR] All teams have 0 domestic titles — check NATIONALITY_MAP adjective for '{league.country.name}'")

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