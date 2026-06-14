// Initial placeholder bounds — covers all planned football countries (Portugal → Turkey,
// southern Spain → Scotland). Replaced immediately once the API data arrives.
const EUROPE_FOOTBALL_BOUNDS = [[34, -12], [60, 40]];

const map = L.map('map', {
    zoomControl: false
}).fitBounds(EUROPE_FOOTBALL_BOUNDS, { padding: [10, 10] });

L.tileLayer(
    'https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png',
    {
        attribution: '&copy; OpenStreetMap & CARTO'
    }
).addTo(map);

L.control.zoom({
    position: 'bottomright'
}).addTo(map);

const clusterGroup = L.markerClusterGroup({
    maxClusterRadius: 60,
    disableClusteringAtZoom: 6,
    chunkedLoading: true,
});
map.addLayer(clusterGroup);

let markers = [];
let activeMarker = null;
let activePopup = null;
let lastVisibleMarkers = [];   // updated by applyFilters(); used by fitToVisibleMarkers()
let searchTempMarker  = null;  // marker temporarily shown on map after a search for a hidden (lower-tier) stadium

// Bounding box computed from ALL loaded markers after the API responds.
// Replaces EUROPE_FOOTBALL_BOUNDS for every reset/fallback once data is available,
// so adding new countries automatically expands the default view — no code changes needed.
let allMarkersBounds = null;

/**
 * Fit the map to the bounding box of the given markers.
 * Uses the full-dataset bounds (computed after load) as fallback,
 * or the static EUROPE_FOOTBALL_BOUNDS before data has arrived.
 */
function fitToVisibleMarkers(visibleMarkers) {
    if (!visibleMarkers || visibleMarkers.length === 0) {
        const fallback = allMarkersBounds || EUROPE_FOOTBALL_BOUNDS;
        map.fitBounds(fallback, { paddingTopLeft: [30, 110], paddingBottomRight: [30, 30], animate: true });
        return;
    }
    const group = L.featureGroup(visibleMarkers);
    map.fitBounds(group.getBounds(), {
        paddingTopLeft:     [30, 110],
        paddingBottomRight: [30, 40],
        maxZoom: 12,
        animate: true,
    });
}

// Populated from GeoJSON after /api/stadiums/ loads — no hardcoded constants.
// Maps country name → UEFA 5-year coefficient rank (lower = better).
const countryRankMap = {};

// Badge DivIcon sizes (px) per role — use numbers, not strings
const BADGE_SIZE = { active: 32, context2: 24, context3: 20 };

function createBadgeIcon(imageUrl, sizePx) {
    const inner = imageUrl
        ? `<img src="${imageUrl}" alt="">`
        : `<div class="badge-icon-fallback" style="background:#9e9e9e;"></div>`;
    return L.divIcon({
        html: `<div class="badge-icon-wrap badge-sz-${sizePx} badge-active">${inner}</div>`,
        className: "",
        iconSize: [sizePx, sizePx],
        iconAnchor: [sizePx / 2, sizePx / 2],
        popupAnchor: [0, -sizePx / 2],
    });
}

/**
 * Badge icon for stadiums with multiple tenant clubs (WS10).
 *
 *  1 team  → delegates to createBadgeIcon (zero regression risk)
 *  2 teams → split circle: left half = team[0], right half = team[1]
 *  3+ teams → split of top-2 + "+N" mini-counter
 *
 * Teams are sorted by division_level ascending (highest tier first) so
 * the most prominent club always occupies the left half.
 */
function createMultiBadgeIcon(teams, sizePx) {
    if (!teams || teams.length <= 1) {
        return createBadgeIcon(teams?.[0]?.image_url || null, sizePx);
    }

    const sorted = [...teams].sort(
        (a, b) => (a.division_level ?? 99) - (b.division_level ?? 99)
    );
    const [t1, t2] = sorted;

    const half = (t) => t?.image_url
        ? `<img src="${t.image_url}" alt="${t.name || ""}" class="badge-half">`
        : `<div class="badge-half badge-half-fallback"></div>`;

    const extra = teams.length > 2
        ? `<span class="badge-extra-count">+${teams.length - 2}</span>`
        : "";

    return L.divIcon({
        html: `<div class="badge-icon-wrap badge-sz-${sizePx} badge-active badge-split">${half(t1)}${half(t2)}${extra}</div>`,
        className: "",
        iconSize:    [sizePx, sizePx],
        iconAnchor:  [sizePx / 2, sizePx / 2],
        popupAnchor: [0, -sizePx / 2],
    });
}

// Reset active state whenever a popup closes by any means (X button, map click, etc.)
// Without this, clicking the same marker after closing its popup via X would not reopen it.
map.on("popupclose", function () {
    activeMarker = null;
    activePopup = null;
});
let operationalMarkers = [];
let developmentMarkers = [];
let currentLayerMode = "operational";
let legendDiv = null;
const isMobile = window.innerWidth <= 768;



const countryFilter   = document.getElementById("countryFilter");
const leagueFilter    = document.getElementById("leagueFilter");
const gironeFilter    = document.getElementById("gironeFilter");
const ownershipFilter = document.getElementById("ownershipFilter");
const surfaceFilter   = document.getElementById("surfaceFilter");
const typeFilter      = document.getElementById("typeFilter");
const stadiumFilter   = document.getElementById("stadiumFilter");
const stadiumCounter  = document.getElementById("stadiumCounter");
const clearFiltersBtn = document.getElementById("clearFiltersBtn");

const mapModeToggle = document.getElementById("mapModeToggle");
const operationalFilters = document.getElementById("operationalFilters");
const developmentFilters = document.getElementById("developmentFilters");
const operationalLabel = document.getElementById("operationalLabel");
const developmentLabel = document.getElementById("developmentLabel");

function updateSelectHighlights() {
    [ownershipFilter, surfaceFilter, typeFilter, stadiumFilter].forEach(sel => {
        sel.classList.toggle("filter-has-value", sel.value !== "");
    });
}

// Show the clear button only when at least one filter is active
function updateClearButton() {
    const operationalActive =
        countryFilter.value || leagueFilter.value ||
        gironeFilter.value  || ownershipFilter.value ||
        surfaceFilter.value || typeFilter.value || stadiumFilter.value;
    const developmentActive =
        developmentCountryFilter?.value || developmentStatusFilter?.value ||
        developmentYearFilter?.value    || developmentStadiumFilter?.value;
    const active = currentLayerMode === "development" ? developmentActive : operationalActive;
    clearFiltersBtn.style.display = active ? "inline-block" : "none";
    updateSelectHighlights();
}

