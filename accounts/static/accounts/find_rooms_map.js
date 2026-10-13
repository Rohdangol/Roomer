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
            ? `Selected point: ${point[0].toFixed(6)}, ${point[1].toFixed(6)}. Radius: ${radius.value} km. Apply to update results.`
            : `No point selected. Radius: ${radius.value} km (used when a point is selected).`;
    }
    function choose(lat, lon) {
        latitude.value = lat.toFixed(6);
        longitude.value = lon.toFixed(6);
        if (map) {
            if (marker) marker.setLatLng([lat, lon]);
            else marker = L.marker([lat, lon], {title: "Selected search location"}).addTo(map);
            map.panTo([lat, lon]);
        }
        describeSelection();
    }
    radius.addEventListener("change", describeSelection);
    clear.addEventListener("click", () => {
        latitude.value = "";
        longitude.value = "";
        if (marker && map) map.removeLayer(marker);
        marker = null;
        describeSelection();
    });
    // Never request location on page load or send coordinates to a geocoding service.
    locate.addEventListener("click", () => {
        if (!navigator.geolocation) {
            status.textContent = "Your browser does not support location. Select a point on the map or use text search.";
            return;
        }
        locate.disabled = true;
        status.textContent = "Requesting your location...";
        navigator.geolocation.getCurrentPosition(position => {
            locate.disabled = false;
            choose(position.coords.latitude, position.coords.longitude);
            if (map) map.setZoom(14);
            status.textContent = "Current location selected. Apply to search within the selected radius.";
        }, error => {
            locate.disabled = false;
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
        map.on("click", event => choose(event.latlng.lat, event.latlng.wrap().lng));
        // Keyboard users can pan with arrow keys, then select the map center.
        container.addEventListener("keydown", event => {
            if (event.key === "Enter" && event.target === container) {
                event.preventDefault();
                const point = map.getCenter().wrap();
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
