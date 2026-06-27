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
    var badgeMode = el.dataset.badges || "";   // "flag" (national) | "club" (club crest)
    var useBadges = !!badgeMode;
    function badgeIcon(url, fit) {
      return L.divIcon({
        className: "insight-badge",
        html: '<img src="' + url + '" style="width:32px;height:32px;border-radius:50%;'
            + 'object-fit:' + (fit || "cover") + ';border:2px solid #fff;'
            + 'box-shadow:0 1px 4px rgba(0,0,0,.5);background:#fff">',
        iconSize: [32, 32], iconAnchor: [16, 16],
      });
    }
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
          // National-team flag badge when requested (falls back to a dot if no flag)
          var flag = null;
          if (useBadges) {
            var teams = p.teams || [];
            var pick = badgeMode === "club"
              ? (teams.filter(function (t) { return !t.is_national; })[0] || teams[0])
              : (teams.filter(function (t) { return t.is_national; })[0] || teams[0]);
            flag = pick && pick.image_url ? pick.image_url : null;
          }
          var marker = flag
            ? L.marker(ll, { icon: badgeIcon(flag, badgeMode === "club" ? "contain" : "cover") })
            : L.circleMarker(ll, {
                radius: radius, color: "#111", weight: 1, fillColor: color, fillOpacity: 0.85,
              });
          marker.addTo(map).bindPopup(
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
    // 11-class blue -> red palette (low -> high density). Quantile classes give every
    // class roughly equal countries, so the map uses the full colour range.
    var PALETTE = ["#3288bd", "#5aa0c4", "#85c0a8", "#abdda4", "#d6ef9b", "#ffffbf",
                   "#fee08b", "#fdae61", "#f46d43", "#e34a33", "#b2182b"];
    var N = PALETTE.length;
    // Assign each country with data to a quantile bucket (0 = lowest .. N-1 = highest).
    var withData = Object.keys(density).sort(function (a, b) { return density[a] - density[b]; });
    var bucketOf = {};
    withData.forEach(function (nm, i) {
      bucketOf[nm] = Math.min(N - 1, Math.floor(i / withData.length * N));
    });
    // Quantile thresholds (min value entering each bucket) for the legend.
    var thresholds = [];
    for (var k = 0; k < N; k++) {
      var idx = Math.floor(k / N * withData.length);
      thresholds.push(density[withData[idx]]);
    }
    function fill(name) {
      if (density[name] == null) return "#374151";
      return PALETTE[bucketOf[name]];
    }
    var EUROPE = L.latLngBounds([34, -11], [71, 45]);
    var selected = null;
    fetch(el.dataset.countriesUrl)
      .then(function (r) { return r.json(); })
      .then(function (gj) {
        var dataBounds = L.latLngBounds([]);
        L.geoJSON(gj, {
          style: function (feat) {
            var v = density[feat.properties.name];
            return { color: "#111", weight: 1, fillColor: fill(feat.properties.name),
                     fillOpacity: v == null ? 0.12 : 0.85 };
          },
          onEachFeature: function (feat, lyr) {
            var v = density[feat.properties.name];
            lyr.bindPopup("<strong>" + feat.properties.name + "</strong><br>" +
              (v == null ? "no data" : v + " stadiums / million people"));
            lyr.on("click", function () {
              if (selected) selected.setStyle({ color: "#111", weight: 1 });
              lyr.setStyle({ color: "#00e5ff", weight: 3 });
              lyr.bringToFront();
              selected = lyr;
            });
            if (v != null && feat.properties.name !== "Russia") {
              try { dataBounds.extend(lyr.getBounds()); } catch (e) {}
            }
          },
        }).addTo(map);
        var b = (dataBounds.isValid() ? dataBounds : EUROPE);
        try { map.fitBounds(b.pad(0.05), { maxZoom: 5 }); } catch (e) { map.fitBounds(EUROPE); }
      });
    // Legend: a few representative quantile bins (high -> low) + no-data.
    var leg = [];
    [N - 1, Math.round(N * 0.7), Math.round(N * 0.4), 0].forEach(function (k) {
      leg.push({ color: PALETTE[k], label: "≥ " + thresholds[k] + " / M" });
    });
    leg.push({ color: "#374151", label: "No data" });
    legend(leg);
  }
})();