clearFiltersBtn.addEventListener("click", function () {
    if (currentLayerMode === "development") {
        developmentCountryFilter.value = "";
        developmentStatusFilter.value  = "";
        developmentYearFilter.value    = "";
        developmentStadiumFilter.value = "";
        applyDevelopmentFilters();
        // Refit to full development dataset after clearing filters
        const fallback = allMarkersBounds || EUROPE_FOOTBALL_BOUNDS;
        map.fitBounds(fallback, { padding: [10, 10], animate: true });
    } else {
        countryFilter.value   = "";
        leagueFilter.value    = "";
        gironeFilter.value    = "";
        gironeFilter.style.display = "none";
        ownershipFilter.value = "";
        surfaceFilter.value   = "";
        typeFilter.value      = "";
        stadiumFilter.value   = "";
        populateLeagueFilter("");
        if (flashLayer) { map.removeLayer(flashLayer); flashLayer = null; }
        applyFilters();
        fitToVisibleMarkers(lastVisibleMarkers);
        updatePickerLabel();
        saveFilterState();
    }
    updateClearButton();
});

const developmentCountryFilter = document.getElementById("developmentCountryFilter");
const developmentStatusFilter = document.getElementById("developmentStatusFilter");
const developmentYearFilter = document.getElementById("developmentYearFilter");
const developmentStadiumFilter = document.getElementById("developmentStadiumFilter");

// ── Country-League Picker ─────────────────────────────────────────────────
const clpTrigger = document.getElementById("clpTrigger");
const clpPanel   = document.getElementById("clpPanel");

/** Update the trigger button label to reflect the current filter state. */
function updatePickerLabel() {
    const country    = countryFilter.value;
    const leagueOpt  = leagueFilter.options[leagueFilter.selectedIndex];
    const leagueName = (leagueFilter.value && leagueOpt) ? leagueOpt.textContent : "";

    if (!country) {
        clpTrigger.textContent = "All countries";
    } else if (!leagueName) {
        clpTrigger.textContent = country;
    } else {
        clpTrigger.textContent = `${country} — ${leagueName}`;
    }
}

/** Close the picker panel. */
function closePicker() {
    clpPanel.style.display = "none";
}

/**
 * Build (or rebuild) the picker panel from the current markers data.
 * Called once after the API loads and whenever the panel is opened.
 */
function buildPickerUI() {
    clpPanel.innerHTML = "";

    // Gather country → league map directly from marker data
    const countryLeagues = new Map();
    markers.forEach(marker => {
        marker.leagues.forEach(l => {
            if (!l.country || !l.id) return;
            if (!countryLeagues.has(l.country)) countryLeagues.set(l.country, new Map());
            if (!countryLeagues.get(l.country).has(l.id))
                countryLeagues.get(l.country).set(l.id, l);
        });
    });

    // Sort countries by UEFA rank (same order as the dropdown)
    const countries = [...countryLeagues.keys()].sort(
        (a, b) => (countryRankMap[a] ?? 99) - (countryRankMap[b] ?? 99)
    );

    const activeCountry = countryFilter.value;
    const activeLeague  = leagueFilter.value;

    countries.forEach(country => {
        const leagues = [...countryLeagues.get(country).values()].sort(
            (a, b) => (a.divisionLevel ?? 99) - (b.divisionLevel ?? 99)
        );

        // ── Country row ──────────────────────────────────────────────────
        const countryRow = document.createElement("div");
        countryRow.className = "clp-country-row";
        if (country === activeCountry) countryRow.classList.add("active");

        const nameSpan = document.createElement("span");
        nameSpan.className = "clp-country-name";
        nameSpan.textContent = country;

        const chevron = document.createElement("span");
        chevron.className = "clp-chevron";
        chevron.textContent = "›";

        countryRow.appendChild(nameSpan);
        countryRow.appendChild(chevron);

        // ── Leagues accordion ─────────────────────────────────────────────
        const leaguesDiv = document.createElement("div");
        leaguesDiv.className = "clp-leagues";

        // Pre-open accordion for the active country
        if (country === activeCountry) {
            countryRow.classList.add("open");
            leaguesDiv.classList.add("open");
        }

        leagues.forEach(l => {
            const leagueRow = document.createElement("div");
            leagueRow.className = "clp-league-row";
            if (String(l.id) === activeLeague) leagueRow.classList.add("active");
            leagueRow.textContent = l.name;

            leagueRow.addEventListener("click", function (e) {
                e.stopPropagation();
                // Set hidden selects then fire change so existing map.js logic runs
                countryFilter.value = country;
                populateLeagueFilter(country);
                leagueFilter.value = String(l.id);
                leagueFilter.dispatchEvent(new Event("change"));
                updatePickerLabel();
                closePicker();
            });

            leaguesDiv.appendChild(leagueRow);
        });

        // Clicking the country name applies country filter only
        nameSpan.addEventListener("click", function (e) {
            e.stopPropagation();
            countryFilter.value = country;
            leagueFilter.value  = "";
            countryFilter.dispatchEvent(new Event("change"));
            updatePickerLabel();
            closePicker();
        });

        // Clicking the chevron toggles the accordion (without changing filter)
        chevron.addEventListener("click", function (e) {
            e.stopPropagation();
            const isOpen = leaguesDiv.classList.contains("open");
            // Collapse all other open accordions
            clpPanel.querySelectorAll(".clp-leagues.open").forEach(el => {
                el.classList.remove("open");
                el.previousElementSibling?.classList.remove("open");
            });
            if (!isOpen) {
                leaguesDiv.classList.add("open");
                countryRow.classList.add("open");
            }
        });

        // Desktop hover: auto-expand accordion (hover:hover guard prevents touch-device misfires)
        countryRow.addEventListener("mouseenter", function () {
            if (window.matchMedia("(hover: hover) and (pointer: fine)").matches) {
                clpPanel.querySelectorAll(".clp-leagues.open").forEach(el => {
                    el.classList.remove("open");
                    el.previousElementSibling?.classList.remove("open");
                });
                leaguesDiv.classList.add("open");
                countryRow.classList.add("open");
            }
        });

        // Fallback: tapping the container gap (not nameSpan or chevron) still applies country filter
        countryRow.addEventListener("click", function () {
            countryFilter.value = country;
            leagueFilter.value  = "";
            countryFilter.dispatchEvent(new Event("change"));
            updatePickerLabel();
            closePicker();
        });

        clpPanel.appendChild(countryRow);
        clpPanel.appendChild(leaguesDiv);
    });
}

// Toggle picker open/close
clpTrigger.addEventListener("click", function (e) {
    e.stopPropagation();
    if (clpPanel.style.display !== "none") {
        closePicker();
    } else {
        buildPickerUI();   // rebuild to reflect active state
        clpPanel.style.display = "block";
    }
});

