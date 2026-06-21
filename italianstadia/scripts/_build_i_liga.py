"""One-off: build scripts/data/urls_i_liga.json for the 2025-26 Polish I liga.
Resolves real EN-Wikipedia URLs via the API; TM verein IDs taken from TM's own
I liga page. Existing DB stadium names are reused so the scrape links (not dupes)."""
import json, time, requests, re
from pathlib import Path

H = {"User-Agent": "ItalianStadiaBot/1.0 (learning project; contact example@example.com)"}
API = "https://en.wikipedia.org/w/api.php"

# name, tm_slug, vid, stadium_name (DB name if it already exists), stadium_title, city
CLUBS = [
    ("Chrobry Głogów", "chrobry-glogow", 8377, "Stadion przy ulicy Rudnowskiej", "Stadion przy ulicy Rudnowskiej", "Głogów"),
    ("GKS Tychy", "gks-tychy", 1750, "Tychy City Stadium", "Tychy City Stadium", "Tychy"),
    ("Górnik Łęczna", "gornik-leczna", 3291, "Górnik Łęczna Stadium", "Górnik Łęczna Stadium", "Łęczna"),
    ("ŁKS Łódź", "lks-lodz", 256, "Władysław Król Stadium", "Władysław Król Stadium", "Łódź"),
    ("Miedź Legnica", "miedz-legnica", 8936, "Stadion im. Orła Białego", "Stadion im. Orła Białego", "Legnica"),
    ("Odra Opole", "odra-opole", 5699, "Stadion Miejski w Opolu", "Stadion Miejski w Opolu", "Opole"),
    ("Pogoń Grodzisk Mazowiecki", "pogon-grodzisk-mazowiecki", 30998, "Stadion MOSiR w Grodzisku Mazowieckim", "Stadion MOSiR w Grodzisku Mazowieckim", "Grodzisk Mazowiecki"),
    ("Pogoń Siedlce", "pogon-siedlce", 4896, "Stadion Miejski w Siedlcach", "Stadion Miejski w Siedlcach", "Siedlce"),
    ("Polonia Bytom", "polonia-bytom", 7976, "Stadion Polonii Bytom", "Stadion Polonii Bytom", "Bytom"),
    ("Polonia Warsaw", "polonia-warschau", 2745, "Konwiktorska Street Stadium", "Konwiktorska Street Stadium", "Warsaw"),
    ("Puszcza Niepołomice", "puszcza-niepolomice", 28893, "Stadion Miejski w Niepołomicach", "Stadion Miejski w Niepołomicach", "Niepołomice"),
    ("Ruch Chorzów", "ruch-chorzow", 318, "Stadion Śląski", "Silesian Stadium", "Chorzów"),
    ("Stal Rzeszów", "stal-rzeszow", 9510, "Stadion Miejski w Rzeszowie", "Stadion Miejski w Rzeszowie", "Rzeszów"),
    ("Stal Mielec", "stal-mielec", 22431, "Grzegorz Lato Stadium", "Grzegorz Lato Stadium", "Mielec"),
    ("Śląsk Wrocław", "slask-wroclaw", 759, "Tarczyński Arena", "Stadion Wrocław", "Wrocław"),
    ("Wieczysta Kraków", "wieczysta-krakow", 30974, "ArcelorMittal Park", "ArcelorMittal Park", "Sosnowiec"),
    ("Wisła Kraków", "wisla-krakau", 422, "Stadion Miejski (Kraków)", "Henryk Reyman Municipal Stadium", "Kraków"),
    ("Znicz Pruszków", "znicz-pruszkow", 9109, "Znicz Stadium", "Znicz Stadium", "Pruszków"),
]


def wiki(title):
    """Return canonical EN-wiki URL if the page exists (follows redirects), else ''."""
    if not title:
        return ""
    try:
        d = requests.get(API, params={"action": "query", "titles": title,
                                      "redirects": 1, "format": "json"},
                         headers=H, timeout=20).json()
        for p in d["query"]["pages"].values():
            if "missing" not in p:
                return "https://en.wikipedia.org/wiki/" + p["title"].replace(" ", "_")
        # fallback: search
        s = requests.get(API, params={"action": "query", "list": "search",
                                      "srsearch": title, "srlimit": 1, "format": "json"},
                         headers=H, timeout=20).json()
        hits = s.get("query", {}).get("search", [])
        if hits:
            return "https://en.wikipedia.org/wiki/" + hits[0]["title"].replace(" ", "_")
    except Exception as e:
        print("  wiki err", title, str(e)[:60])
    return ""


teams = []
for name, slug, vid, st_name, st_title, city in CLUBS:
    cw = wiki(name); time.sleep(0.4)
    sw = wiki(st_title); time.sleep(0.4)
    ci = wiki(city); time.sleep(0.4)
    teams.append({
        "name": name,
        "wikipedia_url": cw,
        "transfermarkt_url": f"https://www.transfermarkt.com/{slug}/startseite/verein/{vid}",
        "transfermarkt_attendance_url": f"https://www.transfermarkt.com/{slug}/besucherzahlenentwicklung/verein/{vid}",
        "stadium": {
            "name": st_name,
            "wikipedia_url": sw,
            "transfermarkt_url": f"https://www.transfermarkt.com/{slug}/stadion/verein/{vid}",
            "city": {"name": city, "wikipedia_url": ci},
        },
    })
    print(f"{name:26} club={'Y' if cw else '-'} stadium={'Y' if sw else '-'} city={'Y' if ci else '-'}")

out = {"league": {"name": "I liga", "country": "Poland", "country_code": "PL",
                  "division_level": 2, "season": "25/26"},
       "teams": teams}
Path("scripts/data/urls_i_liga.json").write_text(
    json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
print("\nwrote scripts/data/urls_i_liga.json |",
      sum(1 for t in teams if not t["stadium"]["wikipedia_url"]), "stadiums missing wiki")
