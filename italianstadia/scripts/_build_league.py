"""Build urls_<slug>.json for several leagues. Resolves real EN-Wikipedia URLs via
the API and percent-encodes them. Run, then null mis-resolved stadiums and validate."""
import json, time, requests
from urllib.parse import quote
from pathlib import Path

H = {"User-Agent": "ItalianStadiaBot/1.0 (learning project; contact example@example.com)"}
API = "https://en.wikipedia.org/w/api.php"

LEAGUES = [
    ("urls_3_liga.json",
     {"name": "3. Liga", "country": "Germany", "country_code": "DE", "division_level": 3, "season": "25/26"},
     [
        ("Alemannia Aachen", "alemannia-aachen", 8, "New Tivoli", "Tivoli (2009)", "Aachen"),
        ("Erzgebirge Aue", "fc-erzgebirge-aue", 94, "Erzgebirgsstadion", "Erzgebirgsstadion", "Aue"),
        ("Energie Cottbus", "fc-energie-cottbus", 25, "Stadion der Freundschaft", "Stadion der Freundschaft (Cottbus)", "Cottbus"),
        ("MSV Duisburg", "msv-duisburg", 52, "Schauinsland-Reisen-Arena", "Schauinsland-Reisen-Arena", "Duisburg"),
        ("Rot-Weiss Essen", "rot-weiss-essen", 56, "Stadion an der Hafenstraße", "Stadion Essen", "Essen"),
        ("TSV Havelse", "tsv-havelse", 476, "Eilenriedestadion", "Eilenriedestadion", "Hanover"),
        ("TSG Hoffenheim II", "tsg-1899-hoffenheim-ii", 983, "Dietmar-Hopp-Stadion", "Dietmar-Hopp-Stadion", "Sinsheim"),
        ("FC Ingolstadt", "fc-ingolstadt-04", 4795, "Audi Sportpark", "Audi Sportpark", "Ingolstadt"),
        ("Viktoria Köln", "fc-viktoria-koln", 1622, "Sportpark Höhenberg", "Höhenberg Sports Park", "Cologne"),
        ("SV Waldhof Mannheim", "sv-waldhof-mannheim", 85, "Carl-Benz-Stadion", "Carl-Benz-Stadion", "Mannheim"),
        ("1860 Munich", "tsv-1860-munchen", 72, "Grünwalder Stadion", "Grünwalder Stadion", "Munich"),
        ("VfL Osnabrück", "vfl-osnabruck", 81, "Stadion an der Bremer Brücke", "Stadion an der Bremer Brücke", "Osnabrück"),
        ("Jahn Regensburg", "ssv-jahn-regensburg", 109, "Jahnstadion Regensburg", "Jahnstadion Regensburg", "Regensburg"),
        ("Hansa Rostock", "fc-hansa-rostock", 30, "Ostseestadion", "Ostseestadion", "Rostock"),
        ("1. FC Saarbrücken", "1-fc-saarbrucken", 1, "Ludwigsparkstadion", "Ludwigsparkstadion", "Saarbrücken"),
        ("1. FC Schweinfurt 05", "1-fc-schweinfurt-05", 103, "Willy-Sachs-Stadion", "Willy-Sachs-Stadion", "Schweinfurt"),
        ("VfB Stuttgart II", "vfb-stuttgart-ii", 102, "WIRmachenDRUCK Arena", "Stadion Aspach", "Aspach"),
        ("SSV Ulm", "ssv-ulm-1846", 69, "Donaustadion", "Donaustadion", "Ulm"),
        ("SC Verl", "sc-verl", 93, "Sportclub Arena", "Sportclub Arena", "Verl"),
        ("SV Wehen Wiesbaden", "sv-wehen-wiesbaden", 108, "BRITA-Arena", "BRITA-Arena", "Wiesbaden"),
     ]),
    ("urls_ligue_2.json",
     {"name": "Ligue 2", "country": "France", "country_code": "FR", "division_level": 2, "season": "25/26"},
     [
        ("Amiens SC", "amiens-sc", 1416, "Stade de la Licorne", "Stade de la Licorne", "Amiens"),
        ("FC Annecy", "fc-annecy", 30204, "Parc des Sports", "Parc des Sports (Annecy)", "Annecy"),
        ("SC Bastia", "sc-bastia", 595, "Stade Armand Cesari", "Stade Armand Cesari", "Bastia"),
        ("US Boulogne", "us-boulogne", 7042, "Stade de la Libération", "Stade de la Libération", "Boulogne-sur-Mer"),
        ("Clermont Foot", "clermont-foot-63", 3524, "Stade Gabriel Montpied", "Stade Gabriel Montpied", "Clermont-Ferrand"),
        ("USL Dunkerque", "usl-dunkerque", 9202, "Stade Marcel Tribut", "Stade Marcel-Tribut", "Dunkirk"),
        ("Grenoble Foot 38", "grenoble-foot-38", 1290, "Stade des Alpes", "Stade des Alpes", "Grenoble"),
        ("En Avant Guingamp", "ea-guingamp", 855, "Stade de Roudourou", "Stade de Roudourou", "Guingamp"),
        ("Stade Lavallois", "stade-laval", 1080, "Stade Francis Le Basser", "Stade Francis-Le Basser", "Laval"),
        ("Le Mans FC", "le-mans-fc", 1164, "Stade Marie-Marvingt", "MMArena", "Le Mans"),
        ("Montpellier HSC", "montpellier-hsc", 969, "Stade de la Mosson", "Stade de la Mosson", "Montpellier"),
        ("AS Nancy Lorraine", "as-nancy-lorraine", 1159, "Stade Marcel Picot", "Stade Marcel-Picot", "Nancy"),
        ("Pau FC", "pau-fc", 3166, "Nouste Camp", "Stade du Hameau", "Pau"),
        ("Red Star FC", "red-star-fc", 1154, "Stade Bauer", "Stade Bauer", "Saint-Ouen-sur-Seine"),
        ("Stade de Reims", "stade-reims", 1421, "Stade Auguste-Delaune", "Stade Auguste-Delaune", "Reims"),
        ("Rodez AF", "rodez-af", 11273, "Stade Paul Lignon", "Stade Paul-Lignon", "Rodez"),
        ("AS Saint-Étienne", "as-saint-etienne", 618, "Stade Geoffroy Guichard", "Stade Geoffroy-Guichard", "Saint-Étienne"),
        ("ES Troyes AC", "es-troyes-ac", 1095, "Stade de l'Aube", "Stade de l'Aube", "Troyes"),
     ]),
    ("urls_eerste_divisie.json",
     {"name": "Eerste Divisie", "country": "Netherlands", "country_code": "NL", "division_level": 2, "season": "25/26"},
     [
        ("ADO Den Haag", "ado-den-haag", 1268, "Bingoal Stadion", "Bingoal Stadion", "The Hague"),
        ("Almere City", "almere-city-fc", 723, "Yanmar Stadion", "Yanmar Stadion", "Almere"),
        ("SC Cambuur", "sc-cambuur-leeuwarden", 133, "Cambuur Stadion", "Cambuur Stadion", "Leeuwarden"),
        ("De Graafschap", "de-graafschap-doetinchem", 642, "Stadion De Vijverberg", "De Vijverberg", "Doetinchem"),
        ("FC Den Bosch", "fc-den-bosch", 404, "Stadion De Vliert", "De Vliert", "'s-Hertogenbosch"),
        ("FC Dordrecht", "fc-dordrecht", 1455, "Stadion Krommedijk", "Stadion Krommedijk", "Dordrecht"),
        ("FC Eindhoven", "fc-eindhoven", 3892, "Jan Louwers Stadion", "Jan Louwers Stadion", "Eindhoven"),
        ("FC Emmen", "fc-emmen", 1283, "De Oude Meerdijk", "De Oude Meerdijk", "Emmen"),
        ("Helmond Sport", "helmond-sport", 500, "Lavans Stadion", "Lavans Stadion", "Helmond"),
        ("Jong Ajax", "ajax-amsterdam-ii", 8817, "Sportpark De Toekomst", "De Toekomst", "Amsterdam"),
        ("Jong AZ", "az-alkmaar-ii", 11368, "AFAS Trainingscomplex", "", "Alkmaar"),
        ("Jong PSV", "psv-eindhoven-ii", 9715, "De Herdgang", "De Herdgang", "Eindhoven"),
        ("Jong FC Utrecht", "fc-utrecht-ii", 17596, "Sportcomplex Zoudenbalch", "", "Utrecht"),
        ("MVV Maastricht", "mvv-maastricht", 384, "Stadion De Geusselt", "De Geusselt", "Maastricht"),
        ("RKC Waalwijk", "rkc-waalwijk", 235, "Mandemakers Stadion", "Mandemakers Stadion", "Waalwijk"),
        ("Roda JC Kerkrade", "roda-jc-kerkrade", 192, "Parkstad Limburg Stadion", "Parkstad Limburg Stadion", "Kerkrade"),
        ("TOP Oss", "top-oss", 1228, "Frans Heesen Stadion", "Frans Heesen Stadion", "Oss"),
        ("SBV Vitesse", "vitesse-arnheim", 499, "GelreDome", "GelreDome", "Arnhem"),
        ("VVV-Venlo", "vvv-venlo", 1426, "Covebo Stadion - De Koel", "De Koel", "Venlo"),
        ("Willem II", "willem-ii-tilburg", 403, "Koning Willem II Stadion", "Koning Willem II Stadion", "Tilburg"),
     ]),
    ("urls_liga_portugal_2.json",
     {"name": "Liga Portugal 2", "country": "Portugal", "country_code": "PT", "division_level": 2, "season": "25/26"},
     [
        ("Académico de Viseu", "academico-viseu-fc", 7788, "Estádio do Fontelo", "Estádio do Fontelo", "Viseu"),
        ("Benfica B", "benfica-lissabon-b", 10330, "Benfica Campus", "Benfica Campus", "Seixal"),
        ("Chaves", "gd-chaves", 3325, "Estádio Municipal de Chaves", "Estádio Municipal de Chaves", "Chaves"),
        ("Farense", "sc-farense", 4294, "Estádio de São Luís", "Estádio de São Luís", "Faro"),
        ("Feirense", "cd-feirense", 3349, "Estádio Marcolino de Castro", "Estádio Marcolino de Castro", "Santa Maria da Feira"),
        ("Felgueiras 1932", "fc-felgueiras-1932", 1701, "Estádio Dr. Machado de Matos", "Estádio Dr. Machado de Matos", "Felgueiras"),
        ("Leixões", "leixoes-sc", 3345, "Estádio do Mar", "Estádio do Mar", "Matosinhos"),
        ("Lusitânia de Lourosa", "lusitania-fc-lourosa", 8189, "Estádio do Lusitânia de Lourosa", "", "Lourosa"),
        ("Marítimo", "cs-maritimo", 1301, "Estádio do Marítimo", "Estádio dos Barreiros", "Funchal"),
        ("UD Oliveirense", "ud-oliveirense", 8827, "Estádio Carlos Osório", "", "Oliveira de Azeméis"),
        ("Paços de Ferreira", "fc-pacos-de-ferreira", 2995, "Estádio Capital do Móvel", "Estádio Capital do Móvel", "Paços de Ferreira"),
        ("Penafiel", "fc-penafiel", 3327, "Estádio Municipal 25 de Abril", "Estádio Municipal 25 de Abril (Penafiel)", "Penafiel"),
        ("Portimonense", "portimonense-sc", 7378, "Estádio Municipal de Portimão", "Estádio Municipal de Portimão", "Portimão"),
        ("Porto B", "fc-porto-b", 10331, "Estádio Luís Filipe Menezes", "", "Vila Nova de Gaia"),
        ("Sporting CP B", "sporting-lissabon-b", 10949, "Estádio Aurélio Pereira", "", "Alcochete"),
        ("Torreense", "sc-uniao-torreense", 2432, "Estádio Manuel Marques", "", "Torres Vedras"),
        ("União de Leiria", "uniao-leiria", 2639, "Estádio Dr. Magalhães Pessoa", "Estádio Municipal de Leiria", "Leiria"),
        ("Vizela", "fc-vizela", 6912, "Estádio do FC Vizela", "Estádio do Futebol Clube de Vizela", "Vizela"),
     ]),
    ("urls_primera_federacion.json",
     {"name": "Primera Federación", "country": "Spain", "country_code": "ES", "division_level": 3, "season": "25/26"},
     [
        ("Arenas Club", "arenas-club", 16122, "Campo Municipal de Gobela", "Campo Municipal de Gobela", "Getxo"),
        ("CD Arenteiro", "cd-arenteiro", 58946, "Espiñedo", "", "O Carballiño"),
        ("Real Avilés", "real-aviles-cf", 20844, "Estadio Román Suárez Puerta", "Román Suárez Puerta", "Avilés"),
        ("Barakaldo", "fc-barakaldo", 3708, "Lasesarre", "Lasesarre", "Barakaldo"),
        ("Bilbao Athletic", "athletic-bilbao-b", 6688, "Lezama", "Lezama Facilities", "Bilbao"),
        ("Cacereño", "cp-cacereno", 11602, "Estadio Príncipe Felipe", "Príncipe Felipe Stadium", "Cáceres"),
        ("Celta Fortuna", "celta-vigo-b", 8733, "Estadio Abanca-Balaídos", "Balaídos", "Vigo"),
        ("CD Guadalajara", "cd-guadalajara", 16576, "Estadio Pedro Escartín", "Pedro Escartín", "Guadalajara"),
        ("CD Lugo", "cd-lugo", 11000, "Estadio Anxo Carro", "Anxo Carro", "Lugo"),
        ("Mérida AD", "merida-ad", 46854, "Estadio Romano", "Estadio Romano José Fouto", "Mérida"),
        ("Osasuna B", "ca-osasuna-b", 8516, "Tajonar", "Tajonar Facilities", "Pamplona"),
        ("Ourense CF", "fc-ourense", 55398, "Estadio O Couto", "Estadio O Couto", "Ourense"),
        ("Ponferradina", "sd-ponferradina", 4032, "Estadio El Toralín", "El Toralín", "Ponferrada"),
        ("Pontevedra", "pontevedra-cf", 5650, "Estadio de Pasarón", "Estadio Municipal de Pasarón", "Pontevedra"),
        ("Racing de Ferrol", "racing-ferrol", 1176, "Estadio da Malata", "A Malata", "Ferrol"),
        ("Real Madrid Castilla", "real-madrid-b-castilla-", 6767, "Estadio Alfredo Di Stéfano", "Alfredo Di Stéfano Stadium", "Madrid"),
        ("CF Talavera", "cf-talavera-de-la-reina", 47421, "El Prado", "", "Talavera de la Reina"),
        ("Tenerife", "cd-teneriffa", 648, "Estadio Heliodoro Rodríguez López", "Estadio Heliodoro Rodríguez López", "Santa Cruz de Tenerife"),
        ("Unionistas", "unionistas-cf", 52397, "Estadio Reina Sofía", "", "Salamanca"),
        ("Zamora", "fc-zamora", 10907, "Estadio Ruta de la Plata", "Estadio Ruta de la Plata", "Zamora"),
        ("AD Alcorcón", "ad-alcorcon", 11596, "Estadio Santo Domingo", "Estadio Municipal de Santo Domingo", "Alcorcón"),
        ("Algeciras", "fc-algeciras", 3705, "Nuevo Mirador", "Estadio Nuevo Mirador", "Algeciras"),
        ("Antequera", "antequera-cf", 16022, "El Maulí", "Estadio El Maulí", "Antequera"),
        ("Atlético Madrileño", "atletico-madrid-b", 3679, "Centro Deportivo Alcalá de Henares", "", "Alcalá de Henares"),
        ("Atlético Sanluqueño", "atletico-sanluqueno", 21322, "El Palmar", "Estadio El Palmar", "Sanlúcar de Barrameda"),
        ("Betis Deportivo", "real-betis-sevilla-b", 2865, "Ciudad Deportiva Luis del Sol", "", "Seville"),
        ("FC Cartagena", "fc-cartagena", 7077, "Estadio Cartagonova", "Cartagonova", "Cartagena"),
        ("CD Eldense", "cd-eldense", 12567, "Estadio Pepico Amat", "Nuevo Pepico Amat", "Elda"),
        ("CE Europa", "ce-europa", 20528, "Nou Sardenya", "Nou Sardenya", "Barcelona"),
        ("Gimnàstic", "gimnastic-de-tarragona", 5648, "Nou Estadi", "Nou Estadi", "Tarragona"),
        ("Hércules", "hercules-alicante", 7971, "Estadio José Rico Pérez", "José Rico Pérez", "Alicante"),
        ("UD Ibiza", "ud-ibiza", 13241, "Can Misses", "Estadi Municipal de Can Misses", "Ibiza"),
        ("Juventud Torremolinos", "juventud-torremolinos-cf", 43454, "El Pozuelo", "", "Torremolinos"),
        ("Marbella", "marbella-fc", 12361, "Estadio Municipal de Marbella", "", "Marbella"),
        ("Real Murcia", "real-murcia", 171, "Estadio Enrique Roca", "Estadio Enrique Roca", "Murcia"),
        ("CE Sabadell", "ce-sabadell", 11422, "Nova Creu Alta", "Nova Creu Alta", "Sabadell"),
        ("Sevilla Atlético", "fc-sevilla-b-atletico-", 8519, "Estadio Jesús Navas", "Estadio Jesús Navas", "Seville"),
        ("SD Tarazona", "sd-tarazona", 41403, "Municipal de Tarazona", "", "Tarazona"),
        ("CD Teruel", "cd-teruel", 19301, "Pinilla", "Estadio Pinilla", "Teruel"),
        ("Villarreal B", "fc-villarreal-b", 11972, "Estadio de la Cerámica", "Estadio de la Cerámica", "Villarreal"),
     ]),
]