// Click outside closes the picker
document.addEventListener("click", function (e) {
    if (!document.getElementById("countryLeaguePicker").contains(e.target)) {
        closePicker();
    }
});
// ─────────────────────────────────────────────────────────────────────────

const legend = L.control({ position: "bottomleft" });

legend.onAdd = function () {
    legendDiv = L.DomUtil.create("div", "info legend");
    updateLegend("operational");
    return legendDiv;
};


legend.addTo(map);

// Flag colors ordered by division_level (index 0 = top flight).
// Colors follow the national flag top-to-bottom color order.
// Near-black fills (Germany div-1) use dark grey so they're visible on the dark basemap.
const COUNTRY_COLORS = {
    "Italy":       ["#009246", "#ffffff", "#ce2b37"],  // green · white · red
    "Germany":     ["#333333", "#dd0000", "#ffce00"],  // black* · red · gold
    "England":     ["#cf081f", "#ffffff", "#003087"],  // red · white · blue
    "France":      ["#002395", "#ffffff", "#ed2939"],  // blue · white · red
    "Spain":       ["#aa151b", "#f1bf00"],              // red · yellow
    "Netherlands": ["#ae1c28", "#ffffff", "#21468b"],  // red · white · blue
    "Portugal":    ["#006600", "#ff0000"],              // green · red
    "Scotland":    ["#005eb8", "#ffffff"],              // blue · white
    "Turkey":      ["#e30a17", "#ffffff"],              // red · white
    "Belgium":     ["#fdda24", "#000000", "#ef3340"],  // yellow · black · red
};

// Fallback bounding boxes [[south, west], [north, east]] for country zoom.
// ONLY used when no markers exist for a country yet (e.g. the scraper
// hasn't run). Primary zoom is derived dynamically from actual marker
// positions in zoomToCountry() — new countries never need to be added here.
const COUNTRY_BOUNDS = {
    "Albania":                [[39.6, 19.3], [42.7, 21.1]],
    "Andorra":                [[42.4,  1.4], [42.7,  1.8]],
    "Armenia":                [[38.8, 43.4], [41.3, 46.6]],
    "Austria":                [[46.4,  9.5], [49.0, 17.2]],
    "Azerbaijan":             [[38.4, 44.8], [41.9, 50.4]],
    "Belarus":                [[51.3, 23.2], [56.2, 32.8]],
    "Belgium":                [[49.5,  2.5], [51.5,  6.4]],
    "Bosnia and Herzegovina": [[42.6, 15.7], [45.3, 19.6]],
    "Bulgaria":               [[41.2, 22.4], [44.2, 28.6]],
    "Croatia":                [[42.4, 13.5], [46.6, 19.4]],
    "Cyprus":                 [[34.5, 32.3], [35.7, 34.6]],
    "Czech Republic":         [[48.6, 12.1], [51.1, 18.9]],
    "Denmark":                [[54.6,  8.1], [57.8, 15.2]],
    "England":                [[49.9, -5.7], [55.8,  1.8]],
    "Estonia":                [[57.5, 21.8], [59.7, 28.2]],
    "Finland":                [[59.8, 20.0], [70.1, 31.6]],
    "France":                 [[41.3, -5.1], [51.1,  9.6]],
    "Georgia":                [[41.0, 40.0], [43.6, 46.7]],
    "Germany":                [[47.3,  5.9], [55.1, 15.0]],
    "Greece":                 [[34.8, 20.0], [41.8, 26.6]],
    "Hungary":                [[45.7, 16.1], [48.6, 22.9]],
    "Iceland":                [[63.4,-24.5], [66.5,-13.5]],
    "Ireland":                [[51.4, -10.5],[55.4, -6.0]],
    "Italy":                  [[36.6,  6.6], [47.1, 18.5]],
    "Kosovo":                 [[41.9, 20.0], [43.3, 21.8]],
    "Latvia":                 [[55.7, 20.9], [58.1, 28.2]],
    "Liechtenstein":          [[47.0,  9.5], [47.3,  9.7]],
    "Lithuania":              [[53.9, 21.0], [56.4, 26.8]],
    "Luxembourg":             [[49.4,  5.7], [50.2,  6.5]],
    "Malta":                  [[35.8, 14.2], [36.1, 14.6]],
    "Moldova":                [[45.5, 26.6], [48.5, 30.2]],
    "Monaco":                 [[43.7,  7.4], [43.8,  7.5]],
    "Montenegro":             [[41.9, 18.5], [43.6, 20.4]],
    "Netherlands":            [[50.8,  3.4], [53.5,  7.2]],
    "North Macedonia":        [[40.9, 20.5], [42.4, 23.0]],
    "Norway":                 [[57.9,  4.5], [71.2, 31.1]],
    "Poland":                 [[49.0, 14.1], [54.9, 24.1]],
    "Portugal":               [[36.9, -9.5], [42.2, -6.2]],
    "Romania":                [[43.6, 20.3], [48.3, 29.7]],
    "Russia":                 [[41.2, 27.3], [55.8, 60.0]],
    "San Marino":             [[43.9, 12.4], [44.0, 12.5]],
    "Scotland":               [[54.6, -7.6], [60.9, -0.7]],
    "Serbia":                 [[42.2, 19.0], [46.2, 23.0]],
    "Slovakia":               [[47.7, 16.8], [49.6, 22.6]],
    "Slovenia":               [[45.4, 13.4], [46.9, 16.6]],
    "Spain":                  [[36.0, -9.3], [43.8,  4.3]],
    "Sweden":                 [[55.3, 11.1], [69.1, 24.2]],
    "Switzerland":            [[45.8,  5.9], [47.8, 10.5]],
    "Turkey":                 [[36.0, 26.0], [42.1, 44.8]],
    "Ukraine":                [[44.4, 22.1], [52.4, 40.2]],
    "Wales":                  [[51.3, -5.4], [53.5, -2.7]],
};

// Natural Earth country name → our Country.name mapping
const NE_NAME_MAP = {
    "England": "United Kingdom",
    "Scotland": "United Kingdom",
};

function updateLegend(mode) {
    if (!legendDiv) return;

    if (mode === "development") {
        legendDiv.style.display = "";
        legendDiv.innerHTML = `
            <h6 class="legend-title">Status</h6>
            <div class="legend-item">
                <span class="legend-dot status-planning"></span>
                Planning
            </div>
            <div class="legend-item">
                <span class="legend-dot status-approved"></span>
                Approved
            </div>
            <div class="legend-item">
                <span class="legend-dot status-construction"></span>
                Under construction
            </div>
        `;
        return;
    }

    // Operational mode: badges speak for themselves — no legend needed
    legendDiv.style.display = "none";
    legendDiv.innerHTML = "";
}

