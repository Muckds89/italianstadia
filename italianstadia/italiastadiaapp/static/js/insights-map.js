/* Shared map for the /insights/ pages. Driven by data- attributes on #insight-map:
 *   data-mode="markers"  data-geojson-url=...  data-color-by="surface|national"
 *   data-mode="choropleth"  data-countries-url=...  data-density='{"Italy":1.2,...}'
 * Uses Leaflet (loaded by the template). No build step.
 */
(function () {
  var el = document.getElementById("insight-map");
  if (!el || typeof L === "undefined") return;

  var map = L.map(el, { scrollWheelZoom: false }).setView([54, 15], 4);
  L.tileLayer("https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png", {
    attribution: "&copy; OpenStreetMap &copy; CARTO", maxZoom: 18,
  }).addTo(map);

  var SURFACE = {
    GRASS: { color: "#22c55e", label: "Natural grass" },
    HYBRID: { color: "#14b8a6", label: "Hybrid" },
    ARTIFICIAL: { color: "#f59e0b", label: "Artificial" },
  };
  var mode = el.dataset.mode || "markers";
  var stadiumUrlPrefix = el.dataset.stadiumUrlPrefix || "/stadium/";

  function legend(items) {
    var lg = L.control({ position: "bottomright" });
    lg.onAdd = function () {
      var d = L.DomUtil.create("div", "insight-legend");
      d.style.cssText = "background:#1f2937;color:#fff;padding:8px 10px;border-radius:6px;font:12px/1.5 sans-serif;box-shadow:0 1px 4px rgba(0,0,0,.4)";
      d.innerHTML = items.map(function (i) {
        return '<div><span style="display:inline-block;width:11px;height:11px;border-radius:50%;background:' +
          i.color + ';margin-right:6px"></span>' + i.label + "</div>";
      }).join("");
      return d;
    };
    lg.addTo(map);
  }

  if (mode === "markers") {
    var colorBy = el.dataset.colorBy || "single";
    fetch(el.dataset.geojsonUrl)
      .then(function (r) { return r.json(); })
      .then(function (fc) {
        var bounds = [];
        (fc.features || []).forEach(function (f) {
          var c = f.geometry && f.geometry.coordinates;
          if (!c) return;
          var p = f.properties || {};
          var color = "#3b82f6";
          if (colorBy === "surface") color = (SURFACE[p.surface] || {}).color || "#9ca3af";
          var radius = 6;
          if (colorBy === "capacity") {
            // scale radius 4–16 by capacity; warmer colour for bigger grounds
            var cap0 = p.capacity || 0;
            radius = Math.max(4, Math.min(16, 4 + Math.sqrt(cap0) / 50));
            color = cap0 >= 60000 ? "#ef4444" : cap0 >= 40000 ? "#f59e0b"
                  : cap0 >= 20000 ? "#22c55e" : "#3b82f6";
          }
          var ll = [c[1], c[0]];
          bounds.push(ll);
          var cap = p.capacity ? p.capacity.toLocaleString() + " seats" : "";
          L.circleMarker(ll, {
            radius: radius, color: "#111", weight: 1, fillColor: color, fillOpacity: 0.85,
          }).addTo(map).bindPopup(
            '<strong><a href="' + stadiumUrlPrefix + (p.slug || p.id) + '/">' + p.name + "</a></strong><br>" +
            (p.city ? p.city + (p.country ? ", " + p.country : "") + "<br>" : "") +
            (colorBy === "surface" && p.surface ? (SURFACE[p.surface] || {}).label + "<br>" : "") + cap
          );
        });
        if (bounds.length) map.fitBounds(bounds, { padding: [30, 30] });
        if (colorBy === "surface") {
          legend(Object.keys(SURFACE).map(function (k) {
            return { color: SURFACE[k].color, label: SURFACE[k].label };
          }));
        } else if (colorBy === "capacity") {
          legend([
            { color: "#ef4444", label: "60,000+" },
            { color: "#f59e0b", label: "40,000–60,000" },
            { color: "#22c55e", label: "20,000–40,000" },
            { color: "#3b82f6", label: "Under 20,000" },
          ]);
        }
      });
  } else if (mode === "choropleth") {
    var density = JSON.parse(el.dataset.density || "{}");
    var vals = Object.keys(density).map(function (k) { return density[k]; });
    var max = vals.length ? Math.max.apply(null, vals) : 1;
    function fill(v) {
      if (v == null) return "#374151";
      var t = Math.min(1, v / max);
      // dark teal -> bright yellow ramp
      var r = Math.round(20 + t * 235), g = Math.round(80 + t * 175), b = Math.round(90 - t * 60);
      return "rgb(" + r + "," + g + "," + b + ")";
    }
    fetch(el.dataset.countriesUrl)
      .then(function (r) { return r.json(); })
      .then(function (gj) {
        var layer = L.geoJSON(gj, {
          style: function (feat) {
            var v = density[feat.properties.name];
            return { color: "#111", weight: 1, fillColor: fill(v), fillOpacity: v == null ? 0.15 : 0.8 };
          },
          onEachFeature: function (feat, lyr) {
            var v = density[feat.properties.name];
            lyr.bindPopup("<strong>" + feat.properties.name + "</strong><br>" +
              (v == null ? "no data" : v + " stadiums / million people"));
          },
        }).addTo(map);
        try { map.fitBounds(layer.getBounds(), { padding: [20, 20] }); } catch (e) {}
      });
    legend([
      { color: fill(max), label: "More stadiums per capita" },
      { color: fill(max * 0.4), label: "Fewer" },
      { color: "#374151", label: "No data" },
    ]);
  }
})();
