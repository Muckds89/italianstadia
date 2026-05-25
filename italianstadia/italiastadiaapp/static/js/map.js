const map = L.map('map', {
    zoomControl: false
}).setView([42.5, 12.5], 5);

L.tileLayer(
    'https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png',
    {
        attribution: '&copy; OpenStreetMap & CARTO'
    }
).addTo(map);

L.control.zoom({
    position: 'bottomright'
}).addTo(map);

let markers = [];
let activeMarker = null;
let activePopup = null;
let operationalMarkers = [];
let developmentMarkers = [];
let currentLayerMode = "operational";
let legendDiv = null;



const countryFilter  = document.getElementById("countryFilter");
const leagueFilter   = document.getElementById("leagueFilter");
const gironeFilter   = document.getElementById("gironeFilter");
const ownershipFilter = document.getElementById("ownershipFilter");
const stadiumFilter  = document.getElementById("stadiumFilter");
const stadiumCounter = document.getElementById("stadiumCounter");

const mapModeToggle = document.getElementById("mapModeToggle");
const operationalFilters = document.getElementById("operationalFilters");
const developmentFilters = document.getElementById("developmentFilters");

const developmentStatusFilter = document.getElementById("developmentStatusFilter");
const developmentYearFilter = document.getElementById("developmentYearFilter");
const developmentStadiumFilter = document.getElementById("developmentStadiumFilter");

const legend = L.control({ position: "bottomleft" });

legend.onAdd = function () {
    legendDiv = L.DomUtil.create("div", "info legend");
    updateLegend("operational");
    return legendDiv;
};


legend.addTo(map);

const LEVEL_COLORS = { 1: "#00c853", 2: "#ffffff", 3: "#ff1744" };

