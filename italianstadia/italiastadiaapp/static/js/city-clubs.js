(function () {
  "use strict";
  var dataEl = document.getElementById("city-data");
  var CITIES = dataEl ? JSON.parse(dataEl.textContent) : [];

  // ---- Tier filter -----------------------------------------------------------
  // mode: "all" | "1" | "12" | "2" | "3"
  function tierAllowed(mode, tier) {
    if (mode === "all") return true;
    if (mode === "12") return tier === 1 || tier === 2;
    return String(tier) === mode;
  }

  function applyFilter(mode) {
    document.querySelectorAll(".city-card").forEach(function (card) {
      var idx = card.getAttribute("data-idx");
      var visible = 0;
      card.querySelectorAll(".club-badge").forEach(function (b) {
        var tier = parseInt(b.getAttribute("data-tier"), 10) || 0;
        var show = tierAllowed(mode, tier);
        b.classList.toggle("is-hidden", !show);
        if (show) visible++;
      });
      var badge = card.querySelector(".city-count");
      if (badge) badge.textContent = visible;
      var hidden = visible < 2;   // out of scope once <2 clubs in chosen tiers
      card.classList.toggle("is-hidden", hidden);
      // keep the sidebar in sync
      var navItem = document.querySelector('.city-nav-item[data-idx="' + idx + '"]');
      if (navItem) {
        navItem.classList.toggle("is-hidden", hidden);
        var nc = navItem.querySelector(".nav-count");
        if (nc) nc.textContent = visible;
      }
    });
  }

  var filter = document.getElementById("tier-filter");
  if (filter) {
    filter.addEventListener("click", function (e) {
      var btn = e.target.closest("button[data-tier]");
      if (!btn) return;
      filter.querySelectorAll("button").forEach(function (b) {
        b.classList.toggle("btn-primary", b === btn);
        b.classList.toggle("btn-outline-primary", b !== btn);
      });
      applyFilter(btn.getAttribute("data-tier"));
    });
  }

  // ---- Sidebar search --------------------------------------------------------
  var navSearch = document.getElementById("city-nav-search");
  if (navSearch) {
    navSearch.addEventListener("input", function () {
      var q = navSearch.value.trim().toLowerCase();
      document.querySelectorAll(".city-nav-item").forEach(function (li) {
        var match = li.getAttribute("data-city").indexOf(q) !== -1;
        li.style.display = match ? "" : "none";
      });
    });
  }

  // ---- Lazy per-city maps (markers = club crests) ----------------------------
  function crestHtml(club) {
    return club.logo
      ? '<span class="crest-marker"><img src="' + club.logo + '" alt=""></span>'
      : '<span class="crest-marker ph">' + (club.name || "?").slice(0, 3) + '</span>';
  }

  // One icon per stadium location. Shared grounds (e.g. San Siro = AC Milan +
  // Inter) become a single combined badge listing every tenant's crest.
  function groupedIcon(clubs) {
    var size = 22;
    if (clubs.length === 1) {
      return L.divIcon({
        className: "",
        html: '<div class="crest-marker' + (clubs[0].logo ? "" : " ph") + '" ' +
              'style="width:' + size + 'px;height:' + size + 'px">' +
              (clubs[0].logo ? '<img src="' + clubs[0].logo + '" alt="">'
                             : (clubs[0].name || "?").slice(0, 3)) + '</div>',
        iconSize: [size, size], iconAnchor: [size / 2, size / 2],
        popupAnchor: [0, -size / 2],
      });
    }
    var html = '<div class="crest-cluster">' +
      clubs.map(crestHtml).join("") + '</div>';
    var w = clubs.length * (size - 2) + 6;
    return L.divIcon({
      className: "", html: html,
      iconSize: [w, size + 4], iconAnchor: [w / 2, (size + 4) / 2],
      popupAnchor: [0, -(size + 4) / 2],
    });
  }

  function buildMap(el) {
    var idx = parseInt(el.closest(".city-card").getAttribute("data-idx"), 10);
    var city = CITIES[idx];
    if (!city) { el.style.display = "none"; return; }
    var pts = (city.clubs || []).filter(function (c) { return c.lat != null && c.lng != null; });
    if (!pts.length) { el.style.display = "none"; return; }

    var map = L.map(el, { scrollWheelZoom: false });
    var voyager = L.tileLayer("https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}{r}.png",
      { maxZoom: 19, attribution: "&copy; OpenStreetMap &copy; CARTO" });
    var satellite = L.tileLayer(
      "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
      { maxZoom: 19, attribution: "Tiles &copy; Esri" });
    var dark = L.tileLayer("https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png",
      { maxZoom: 19, attribution: "&copy; OpenStreetMap &copy; CARTO" });
    voyager.addTo(map);   // lighter, more readable default
    L.control.layers(
      { "Map": voyager, "Satellite": satellite, "Dark": dark },
      null, { position: "topright", collapsed: true }
    ).addTo(map);
    // Group clubs that share a ground (identical rounded coordinates).
    var groups = {};
    pts.forEach(function (c) {
      var key = c.lat.toFixed(4) + "," + c.lng.toFixed(4);
      (groups[key] = groups[key] || []).push(c);
    });
    var bounds = [];
    Object.keys(groups).forEach(function (key) {
      var clubs = groups[key];
      var ll = [clubs[0].lat, clubs[0].lng]; bounds.push(ll);
      var popup = clubs.map(function (c) {
        return '<a href="/team/' + c.slug + '/">' + c.name + '</a>'
          + (c.tier_label ? ' <span class="text-muted">(' + c.tier_label + ')</span>' : '');
      }).join("<br>");
      L.marker(ll, { icon: groupedIcon(clubs) }).addTo(map).bindPopup(popup);
    });
    if (bounds.length === 1) map.setView(bounds[0], 12);
    else map.fitBounds(bounds, { padding: [30, 30], maxZoom: 13 });
    map.attributionControl.setPrefix(false);
  }

  var maps = document.querySelectorAll(".city-map");
  if ("IntersectionObserver" in window) {
    var io = new IntersectionObserver(function (entries, obs) {
      entries.forEach(function (en) {
        if (en.isIntersecting) { buildMap(en.target); obs.unobserve(en.target); }
      });
    }, { rootMargin: "200px" });
    maps.forEach(function (m) { io.observe(m); });
  } else {
    maps.forEach(buildMap);
  }
})();
