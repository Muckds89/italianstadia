import csv
from pathlib import Path

rows = [
    (177, "FC Famalicão", 3329, "https://www.transfermarkt.com/fc-famalicao/startseite/verein/3329", "https://www.transfermarkt.com/fc-famalicao/besucherzahlenentwicklung/verein/3329", 3776),
    (181, "Casa Pia AC", 3268, "https://www.transfermarkt.com/casa-pia-ac/startseite/verein/3268", "https://www.transfermarkt.com/casa-pia-ac/besucherzahlenentwicklung/verein/3268", 2075),
    (644, "KTP Kotka", 7315, "https://www.transfermarkt.com/fc-ktp/startseite/verein/7315", "https://www.transfermarkt.com/fc-ktp/besucherzahlenentwicklung/verein/7315", ""),
    (647, "FK Željezničar", 2573, "https://www.transfermarkt.com/fk-zeljeznicar-sarajevo/startseite/verein/2573", "https://www.transfermarkt.com/fk-zeljeznicar-sarajevo/besucherzahlenentwicklung/verein/2573", ""),
    (655, "FK Sloga Doboj", 7569, "https://www.transfermarkt.com/fk-sloga-doboj/startseite/verein/7569", "https://www.transfermarkt.com/fk-sloga-doboj/besucherzahlenentwicklung/verein/7569", ""),
    (726, "Hibernians FC", 10604, "https://www.transfermarkt.com/hibernians-fc/startseite/verein/10604", "https://www.transfermarkt.com/hibernians-fc/besucherzahlenentwicklung/verein/10604", ""),
    (727, "Ħamrun Spartans", 17149, "https://www.transfermarkt.com/hamrun-spartans/startseite/verein/17149", "https://www.transfermarkt.com/hamrun-spartans/besucherzahlenentwicklung/verein/17149", ""),
    (728, "Valletta FC", 6335, "https://www.transfermarkt.com/valletta-fc/startseite/verein/6335", "https://www.transfermarkt.com/valletta-fc/besucherzahlenentwicklung/verein/6335", ""),
    (729, "Birkirkara FC", 10262, "https://www.transfermarkt.com/birkirkara-fc/startseite/verein/10262", "https://www.transfermarkt.com/birkirkara-fc/besucherzahlenentwicklung/verein/10262", ""),
    (730, "Floriana FC", 10603, "https://www.transfermarkt.com/floriana-fc/startseite/verein/10603", "https://www.transfermarkt.com/floriana-fc/besucherzahlenentwicklung/verein/10603", ""),
    (731, "Sliema Wanderers", 329, "https://www.transfermarkt.com/sliema-wanderers/startseite/verein/329", "https://www.transfermarkt.com/sliema-wanderers/besucherzahlenentwicklung/verein/329", ""),
    (732, "Mosta FC", 32125, "https://www.transfermarkt.com/mosta-fc/startseite/verein/32125", "https://www.transfermarkt.com/mosta-fc/besucherzahlenentwicklung/verein/32125", ""),
    (733, "Gżira United", 32768, "https://www.transfermarkt.com/gzira-united-fc/startseite/verein/32768", "https://www.transfermarkt.com/gzira-united-fc/besucherzahlenentwicklung/verein/32768", ""),
    (734, "Naxxar Lions", 32130, "https://www.transfermarkt.com/naxxar-lions-fc/startseite/verein/32130", "https://www.transfermarkt.com/naxxar-lions-fc/besucherzahlenentwicklung/verein/32130", ""),
    (735, "Tarxien Rainbows", 21395, "https://www.transfermarkt.com/tarxien-rainbows/startseite/verein/21395", "https://www.transfermarkt.com/tarxien-rainbows/besucherzahlenentwicklung/verein/21395", ""),
    (736, "Marsaxlokk FC", 10605, "https://www.transfermarkt.com/marsaxlokkfc/startseite/verein/10605", "https://www.transfermarkt.com/marsaxlokkfc/besucherzahlenentwicklung/verein/10605", ""),
    (737, "Żabbar St. Patrick", 34423, "https://www.transfermarkt.com/zabbar-st-patrick-fc/startseite/verein/34423", "https://www.transfermarkt.com/zabbar-st-patrick-fc/besucherzahlenentwicklung/verein/34423", ""),
    (804, "England", 3299, "https://www.transfermarkt.com/england/startseite/verein/3299", "https://www.transfermarkt.com/england/besucherzahlenentwicklung/verein/3299", ""),
    (805, "France", 3377, "https://www.transfermarkt.com/france/startseite/verein/3377", "https://www.transfermarkt.com/france/besucherzahlenentwicklung/verein/3377", ""),
    (806, "Wales", 3864, "https://www.transfermarkt.com/wales/startseite/verein/3864", "https://www.transfermarkt.com/wales/besucherzahlenentwicklung/verein/3864", ""),
    (807, "Scotland", 3380, "https://www.transfermarkt.com/schottland/startseite/verein/3380", "https://www.transfermarkt.com/schottland/besucherzahlenentwicklung/verein/3380", ""),
    (808, "Republic of Ireland", 3509, "https://www.transfermarkt.com/republic-of-ireland/startseite/verein/3509", "https://www.transfermarkt.com/republic-of-ireland/besucherzahlenentwicklung/verein/3509", ""),
    (809, "Netherlands", 3379, "https://www.transfermarkt.com/netherlands/startseite/verein/3379", "https://www.transfermarkt.com/netherlands/besucherzahlenentwicklung/verein/3379", ""),
    (810, "Portugal", 3300, "https://www.transfermarkt.com/portugal/startseite/verein/3300", "https://www.transfermarkt.com/portugal/besucherzahlenentwicklung/verein/3300", ""),
    (811, "Serbia", 3438, "https://www.transfermarkt.com/serbia/startseite/verein/3438", "https://www.transfermarkt.com/serbia/besucherzahlenentwicklung/verein/3438", ""),
    (812, "Hungary", 3468, "https://www.transfermarkt.com/hungary/startseite/verein/3468", "https://www.transfermarkt.com/hungary/besucherzahlenentwicklung/verein/3468", ""),
    (813, "Northern Ireland", 5674, "https://www.transfermarkt.com/northern-ireland/startseite/verein/5674", "https://www.transfermarkt.com/northern-ireland/besucherzahlenentwicklung/verein/5674", ""),
    (814, "Belgium", 3382, "https://www.transfermarkt.com/belgium/startseite/verein/3382", "https://www.transfermarkt.com/belgium/besucherzahlenentwicklung/verein/3382", ""),
    (815, "Poland", 3442, "https://www.transfermarkt.com/polen/startseite/verein/3442", "https://www.transfermarkt.com/polen/besucherzahlenentwicklung/verein/3442", ""),
    (816, "Romania", 3447, "https://www.transfermarkt.com/romania/startseite/verein/3447", "https://www.transfermarkt.com/romania/besucherzahlenentwicklung/verein/3447", ""),
    (817, "Albania", 3561, "https://www.transfermarkt.com/albanien/startseite/verein/3561", "https://www.transfermarkt.com/albanien/besucherzahlenentwicklung/verein/3561", ""),
    (818, "Armenia", 6219, "https://www.transfermarkt.com/armenia/startseite/verein/6219", "https://www.transfermarkt.com/armenia/besucherzahlenentwicklung/verein/6219", ""),
    (819, "Georgia", 3669, "https://www.transfermarkt.com/georgia/startseite/verein/3669", "https://www.transfermarkt.com/georgia/besucherzahlenentwicklung/verein/3669", ""),
    (820, "Azerbaijan", 8605, "https://www.transfermarkt.com/azerbaijan/startseite/verein/8605", "https://www.transfermarkt.com/azerbaijan/besucherzahlenentwicklung/verein/8605", ""),
]

path = Path("./missing_transfermarkt_data_with_attendance.csv")

with path.open("w", newline="", encoding="utf-8") as f:
    writer = csv.writer(f)
    writer.writerow([
        "team_id",
        "team_name",
        "transfermarkt_id",
        "transfermarkt_url",
        "image_url",
        "attendance_url",
        "average_attendance",
    ])
    for team_id, team_name, tm_id, tm_url, attendance_url, average_attendance in rows:
        image_url = f"https://tmssl.akamaized.net//images/wappen/head/{tm_id}.png"
        writer.writerow([
            team_id,
            team_name,
            tm_id,
            tm_url,
            image_url,
            attendance_url,
            average_attendance,
        ])

path.as_posix()