const SURFACE_LABEL      = { GRASS: "Grass", HYBRID: "Hybrid", ARTIFICIAL: "Artificial" };
const STADIUM_TYPE_LABEL = { OPEN: "Open", CLOSED: "Closed", RETRACTABLE: "Retractable", INDOOR: "Indoor" };

function buildPopupContent(props) {
    const teams = props.teams || [];
    const hasMultiple = teams.length > 1;

    // ── Logo strip — only for multi-tenant stadiums ─────────────────
    const logoStrip = hasMultiple ? `
        <div class="popup-tenant-strip">
            ${teams.map((t, i) => `
                <button class="popup-tenant-logo-btn${i === 0 ? " active" : ""}"
                        data-idx="${i}" title="${t.name}">
                    ${t.image_url
                        ? `<img src="${t.image_url}" alt="${t.name}">`
                        : `<div class="btn-logo-fallback"></div>`}
                </button>
            `).join("")}
        </div>
    ` : "";

    // ── Per-team info panels (all rendered, only active one is shown) ─
    const teamPanels = teams.length > 0
        ? teams.map((t, i) => `
            <div class="popup-tenant-panel${i === 0 ? " active" : ""}" data-idx="${i}">
                ${!hasMultiple && t.image_url
                    ? `<img src="${t.image_url}" alt="${t.name}" class="popup-single-logo">`
                    : ""}
                <strong>${t.name}</strong>${t.is_national ? ' <span style="font-size:0.75em;background:#0d6efd;color:#fff;border-radius:3px;padding:1px 4px">National</span>' : ''}<br>
                <span style="font-size:0.8em">${t.is_national ? "National Team Stadium" : (t.league_name || t.tier_name || "Unknown")}${t.girone ? ` — Girone ${t.girone}` : ""}</span><br>
                ${t.wikipedia_url    ? `<a href="${t.wikipedia_url}" target="_blank" style="font-size:0.8em">Team Wikipedia</a><br>` : ""}
                ${t.transfermarkt_url ? `<a href="${t.transfermarkt_url}" target="_blank" style="font-size:0.8em">Team Transfermarkt</a><br>` : ""}
            </div>
          `).join("")
        : `<em>No team linked</em>`;

    return `
        <div style="min-width:185px; max-width:250px;">
            <strong>${props.name}</strong><br>
            ${props.city}<br>
            <strong>Capacity:</strong> ${props.capacity || "Unknown"}<br>
            ${props.year_of_construction ? `<strong>Opened:</strong> ${props.year_of_construction}<br>` : ""}
            ${props.stadium_type ? `<strong>Type:</strong> ${STADIUM_TYPE_LABEL[props.stadium_type] || props.stadium_type}<br>` : ""}
            ${props.surface      ? `<strong>Surface:</strong> ${SURFACE_LABEL[props.surface] || props.surface}<br>` : ""}
            <strong>Ownership:</strong> ${props.ownership || "Unknown"}<br>
            ${props.owner_raw ? `<small>Owner: ${props.owner_raw}</small><br>` : ""}
            <hr style="margin:6px 0">
            ${logoStrip}
            ${teamPanels}
            <hr style="margin:6px 0">
            <a href="/stadium/${props.slug || props.id}/">View stadium details</a>
            ${props.wikipedia_url    ? `<br><a href="${props.wikipedia_url}" target="_blank">Stadium Wikipedia</a>` : ""}
            ${props.transfermarkt_url ? `<br><a href="${props.transfermarkt_url}" target="_blank">Stadium Transfermarkt</a>` : ""}
        </div>
    `;
}

/**
 * Wire the logo-strip click handlers for multi-tenant popups.
 * Clicking a team logo button toggles .active on buttons and panels
 * without re-rendering the popup (no flicker, no latLng reset needed).
 */
function attachPopupLogoStrip() {
    const strip = document.querySelector(".popup-tenant-strip");
    if (!strip) return;   // single-team popup — nothing to wire

    strip.querySelectorAll(".popup-tenant-logo-btn").forEach(btn => {
        btn.addEventListener("click", function (e) {
            e.preventDefault();
            e.stopPropagation();
            const idx = Number(this.dataset.idx);

            // Highlight the clicked logo button
            strip.querySelectorAll(".popup-tenant-logo-btn").forEach(b => {
                b.classList.toggle("active", b === this);
            });

            // Show only the matching team info panel
            const container = strip.parentNode;
            container.querySelectorAll(".popup-tenant-panel").forEach((p, i) => {
                p.classList.toggle("active", i === idx);
            });
        });
    });
}

function closeActivePopup() {
    if (activePopup) {
        map.closePopup(activePopup);
        activePopup = null;
    }
    closeMobileSheet();
    activeMarker = null;
}

function openMobileSheet(html) {
    const sheet = document.getElementById("mobileSheet");
    if (!sheet) return;
    document.getElementById("mobileSheetContent").innerHTML = html;
    sheet.classList.add("open");
}

function closeMobileSheet() {
    const sheet = document.getElementById("mobileSheet");
    if (!sheet) return;
    sheet.classList.remove("open");
}

