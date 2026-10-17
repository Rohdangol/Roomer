"use strict";
(() => {
    const editor = document.getElementById("preference-editor");
    const container = document.getElementById("preference-location-map");
    if (!editor || !container) return;
    const latitude = document.getElementById("id_latitude");
    const longitude = document.getElementById("id_longitude");
    const coordinatesSelected = document.getElementById("id_coordinates_selected");
    const status = document.getElementById("preference-map-status");
    let map, marker;
    function point() {
        const lat = Number(latitude.value), lon = Number(longitude.value);
        return latitude.value && longitude.value && Number.isFinite(lat) && Number.isFinite(lon) && Math.abs(lat)<=90 && Math.abs(lon)<=180 ? [lat,lon] : null;
    }
    function select(lat, lon, userSelected = true) {
        if (userSelected && coordinatesSelected) coordinatesSelected.value = "true";
        latitude.value = lat.toFixed(6);
        longitude.value = lon.toFixed(6);
        if (marker) marker.setLatLng([lat,lon]);
        else marker = L.marker([lat,lon], {title:"Preferred room location"}).addTo(map);
        status.textContent = "Location selected. Enter its area name above and save preferences.";
    }
    function initialize() {
        if (!editor.open) return;
        if (map) { map.invalidateSize(); return; }
        if (!window.L || !window.RoomerMaps) {
            status.textContent = "Map unavailable. Save a text-only location or enter both coordinates.";
            return;
        }
        try {
            map = RoomerMaps.create(container, point() || [27.7172,85.3240],12,()=>{
                status.textContent = "Map tiles could not load. Text-only preferences can still be saved.";
            });
            if (point()) select(...point(), false);
            map.on("click", event=>select(event.latlng.lat,event.latlng.wrap().lng));
            container.addEventListener("keydown",event=>{
                if(event.key==="Enter" && event.target===container){event.preventDefault();const p=map.getCenter().wrap();select(p.lat,p.lng);}
            });
            [latitude,longitude].forEach(input=>input.addEventListener("change",()=>{if(point()){select(...point());map.panTo(point());}}));
        } catch(error) { status.textContent = "Map unavailable. Save a text-only location or enter both coordinates."; }
    }
    // Initialize only when expanded so hidden Leaflet dimensions are correct.
    editor.addEventListener("toggle",initialize);
    initialize();
})();
