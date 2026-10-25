"use strict";

(() => {
    const container = document.getElementById("room-location-map");
    if (!container) return;
    const latitude = document.getElementById("id_latitude");
    const longitude = document.getElementById("id_longitude");
    const radius = document.getElementById("id_radius");
    const status = document.getElementById("map-status");
    const selection = document.getElementById("selected-point");
    const locate = document.getElementById("use-current-location");
    const clear = document.getElementById("clear-map-point");
    const query = document.getElementById("hero-location");
    const pointLocation = document.getElementById("id_point_location");
    const pointSource = document.getElementById("id_point_source");
    const locationToken = document.getElementById("id_location_token");
    const resolvedLabel = document.getElementById("id_resolved_label");
    const area = document.getElementById("id_area");
    const city = document.getElementById("id_city");
    let locationVersion = 0;
    let boundary;
    let applied = true;
    let map;
    let marker;

    function selectedPoint() {
        if (!latitude.value || !longitude.value) return null;
        const lat = Number(latitude.value), lon = Number(longitude.value);
        return Number.isFinite(lat) && Number.isFinite(lon) && Math.abs(lat) <= 90 && Math.abs(lon) <= 180 ? [lat, lon] : null;
    }
    function describeSelection() {
        const point = selectedPoint();
        selection.textContent = point
            ? `${resolvedLabel.value || pointLocation.value || "Selected map point"}: ${point[0].toFixed(6)}, ${point[1].toFixed(6)}. ${applied ? "Active radius" : "Selected radius"}: ${radius.value} km.${applied ? "" : " Apply to update results."}`
            : "No resolved point. Nearby radius is not active. Search an area or select a map point.";
        if (map && point) {
            if (boundary) boundary.setLatLng(point).setRadius(Number(radius.value) * 1000);
            else boundary = L.circle(point, {radius:Number(radius.value) * 1000, color:"#236D4A", fillOpacity:0.08}).addTo(map);
        }
    }
    function clearPoint() {
        latitude.value = "";
        longitude.value = "";
        pointLocation.value = "";
        resolvedLabel.value = "";
        locationToken.value = "";
        pointSource.value = "";
        if (marker && map) map.removeLayer(marker);
        if (boundary && map) map.removeLayer(boundary);
        marker = null;
        boundary = null;
        describeSelection();
    }
    query.addEventListener("input", () => {
        if (selectedPoint() && pointLocation.value === query.value.trim()) return;
        locationVersion += 1;
        applied = false;
        clearPoint();
        area.value = "";
        city.value = "";
        status.textContent = "Location changed. Choose a suggestion for the new area; nearby filtering is not active yet.";
    });
    document.getElementById("room-search").addEventListener("submit", () => {
        if (query.value.trim() && !selectedPoint()) {
            status.textContent = "Choose a location from the suggestions before searching.";
        }
    });

    function choose(lat, lon, source = "map") {
        query.setCustomValidity("");
        if (!applied) { pointSource.value = source; locationToken.value = ""; }
        locationVersion += 1;
        pointLocation.value = query.value.trim() || area.value.trim() || city.value.trim();
        latitude.value = lat.toFixed(6);
        longitude.value = lon.toFixed(6);
        if (map) {
            if (marker) marker.setLatLng([lat, lon]);
            else marker = L.marker([lat, lon], {title: "Selected search location"}).addTo(map);
            map.panTo([lat, lon]);
        }
        describeSelection();
    }
    query.addEventListener("locationselected", () => {
        applied = false;
        const point = selectedPoint();
        if (point && map) {
            if (marker) marker.setLatLng(point);
            else marker = L.marker(point, {title:"Selected search location"}).addTo(map);
            map.setView(point, 14);
        }
        describeSelection();
    });
    radius.addEventListener("change", () => { applied = false; describeSelection(); });
    clear.addEventListener("click", () => {
        locationVersion += 1;
        applied = false;
        clearPoint();
        status.textContent = "Point cleared. Choose a suggestion or a map point before location Search.";
    });
    // Never request location on page load or send coordinates to a geocoding service.
    locate.addEventListener("click", () => {
        if (!navigator.geolocation) {
            status.textContent = "Your browser does not support location. Select a point on the map or use text search.";
            return;
        }
        const gpsVersion = ++locationVersion;
        locate.disabled = true;
        status.textContent = "Requesting your location...";
        navigator.geolocation.getCurrentPosition(position => {
            locate.disabled = false;
            if (gpsVersion !== locationVersion) return;
            applied = false;
            resolvedLabel.value = "Current location";
            choose(position.coords.latitude, position.coords.longitude, "gps");
            if (map) map.setZoom(14);
            status.textContent = "Current location selected. Apply to search within the selected radius.";
        }, error => {
            locate.disabled = false;
            if (gpsVersion !== locationVersion) return;
            const messages = {1: "Location permission was denied.", 2: "Your location could not be determined.", 3: "Location request timed out."};
            status.textContent = `${messages[error.code] || "Location is unavailable."} Select a map point or use text search instead.`;
        }, {timeout: 10000, maximumAge: 60000});
    });
    describeSelection();
    if (!window.L) {
        status.textContent = "Map resources could not load. Text search and other filters still work; current location can still select coordinates.";
        return;
    }
    try {
        map = RoomerMaps.create(container, selectedPoint() || [27.7172, 85.3240], 12, () => {
            status.textContent = "Map tiles could not load. Use text search or current location; your selected point is retained.";
        });
        map.on("click", event => {
            applied = false;
            resolvedLabel.value = "Selected map point";
            choose(event.latlng.lat, event.latlng.wrap().lng);
        });
        // Keyboard users can pan with arrow keys, then select the map center.
        container.addEventListener("keydown", event => {
            if (event.key === "Enter" && event.target === container) {
                event.preventDefault();
                const point = map.getCenter().wrap();
                applied = false;
                resolvedLabel.value = "Selected map point";
                choose(point.lat, point.lng);
            }
        });
        const point = selectedPoint();
        if (point) choose(...point);
        status.textContent = "Click to select a location, or use arrow keys to pan and Enter to select the center.";
    } catch (error) {
        status.textContent = "The map could not start. Use text search or current location instead.";
    }
})();