function applyFilters(updateStadiumDropdown = true) {
    if (searchTempMarker) { map.removeLayer(searchTempMarker); searchTempMarker = null; }

    const selectedCountry  = countryFilter.value;
    const selectedLeague   = leagueFilter.value;   // league ID string or ""
    const selectedGirone   = gironeFilter.value;
    const selectedOwnership = ownershipFilter.value;
    const selectedSurface   = surfaceFilter.value;
    const selectedType      = typeFilter.value;
    const selectedStadium  = stadiumFilter.value;

    clusterGroup.clearLayers();
    let visibleMarkers = [];

    markers.forEach(marker => {
        const inSelectedCountry = selectedCountry &&
            marker.leagues.some(l => l.country === selectedCountry);
        const inSelectedLeague  = selectedLeague &&
            marker.leagues.some(l => l.id === selectedLeague);
        const isTopTier    = marker.primaryLeague?.divisionLevel === 1;
        const isNational   = marker.isNational;

        const ownershipMatches =
            !selectedOwnership || marker.ownership === selectedOwnership;
        const surfaceMatches =
            !selectedSurface || marker.surface === selectedSurface;
        const typeMatches =
            !selectedType || marker.stadiumType === selectedType;
        const gironeMatches =
            !selectedGirone || marker.gironi.includes(selectedGirone);
        const stadiumMatches =
            !selectedStadium || marker.stadiumId === selectedStadium;

        // Determine visual role
        let role; // "active" | "context-2" | "context-3" | "hidden"

        if (!selectedCountry && !selectedLeague) {
            // Default: show tier-1 clubs + national team stadiums
            role = (isTopTier || isNational) ? "active" : "hidden";
        } else if (selectedLeague) {
            // League selected: show ONLY that league — no context markers from other tiers
            role = inSelectedLeague ? "active" : "hidden";
        } else {
            // Country only: all tiers visible with hierarchy
            if (!inSelectedCountry) {
                role = "hidden";
            } else if (isTopTier || isNational) {
                role = "active";
            } else {
                role = (marker.primaryLeague?.divisionLevel ?? 99) <= 2 ? "context-2" : "context-3";
            }
        }

        // Additional filters override role to hidden
        if (!ownershipMatches || !surfaceMatches || !typeMatches || !gironeMatches || !stadiumMatches) {
            role = "hidden";
        }

        if (role === "hidden") {
            return;
        }

        const cfg = {
            "active":    { opacity: 1.0,  zOffset: 2000, size: BADGE_SIZE.active },
            "context-2": { opacity: 0.65, zOffset: 500,  size: BADGE_SIZE.context2 },
            "context-3": { opacity: 0.45, zOffset: 100,  size: BADGE_SIZE.context3 },
        }[role];

        marker.setOpacity(cfg.opacity);
        marker.setZIndexOffset(cfg.zOffset);
        marker.setIcon(createMultiBadgeIcon(marker.teams, cfg.size));
        clusterGroup.addLayer(marker);
        visibleMarkers.push(marker);
    });

    stadiumCounter.textContent =
        `${visibleMarkers.length} stadium${visibleMarkers.length === 1 ? "" : "s"}`;

    if (updateStadiumDropdown) {
        updateStadiumDropdownOptions(visibleMarkers);
    }

    lastVisibleMarkers = visibleMarkers;
    updateLegend("operational");
    updateClearButton();
    closeActivePopup();
    return visibleMarkers;
}

function updateStadiumDropdownOptions(visibleMarkers) {
    const currentValue = stadiumFilter.value;

    stadiumFilter.innerHTML = `<option value="">All stadiums</option>`;

    visibleMarkers
        .sort((a, b) => a.stadiumName.localeCompare(b.stadiumName))
        .forEach(marker => {
            const option = document.createElement("option");
            option.value = marker.stadiumId;
            option.textContent = marker.stadiumName;
            stadiumFilter.appendChild(option);
        });

    if ([...stadiumFilter.options].some(option => option.value === currentValue)) {
        stadiumFilter.value = currentValue;
    } else {
        stadiumFilter.value = "";
    }
}

function loadDevelopmentStadiums() {
    if (developmentMarkers.length > 0) {
        applyDevelopmentFilters();
        updateLegend("development");
        return;
    }
    fetch(document.getElementById("map").dataset.developmentsUrl)
        .then(res => { if (!res.ok) throw new Error(res.status); return res.json(); })
        .then(data => {
            developmentMarkers.forEach(marker => map.removeLayer(marker));
            developmentMarkers = [];


            data.features.forEach(feature => {
                const coords = feature.geometry.coordinates;
                const props = feature.properties;

                const marker = L.circleMarker([coords[1], coords[0]], {
                    radius: isMobile ? 13 : 7,
                    fillColor: getDevelopmentMarkerColor(props.status),
                    color: "#111111",
                    weight: isMobile ? 3 : 1.5,
                    opacity: 1,
                    fillOpacity: 0.9
                });

                marker.developmentId = String(props.id);
                marker.developmentName = props.name;
                marker.status = props.status || "";
                marker.estimatedOpening = props.estimated_opening
                    ? String(props.estimated_opening)
                    : "";
                marker.country = props.country || "";
                marker.city    = props.city    || "";

                // Store base radius so mouseout can restore it exactly
                const baseRadius = isMobile ? 13 : 7;
                marker._baseRadius = baseRadius;

                // Hover: expand circle and boost opacity for clear affordance
                marker.on("mouseover", function () {
                    this.setRadius(Math.round(this._baseRadius * 1.6));
                    this.setStyle({ weight: isMobile ? 4 : 2.5, fillOpacity: 1 });
                });
                marker.on("mouseout", function () {
                    this.setRadius(this._baseRadius);
                    this.setStyle({ weight: isMobile ? 3 : 1.5, fillOpacity: 0.9 });
                });

                // Tooltip — same dark glass style as badge markers
                marker.bindTooltip(props.name, {
                    permanent: false,
                    direction: "top",
                    className: "badge-tooltip",
                    offset: [0, -(baseRadius + 4)],
                });

            const popupContent = `
                <div class="stadium-popup development-popup">
                    <h4>${props.name}</h4>

                    <div class="popup-row">
                        <strong>Status</strong>
                        <span>${props.status || "Unknown"}</span>
                    </div>

                    <div class="popup-row">
                        <strong>Project type</strong>
                        <span>${props.project_type || "Unknown"}</span>
                    </div>

                    <div class="popup-row">
                        <strong>Future capacity</strong>
                        <span>${props.future_capacity || "Unknown"}</span>
                    </div>

                    <div class="popup-row">
                        <strong>Opening</strong>
                        <span>${props.estimated_opening || "TBD"}</span>
                    </div>

                    ${props.architect ? `
                    <div class="popup-row">
                        <strong>Architect</strong>
                        <span>${props.architect}</span>
                    </div>
                    ` : ""}

                    <a class="popup-btn popup-primary"
                    href="/stadium-development/${props.id}/">
                        View project
                    </a>

                    ${props.source_url ? `
                        <a class="popup-btn"
                        href="${props.source_url}"
                        target="_blank">
                        Source
                        </a>
                    ` : ""}
                </div>
            `;                

                marker.on("click", function (e) {
                    L.DomEvent.stopPropagation(e);
                    if (isMobile) {
                        openMobileSheet(popupContent);
                    } else {
                        L.popup({ maxWidth: 260, minWidth: 220, autoPan: true, autoPanPadding: [20, 20] })
                            .setLatLng(marker.getLatLng())
                            .setContent(popupContent)
                            .openOn(map);
                    }
                });

                marker.addTo(map);
                developmentMarkers.push(marker);
            });

            updateDevelopmentDropdownOptions();
            applyDevelopmentFilters();
        })
        .catch(err => {
            console.error("Failed to load development stadiums:", err);
            stadiumCounter.textContent = "⚠ Load failed";
        });
}
function getDevelopmentMarkerColor(status) {
    if (status === "Planning") return "#ffc107";
    if (status === "Approved") return "#ff9800";
    if (status === "Under Construction") return "#ff1744";
    return "#00e5ff";
}