def _enc(u):
    if not u or "/wiki/" not in u:
        return u
    base, title = u.split("/wiki/", 1)
    return base + "/wiki/" + quote(title, safe="_(),")


def wiki(title):
    if not title:
        return ""
    try:
        d = requests.get(API, params={"action": "query", "titles": title, "redirects": 1,
                                      "format": "json"}, headers=H, timeout=20).json()
        for p in d["query"]["pages"].values():
            if "missing" not in p:
                return _enc("https://en.wikipedia.org/wiki/" + p["title"].replace(" ", "_"))
        s = requests.get(API, params={"action": "query", "list": "search", "srsearch": title,
                                      "srlimit": 1, "format": "json"}, headers=H, timeout=20).json()
        hits = s.get("query", {}).get("search", [])
        if hits:
            return _enc("https://en.wikipedia.org/wiki/" + hits[0]["title"].replace(" ", "_"))
    except Exception as e:
        print("  wiki err", title, str(e)[:50])
    return ""


for OUT, META, CLUBS in LEAGUES:
    teams = []
    print(f"\n### {META['name']} ({len(CLUBS)})")
    for name, slug, vid, st_name, st_title, city in CLUBS:
        cw, sw, ci = wiki(name), wiki(st_title), wiki(city)
        time.sleep(0.3)
        teams.append({
            "name": name, "wikipedia_url": cw,
            "transfermarkt_url": f"https://www.transfermarkt.com/{slug}/startseite/verein/{vid}",
            "transfermarkt_attendance_url": f"https://www.transfermarkt.com/{slug}/besucherzahlenentwicklung/verein/{vid}",
            "stadium": {"name": st_name, "wikipedia_url": sw,
                        "transfermarkt_url": f"https://www.transfermarkt.com/{slug}/stadion/verein/{vid}",
                        "city": {"name": city, "wikipedia_url": ci}},
        })
        print(f"  {name:24} club={'Y' if cw else '-'} stad={(sw.split('/wiki/')[-1] if sw else 'MISSING')}")
    Path("scripts/data/" + OUT).write_text(
        json.dumps({"league": META, "teams": teams}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  -> wrote {OUT}")