function updateLegend(mode) {
    if (!legendDiv) return;

    if (mode === "development") {
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

    // operational: build from loaded marker data for the current country selection
    const country = countryFilter ? countryFilter.value : "";
    const seen = new Map();
    markers.forEach(m => {
        m.leagues.forEach(l => {
            if (!l.id || seen.has(l.id)) return;
            if (country && l.country !== country) return;
            seen.set(l.id, l);
        });
    });

    const leagues = [...seen.values()].sort(
        (a, b) => (a.divisionLevel ?? 99) - (b.divisionLevel ?? 99)
    );

    const items = leagues.map(l => {
        const color = LEVEL_COLORS[l.divisionLevel] || "#9e9e9e";
        return `<div class="legend-item">
                    <span class="legend-dot" style="background:${color};border:1px solid #555"></span>
                    ${l.name}
                </div>`;
    }).join("");

    legendDiv.innerHTML = `<h6 class="legend-title">Leagues</h6>${items || "<em style='font-size:11px;color:#aaa'>No leagues</em>"}`;
}
// console.log("Legend added ", document.querySelector(".legend"));

function buildPopupContent(props, teamIndex = 0) {
    const teams = props.teams || [];
    const team = teams[teamIndex];
    const hasMultipleTeams = teams.length > 1;

    return `
        <div style="min-width:180px; max-width:240px;">
            <strong>${props.name}</strong><br>
            ${props.city}<br>
            <strong>Capacity:</strong> ${props.capacity || "Unknown"}<br>
            <strong>Ownership:</strong> ${props.ownership || "Unknown"}<br>
            ${props.owner_raw ? `<small>Owner: ${props.owner_raw}</small><br>` : ""}
            <hr>

            ${
                team
                ? `
                    <strong>Team:</strong> ${team.name}<br>
                    <strong>League:</strong> ${team.league_name || team.tier_name || "Unknown"}${team.girone ? ` - Girone ${team.girone}` : ""}<br>
                    ${team.wikipedia_url ? `<a href="${team.wikipedia_url}" target="_blank">Team Wikipedia</a><br>` : ""}
                    ${team.transfermarkt_url ? `<a href="${team.transfermarkt_url}" target="_blank">Team Transfermarkt</a><br>` : ""}
                `
                : `<em>No team linked</em><br>`
            }

            <br>
            ${hasMultipleTeams ? `
                <button class="popup-team-prev" data-index="${teamIndex}">←</button>
                <span>${teamIndex + 1} / ${teams.length}</span>
                <button class="popup-team-next" data-index="${teamIndex}">→</button>
                <br><br>
            ` : ""}

            <a href="/stadium/${props.id}/">View stadium details</a>
            ${props.wikipedia_url ? `<br><a href="${props.wikipedia_url}" target="_blank">Stadium Wikipedia</a>` : ""}
            ${props.transfermarkt_url ? `<br><a href="${props.transfermarkt_url}" target="_blank">Stadium Transfermarkt</a>` : ""}
        </div>
    `;
}

function attachPopupTeamNavigation(props, coords) {
    const prevButton = document.querySelector(".popup-team-prev");
    const nextButton = document.querySelector(".popup-team-next");

    if (!prevButton && !nextButton) {
        return;
    }

    const teams = props.teams || [];

    function updatePopup(newIndex) {
        activePopup.setContent(buildPopupContent(props, newIndex));
        activePopup.setLatLng([coords[1], coords[0]]);

        setTimeout(() => {
            attachPopupTeamNavigation(props, coords);
        }, 0);
    }

    if (prevButton) {
        prevButton.addEventListener("click", function (e) {
            e.preventDefault();
            e.stopPropagation();

            const currentIndex = Number(this.dataset.index);
            const newIndex = (currentIndex - 1 + teams.length) % teams.length;
            updatePopup(newIndex);
        });
    }

    if (nextButton) {
        nextButton.addEventListener("click", function (e) {
            e.preventDefault();
            e.stopPropagation();

            const currentIndex = Number(this.dataset.index);
            const newIndex = (currentIndex + 1) % teams.length;
            updatePopup(newIndex);
        });
    }
}

function closeActivePopup() {
    if (activePopup) {
        map.closePopup(activePopup);
        activeMarker = null;
        activePopup = null;
    }
}

function applyFilters(updateStadiumDropdown = true) {
    const selectedCountry  = countryFilter.value;
    const selectedLeague   = leagueFilter.value;   // league ID string or ""
    const selectedGirone   = gironeFilter.value;
    const selectedOwnership = ownershipFilter.value;
    const selectedStadium  = stadiumFilter.value;

    let visibleMarkers = [];

    markers.forEach(marker => {
        const countryMatches =
            !selectedCountry ||
            marker.leagues.some(l => l.country === selectedCountry);

        const leagueMatches =
            !selectedLeague ||
            marker.leagues.some(l => l.id === selectedLeague);

        const gironeMatches =
            !selectedGirone ||
            marker.gironi.includes(selectedGirone);

        const ownershipMatches =
            !selectedOwnership || marker.ownership === selectedOwnership;

        const stadiumMatches =
            !selectedStadium || marker.stadiumId === selectedStadium;

        if (countryMatches && leagueMatches && gironeMatches &&
                ownershipMatches && stadiumMatches) {
            marker.addTo(map);
            visibleMarkers.push(marker);
        } else {
            map.removeLayer(marker);
        }
    });

    stadiumCounter.textContent =
        `${visibleMarkers.length} stadium${visibleMarkers.length === 1 ? "" : "s"}`;

    if (updateStadiumDropdown) {
        updateStadiumDropdownOptions(visibleMarkers);
    }

    closeActivePopup();
}

function getMarkerColor(marker) {
    const primary = marker.primaryLeague;
    const level = primary ? primary.divisionLevel : null;
    const isItaly = primary ? primary.country === "Italy" : false;

    if (level === 1) return "#00c853";  // green  — top flight

    if (level === 2) return "#ffffff";  // white  — second tier

    if (level === 3) {
        if (isItaly) {
            const girone = (marker.gironi || [])[0];
            if (girone === "A") return "#ff8a80";
            if (girone === "B") return "#ff5252";
            if (girone === "C") return "#d50000";
        }
        return "#ff1744";              // generic third-tier red
    }

    return "#9e9e9e";                  // grey — unknown / unassigned
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
    fetch("/api/stadium-developments/")
        .then(res => res.json())
        .then(data => {
            developmentMarkers.forEach(marker => map.removeLayer(marker));
            developmentMarkers = [];

            data.features.forEach(feature => {
                const coords = feature.geometry.coordinates;
                const props = feature.properties;

                const isMobile = window.innerWidth <= 768;

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

                marker.bindPopup(popupContent, {
                    maxWidth: isMobile ? 340 : 260,
                    minWidth: isMobile ? 300 : 220,
                    autoPan: true,
                    autoPanPadding: isMobile ? [30, 120] : [20, 20],
                    closeButton: true
                });

                marker.addTo(map);
                developmentMarkers.push(marker);
            });

            updateDevelopmentDropdownOptions();
            applyDevelopmentFilters();
        });
}
function getDevelopmentMarkerColor(status) {
    if (status === "Planning") return "#ffc107";
    if (status === "Approved") return "#ff9800";
    if (status === "Under Construction") return "#ff1744";
    return "#00e5ff";
}

function updateDevelopmentDropdownOptions() {
    const statuses = [...new Set(developmentMarkers.map(m => m.status).filter(Boolean))].sort();
    const years = [...new Set(developmentMarkers.map(m => m.estimatedOpening).filter(Boolean))].sort();

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
    const selectedStatus = developmentStatusFilter.value;
    const selectedYear = developmentYearFilter.value;
    const selectedProject = developmentStadiumFilter.value;

    let visibleMarkers = [];

    developmentMarkers.forEach(marker => {
        const statusMatches = !selectedStatus || marker.status === selectedStatus;
        const yearMatches = !selectedYear || marker.estimatedOpening === selectedYear;
        const projectMatches = !selectedProject || marker.developmentId === selectedProject;

        if (statusMatches && yearMatches && projectMatches) {
            marker.addTo(map);
            visibleMarkers.push(marker);
        } else {
            map.removeLayer(marker);
        }
    });

    stadiumCounter.textContent = `${visibleMarkers.length} project${visibleMarkers.length === 1 ? "" : "s"}`;
}
// console.log(data.features.length);

// console.log(
// data.features.map(f => ({
//     name: f.properties.name,
//     coords: f.geometry.coordinates,
//     tier: f.properties.teams?.map(t => t.tier)
// }))
// );

function populateCountryFilter() {
    const countries = [...new Set(
        markers.flatMap(m => m.leagues.map(l => l.country)).filter(Boolean)
    )].sort();
    countryFilter.innerHTML = `<option value="">All countries</option>`;
    countries.forEach(c => {
        const opt = document.createElement("option");
        opt.value = c;
        opt.textContent = c;
        countryFilter.appendChild(opt);
    });
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
    const leagues = [...seen.values()].sort(
        (a, b) => (a.divisionLevel ?? 99) - (b.divisionLevel ?? 99)
    );
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

fetch("/api/stadiums/")
  
    .then(res => res.json())
    .then(data => {

        data.features.forEach(feature => {
            const coords = feature.geometry.coordinates;
            const props = feature.properties;



            const marker = L.circleMarker([coords[1], coords[0]], {
                radius: 7,
                fillColor: "#00e5ff",
                color: "#111111",
                weight: 1.5,
                opacity: 1,
                fillOpacity: 0.9
            });

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

            marker.setStyle({ fillColor: getMarkerColor(marker) });
            marker.ownership = props.ownership ? String(props.ownership) : "UNKNOWN";
            marker.stadiumId = String(props.id);
            marker.stadiumName = props.name;

            marker.on("click", function () {
                if (activeMarker === marker && activePopup) {
                    closeActivePopup();
                    return;
                }

                closeActivePopup();

                activePopup = L.popup({
                    maxWidth: 260,
                    maxHeight: 320,
                    autoPan: true,
                    autoPanPadding: [40, 40],
                    keepInView: true
                })
                .setLatLng([coords[1], coords[0]])
                .setContent(buildPopupContent(props, 0))
                .openOn(map);

                activeMarker = marker;

                setTimeout(() => {
                    attachPopupTeamNavigation(props, coords);
                }, 0);
            });

            marker.on("mouseover", function () {
                this.setStyle({
                    radius: 9,
                    fillColor: "#ffd600"
                });
            });

            marker.on("mouseout", function () {
                this.setStyle({
                    radius: 7,
                    fillColor: getMarkerColor(this)
                });
            });

            marker.addTo(map);
            markers.push(marker);
            operationalMarkers.push(marker);
        });

        populateCountryFilter();
        populateLeagueFilter("");
        updateLegend("operational");
        applyFilters();
    });

countryFilter.addEventListener("change", function () {
    stadiumFilter.value = "";
    populateLeagueFilter(this.value);
    updateLegend("operational");
    applyFilters();
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
});

gironeFilter.addEventListener("change", function () {
    stadiumFilter.value = "";
    applyFilters();
});

ownershipFilter.addEventListener("change", function () {
    stadiumFilter.value = "";
    applyFilters();
});

stadiumFilter.addEventListener("change", function () {
    applyFilters(false);
});

mapModeToggle.addEventListener("change", function () {
    if (this.checked) {
        markers.forEach(marker => map.removeLayer(marker));
        closeActivePopup();

        operationalFilters.classList.add("d-none");
        operationalFilters.classList.remove("d-flex");

        developmentFilters.classList.remove("d-none");
        developmentFilters.classList.add("d-flex");

        loadDevelopmentStadiums();
        updateLegend("development");

        operationalLabel.classList.remove("active");
        developmentLabel.classList.add("active");

    } else {
        developmentMarkers.forEach(marker => map.removeLayer(marker));

        developmentFilters.classList.add("d-none");
        developmentFilters.classList.remove("d-flex");

        operationalFilters.classList.remove("d-none");
        operationalFilters.classList.add("d-flex");

        applyFilters();
        updateLegend("operational");

        developmentLabel.classList.remove("active");
        operationalLabel.classList.add("active");
    }
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
    applyDevelopmentFilters();
});