function updateDevelopmentDropdownOptions() {
    const countries = [...new Set(developmentMarkers.map(m => m.country).filter(Boolean))].sort();
    const statuses = [...new Set(developmentMarkers.map(m => m.status).filter(Boolean))].sort();
    const years = [...new Set(developmentMarkers.map(m => m.estimatedOpening).filter(Boolean))].sort();

    developmentCountryFilter.innerHTML = `<option value="">All countries</option>`;
    countries.forEach(c => {
        const opt = document.createElement("option");
        opt.value = opt.textContent = c;
        developmentCountryFilter.appendChild(opt);
    });

    developmentStatusFilter.innerHTML = `<option value="">All statuses</option>`;
    statuses.forEach(status => {
        const option = document.createElement("option");
        option.value = status;
        option.textContent = status;
        developmentStatusFilter.appendChild(option);
    });

    developmentYearFilter.innerHTML = `<option value="">All opening years</option>`;
    years.forEach(year => {
        const option = document.createElement("option");
        option.value = year;
        option.textContent = year;
        developmentYearFilter.appendChild(option);
    });

    developmentStadiumFilter.innerHTML = `<option value="">All projects</option>`;
    developmentMarkers
        .sort((a, b) => a.developmentName.localeCompare(b.developmentName))
        .forEach(marker => {
            const option = document.createElement("option");
            option.value = marker.developmentId;
            option.textContent = marker.developmentName;
            developmentStadiumFilter.appendChild(option);
        });
}
function applyDevelopmentFilters() {
    const selectedCountry = developmentCountryFilter.value;
    const selectedStatus = developmentStatusFilter.value;
    const selectedYear = developmentYearFilter.value;
    const selectedProject = developmentStadiumFilter.value;

    let visibleMarkers = [];

    developmentMarkers.forEach(marker => {
        const countryMatches = !selectedCountry || marker.country === selectedCountry;
        const statusMatches = !selectedStatus || marker.status === selectedStatus;
        const yearMatches = !selectedYear || marker.estimatedOpening === selectedYear;
        const projectMatches = !selectedProject || marker.developmentId === selectedProject;

        if (countryMatches && statusMatches && yearMatches && projectMatches) {
            marker.addTo(map);
            visibleMarkers.push(marker);
        } else {
            map.removeLayer(marker);
        }
    });

    stadiumCounter.textContent = `${visibleMarkers.length} project${visibleMarkers.length === 1 ? "" : "s"}`;
    updateClearButton();
}

function populateCountryFilter() {
    const countries = [...new Set(
        markers.flatMap(m => m.leagues.map(l => l.country)).filter(Boolean)
    )].sort((a, b) => (countryRankMap[a] ?? 99) - (countryRankMap[b] ?? 99));
    countryFilter.innerHTML = `<option value="">All countries</option>`;
    countries.forEach(c => {
        const opt = document.createElement("option");
        opt.value = c;
        opt.textContent = c;
        countryFilter.appendChild(opt);
    });
    // Build the visual picker now that the country list is ready
    buildPickerUI();
}

function populateLeagueFilter(country) {
    const seen = new Map();
    markers.forEach(m => {
        m.leagues.forEach(l => {
            if (!l.id) return;
            if (country && l.country !== country) return;
            if (!seen.has(l.id)) seen.set(l.id, l);
        });
    });
    const leagues = [...seen.values()].sort((a, b) => {
        const cr = (countryRankMap[a.country] ?? 99) - (countryRankMap[b.country] ?? 99);
        return cr !== 0 ? cr : (a.divisionLevel ?? 99) - (b.divisionLevel ?? 99);
    });
    leagueFilter.innerHTML = `<option value="">All leagues</option>`;
    leagues.forEach(l => {
        const opt = document.createElement("option");
        opt.value = l.id;
        opt.textContent = l.name;
        opt.dataset.divisionLevel = l.divisionLevel ?? "";
        opt.dataset.country = l.country;
        leagueFilter.appendChild(opt);
    });
    leagueFilter.value = "";
    gironeFilter.style.display = "none";
    gironeFilter.value = "";
}

// --------------------------------------------------
// Country zoom + flash (Feature C)
// --------------------------------------------------

let countryGeoJSON = null;
let flashLayer = null;

async function loadCountryGeoJSON() {
    if (countryGeoJSON) return countryGeoJSON;
    const url = document.getElementById("map").dataset.countriesUrl;
    if (!url) return null;
    try {
        const res = await fetch(url);
        countryGeoJSON = await res.json();
    } catch (e) {
        console.warn("Could not load country boundaries:", e);
    }
    return countryGeoJSON;
}

async function zoomToCountry(countryName) {
    // 1. Zoom to the visible markers that applyFilters() just computed.
    //    applyFilters() always runs immediately before zoomToCountry() in
    //    every change handler, so lastVisibleMarkers already contains exactly
    //    the right set (the selected country's or league's stadiums).
    //    This works for every country/league automatically — no hardcoded list needed.
    if (lastVisibleMarkers.length > 0) {
        fitToVisibleMarkers(lastVisibleMarkers);
    } else {
        // Fallback: hardcoded box for countries whose scraper hasn't run yet
        const bounds = COUNTRY_BOUNDS[countryName];
        if (bounds) map.fitBounds(bounds, { paddingTopLeft: [30, 110], paddingBottomRight: [30, 40], animate: true });
    }

    // 2. Flash the border polygon
    const geojson = await loadCountryGeoJSON();
    if (!geojson) return;

    const neName = NE_NAME_MAP[countryName] || countryName;
    const feature = geojson.features.find(f => f.properties.name === neName);
    if (!feature) return;

    if (flashLayer) { map.removeLayer(flashLayer); flashLayer = null; }

    flashLayer = L.geoJSON(feature, {
        style: {
            color: "#ffffff",
            weight: 2.5,
            opacity: 0.9,
            fillColor: "#ffffff",
            fillOpacity: 0.12,
            dashArray: "6 4",
        }
    }).addTo(map);

    setTimeout(() => {
        if (flashLayer) { map.removeLayer(flashLayer); flashLayer = null; }
    }, 1800);
}

/**
 * Restore the map view to the most specific active context:
 *   - Country selected → zoom to that country
 *   - Nothing selected → reset to full default view
 * Called when a more-specific filter (league or stadium) is cleared.
 */
function resetZoomToContext() {
    const country = countryFilter.value;
    if (country) {
        zoomToCountry(country);
    } else {
        if (flashLayer) { map.removeLayer(flashLayer); flashLayer = null; }
        fitToVisibleMarkers(lastVisibleMarkers);
    }
}

// ── Filter state persistence (survives navigation to detail pages) ──────────

const FILTER_KEY = "stadiaMapFilters";

