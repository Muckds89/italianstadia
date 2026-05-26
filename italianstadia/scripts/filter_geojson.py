import json, os

src = "italiastadiaapp/static/data/ne_110m_admin_0_countries.geojson"
with open(src, encoding="utf-8") as f:
    data = json.load(f)

needed = {
    "Italy", "Germany", "United Kingdom", "France", "Spain",
    "Netherlands", "Portugal", "Turkey", "Belgium"
}
filtered = [feat for feat in data["features"] if feat["properties"].get("name") in needed]
print("Kept", len(filtered), "of", len(data["features"]), "features")

out = {"type": "FeatureCollection", "features": filtered}
with open(src, "w", encoding="utf-8") as f:
    json.dump(out, f, separators=(",", ":"))

size = os.path.getsize(src)
print("Filtered file:", size // 1024, "KB")
