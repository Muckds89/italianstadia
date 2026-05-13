import json

GIRONE_A = {
    "Inter U23",
    "LR Vicenza",
    "Union Brescia",
    "AS Cittadella",
    "Calcio Lecco 1912",
    "AC Trento",
    "Dolomiti Bellunesi",
    "Alcione Milano",
    "FC Pro Vercelli 1892",
    "Novara FC",
    "FC Lumezzane",
    "AC Renate",
    "Virtusvecomp Verona",
    "AS Giana Erminio",
    "UC AlbinoLeffe",
    "Arzignano Valchiampo",
    "Aurora Pro Patria",
    "CPR Ospitaletto",
    "US Pergolettese 1932",
    "US Triestina",
}

GIRONE_B = {
    "Juventus Next Gen",
    "SS Arezzo",
    "Ascoli Calcio",
    "Ternana Calcio",
    "Ravenna FC",
    "AC Perugia Calcio",
    "Forlì FC",
    "US Città di Pontedera",
    "US Livorno 1915",
    "Vis Pesaro 1898",
    "Guidonia Montecelio 1937 FC",
    "US Sambenedettese",
    "Pineto Calcio",
    "AS Gubbio 1910",
    "Campobasso FC",
    "SEF Torres 1903",
    "AC Carpi",
    "US Pianese",
    "AC Bra",
    "Rimini FC",
}

GIRONE_C = {
    "Atalanta U23",
    "Benevento Calcio",
    "US Salernitana 1919",
    "Catania FC",
    "Cosenza Calcio",
    "Casertana FC",
    "Potenza Calcio",
    "Casarano Calcio",
    "FC Crotone",
    "Calcio Foggia 1920",
    "Giugliano Calcio 1928",
    "FC Trapani 1905",
    "Latina Calcio 1932",
    "SS Monopoli 1966",
    "Audace Cerignola",
    "ASD Team Altamura",
    "Cavese 1919",
    "AZ Picerno",
    "Sorrento 1945",
    "Siracusa Calcio",
}

with open("./transfermrkt_urls.json", "r", encoding="utf-8") as f:
    data = json.load(f)

for team in data["teams"]:
    name = team["name"]
    tier = team["tier"]

    if tier in [1, 2]:
        team["girone"] = None

    elif tier == 3:
        if name in GIRONE_A:
            team["girone"] = "A"
        elif name in GIRONE_B:
            team["girone"] = "B"
        elif name in GIRONE_C:
            team["girone"] = "C"
        else:
            team["girone"] = None
            print(f"Missing Serie C girone for: {name}")

    elif tier == 4:
        if name == "Reggina":
            team["girone"] = "I"
        else:
            team["girone"] = None
            print(f"Missing Serie D girone for: {name}")

def main():
    with open("./transfermrkt_urls_with_girone.json", "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

if __name__ == "__main__":
    main()