function saveFilterState() {
    sessionStorage.setItem(FILTER_KEY, JSON.stringify({
        country:   countryFilter.value,
        league:    leagueFilter.value,
        girone:    gironeFilter.value,
        ownership: ownershipFilter.value,
        surface:   surfaceFilter.value,
        type:      typeFilter.value,
        stadium:   stadiumFilter.value,
    }));
}

function restoreFilterState() {
    const raw = sessionStorage.getItem(FILTER_KEY);
    if (!raw) return;
    let state;
    try { state = JSON.parse(raw); } catch (e) { return; }

    // Restore dropdowns in dependency order
    if (state.country) {
        countryFilter.value = state.country;
        populateLeagueFilter(state.country);   // rebuild league options for this country
    }
    if (state.league) leagueFilter.value = state.league;

    if (state.girone) {
        gironeFilter.value = state.girone;
        gironeFilter.style.display = "inline-block";
    }
    if (state.ownership) ownershipFilter.value = state.ownership;
    if (state.surface)   surfaceFilter.value   = state.surface;
    if (state.type)      typeFilter.value      = state.type;

    // Re-run filters — this also repopulates the stadium dropdown
    applyFilters();

    // Restore stadium selection after dropdown is populated
    if (state.stadium) {
        stadiumFilter.value = state.stadium;
        applyFilters(false);
        const target = markers.find(m => m.stadiumId === state.stadium);
        if (target) map.setView(target.getLatLng(), 13);   // instant, no animation on restore
    } else if (state.country) {
        zoomToCountry(state.country);
    } else {
        fitToVisibleMarkers(lastVisibleMarkers);
    }
    updatePickerLabel();
    return true;   // signals to caller that saved state was processed
}

// Detect if we were redirected here from a development detail page so we can
// auto-activate dev mode after the initial fetch completes (avoids a flash of
// operational markers before the switch fires).
const autoDevMode = new URLSearchParams(window.location.search).get("mode") === "development";

// Show a loading hint while the API responds (clears once data is rendered)
stadiumCounter.textContent = "Loading…";

fetch(document.getElementById("map").dataset.stadiumsUrl)
    .then(res => { if (!res.ok) throw new Error(res.status); return res.json(); })
    .then(data => {

        // Build country→rank map from GeoJSON (no hardcoded constants needed)
        data.features.forEach(f => {
            f.properties.teams.forEach(t => {
                if (t.country && t.country_rank != null)
                    countryRankMap[t.country] = t.country_rank;
            });
        });

        data.features.forEach(feature => {
            const coords = feature.geometry.coordinates;
            const props = feature.properties;

            // Determine primary team (lowest divisionLevel) for badge selection
            const primaryTeam = (props.teams || []).reduce((best, t) => {
                const lvl = t.division_level ?? 99;
                return (!best || lvl < (best.division_level ?? 99)) ? t : best;
            }, null);

            const marker = L.marker([coords[1], coords[0]], {
                icon: createMultiBadgeIcon(props.teams || [], BADGE_SIZE.active),
                zIndexOffset: 1000,
            });
            marker.primaryTeam = primaryTeam;

            marker.teams = props.teams || [];

            marker.leagues = marker.teams.map(t => ({
                id:            String(t.league_id ?? ""),
                name:          t.league_name  || "",
                divisionLevel: t.division_level != null ? Number(t.division_level) : null,
                country:       t.country || props.country || "",
            }));

            const sortedLeagues = [...marker.leagues].sort(
                (a, b) => (a.divisionLevel ?? 99) - (b.divisionLevel ?? 99)
            );
            marker.primaryLeague = sortedLeagues[0] || null;
            marker.country = marker.primaryLeague
                ? marker.primaryLeague.country
                : (props.country || "");

            marker.gironi = marker.teams.map(t => t.girone || "");
            marker.isNational = marker.teams.some(t => t.is_national);

            marker.ownership    = props.ownership ? String(props.ownership) : "UNKNOWN";
            marker.surface      = props.surface || "";
            marker.stadiumType  = props.stadium_type || "";
            marker.stadiumId = String(props.id);
            marker.stadiumName = props.name;

            // Hover tooltip — team name(s), styled for dark map
            const tooltipLabel = marker.teams.length > 1
                ? marker.teams.map(t => t.name).join(" · ")
                : (marker.primaryTeam?.name || marker.stadiumName);
            marker.bindTooltip(tooltipLabel, {
                permanent: false,
                direction: "top",
                className: "badge-tooltip",
                offset: [0, -18],
            });

            marker.on("click", function () {
                const alreadyOpen = activeMarker === marker;
                closeActivePopup();
                if (alreadyOpen) return;

                if (isMobile) {
                    openMobileSheet(buildPopupContent(props));
                    activeMarker = marker;
                    setTimeout(() => { attachPopupLogoStrip(); }, 0);
                } else {
                    activePopup = L.popup({ maxWidth: 270, maxHeight: 360 })
                        .setLatLng([coords[1], coords[0]])
                        .setContent(buildPopupContent(props))
                        .openOn(map);
                    activeMarker = marker;
                    setTimeout(() => { attachPopupLogoStrip(); }, 0);
                }
            });

            clusterGroup.addLayer(marker);
            markers.push(marker);
            operationalMarkers.push(marker);
        });

        // Derive the default view from the actual data — auto-expands as new countries are scraped
        if (markers.length > 0) {
            allMarkersBounds = L.featureGroup(markers).getBounds().pad(0.05);
        }

        populateCountryFilter();
        populateLeagueFilter("");
        wireSearch();

        if (autoDevMode) {
            // Coming back from a development detail page — skip operational view entirely,
            // activate dev mode, and clean the URL so a refresh shows the normal map.
            mapModeToggle.checked = true;
            mapModeToggle.dispatchEvent(new Event("change"));
            history.replaceState(null, "", window.location.pathname);
        } else {
            // Restore saved filters (returns true) or run defaults and fit to data bounds
            if (!restoreFilterState()) {
                const visible = applyFilters();
                fitToVisibleMarkers(visible);
            }
        }
    })
    .catch(err => {
        console.error("Failed to load stadiums:", err);
        stadiumCounter.textContent = "⚠ Load failed";
    });

countryFilter.addEventListener("change", function () {
    const country = this.value;
    stadiumFilter.value = "";
    populateLeagueFilter(country);
    applyFilters();
    if (country) {
        zoomToCountry(country);
    } else {
        if (flashLayer) { map.removeLayer(flashLayer); flashLayer = null; }
        fitToVisibleMarkers(lastVisibleMarkers);
    }
    updatePickerLabel();
    saveFilterState();
});

leagueFilter.addEventListener("change", function () {
    const selected = leagueFilter.options[leagueFilter.selectedIndex];
    const divLevel = selected?.value ? Number(selected.dataset.divisionLevel) : null;
    const country  = selected?.value ? selected.dataset.country : "";

    if (divLevel === 3 && country === "Italy") {
        gironeFilter.style.display = "inline-block";
    } else {
        gironeFilter.style.display = "none";
        gironeFilter.value = "";
    }
    stadiumFilter.value = "";
    applyFilters();

    if (country) {
        zoomToCountry(country);
    } else {
        resetZoomToContext();
    }
    updatePickerLabel();
    saveFilterState();
});

gironeFilter.addEventListener("change", function () {
    stadiumFilter.value = "";
    applyFilters();
    saveFilterState();
});

ownershipFilter.addEventListener("change", function () {
    stadiumFilter.value = "";
    applyFilters();
    saveFilterState();
});

surfaceFilter.addEventListener("change", function () {
    stadiumFilter.value = "";
    applyFilters();
    saveFilterState();
});

typeFilter.addEventListener("change", function () {
    stadiumFilter.value = "";
    applyFilters();
    saveFilterState();
});

stadiumFilter.addEventListener("change", function () {
    const selectedId = this.value;
    applyFilters(false);

    if (selectedId) {
        const target = markers.find(m => m.stadiumId === selectedId);
        if (target) {
            const latlng = target.getLatLng();
            map.flyTo(latlng, Math.max(map.getZoom(), 13), { duration: 0.9 });
        }
    } else {
        resetZoomToContext();
    }
    saveFilterState();
});

mapModeToggle.addEventListener("change", function () {
    if (this.checked) {
        currentLayerMode = "development";
        map.removeLayer(clusterGroup);
        closeActivePopup();

        operationalFilters.classList.add("d-none");
        operationalFilters.classList.remove("d-flex");

        developmentFilters.classList.remove("d-none");
        developmentFilters.classList.add("d-flex");

        stadiumCounter.textContent = "Loading…";
        loadDevelopmentStadiums();
        updateLegend("development");

        operationalLabel.classList.remove("active");
        developmentLabel.classList.add("active");

    } else {
        currentLayerMode = "operational";
        developmentMarkers.forEach(marker => map.removeLayer(marker));

        developmentFilters.classList.add("d-none");
        developmentFilters.classList.remove("d-flex");

        operationalFilters.classList.remove("d-none");
        operationalFilters.classList.add("d-flex");

        map.addLayer(clusterGroup);
        applyFilters();
        updateLegend("operational");
        updateClearButton();

        developmentLabel.classList.remove("active");
        operationalLabel.classList.add("active");
    }
});
developmentCountryFilter.addEventListener("change", function () {
    developmentStadiumFilter.value = "";
    applyDevelopmentFilters();
});

developmentStatusFilter.addEventListener("change", function () {
    developmentStadiumFilter.value = "";
    applyDevelopmentFilters();
});

developmentYearFilter.addEventListener("change", function () {
    developmentStadiumFilter.value = "";
    applyDevelopmentFilters();
});

developmentStadiumFilter.addEventListener("change", function () {
    const selectedId = this.value;
    applyDevelopmentFilters();

    if (selectedId) {
        const target = developmentMarkers.find(m => m.developmentId === selectedId);
        if (target) {
            map.flyTo(target.getLatLng(), Math.max(map.getZoom(), 13), { duration: 0.9 });
        }
    } else {
        // Reset to default view — development mode has no country filter
        const fallback = allMarkersBounds || EUROPE_FOOTBALL_BOUNDS;
        map.fitBounds(fallback, { paddingTopLeft: [30, 110], paddingBottomRight: [30, 30], animate: true });
    }
});

// ── Live search (WS2) ────────────────────────────────────────────────────
function wireSearch() {
    const input   = document.getElementById("liveSearch");
    const results = document.getElementById("searchResults");
    if (!input) return;
    let debounce;

    input.addEventListener("input", function () {
        clearTimeout(debounce);
        debounce = setTimeout(function () {
            const q = input.value.trim().toLowerCase();
            results.innerHTML = "";
            if (q.length < 2) { results.style.display = "none"; return; }

            let hits;
            if (currentLayerMode === "development") {
                hits = developmentMarkers.filter(function (m) {
                    return m.developmentName?.toLowerCase().includes(q);
                }).slice(0, 5);
            } else {
                hits = operationalMarkers.filter(function (m) {
                    if (m.stadiumName?.toLowerCase().includes(q)) return true;
                    return (m.teams || []).some(t => t.name?.toLowerCase().includes(q));
                }).slice(0, 5);
            }

            if (!hits.length) { results.style.display = "none"; return; }

            hits.forEach(function (m) {
                // Bug 1 fix: prefer the team that actually matches the query over primaryTeam,
                // so typing "Inter" shows "Inter Milan — Giuseppe Meazza" not "AC Milan — …"
                const label = currentLayerMode === "development"
                    ? m.developmentName
                    : (function () {
                        const matchingTeam = (m.teams || []).find(
                            function (t) { return t.name?.toLowerCase().includes(q); }
                        );
                        const display = matchingTeam || m.primaryTeam;
                        return display?.name
                            ? display.name + " — " + m.stadiumName
                            : m.stadiumName;
                    }());
                const li = document.createElement("li");
                li.textContent = label;
                li.addEventListener("click", function () {
                    // Bug 2 fix: if marker is filtered out (lower-tier in default view),
                    // add it directly to the map so the pin is visible alongside the popup.
                    if (currentLayerMode !== "development" && !clusterGroup.hasLayer(m)) {
                        if (searchTempMarker && searchTempMarker !== m) {
                            map.removeLayer(searchTempMarker);
                        }
                        m.setOpacity(1.0);
                        m.setZIndexOffset(2000);
                        m.setIcon(createMultiBadgeIcon(m.teams, BADGE_SIZE.active));
                        m.addTo(map);
                        searchTempMarker = m;
                    }
                    map.flyTo(m.getLatLng(), 12, { duration: 1.2 });
                    setTimeout(function () { m.fire("click"); }, 1300);
                    input.value = "";
                    results.style.display = "none";
                });
                results.appendChild(li);
            });
            results.style.display = "block";
        }, 250);
    });

    document.addEventListener("click", function (e) {
        if (!e.target.closest("#searchWrap")) results.style.display = "none";
    });
}

// ── Mobile sheet wiring ───────────────────────────────────────────────────
const mobileSheetClose = document.getElementById("mobileSheetClose");
if (mobileSheetClose) {
    mobileSheetClose.addEventListener("click", function () {
        closeMobileSheet();
        activeMarker = null;
    });
}

// Tapping the map background dismisses the sheet
map.on("click", function () {
    if (isMobile) {
        closeMobileSheet();
        activeMarker = null;
    }
});