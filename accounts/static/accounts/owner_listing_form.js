"use strict";
(function initializeListingForm(retainedFiles = []) {
    const availableFrom = document.getElementById("id_available_from");
    const dateError = document.createElement("p");
    dateError.id = "available-from-client-error";
    dateError.className = "errorlist";
    dateError.setAttribute("aria-live", "polite");
    availableFrom.after(dateError);
    availableFrom.setAttribute("aria-describedby", [availableFrom.getAttribute("aria-describedby"), dateError.id].filter(Boolean).join(" "));
    function validateAvailableDate() {
        const value = availableFrom.value;
        let message = "";
        if (availableFrom.validity.badInput) {
            message = "Enter a complete, valid date.";
        } else if (value && value !== availableFrom.dataset.originalDate && value < availableFrom.dataset.today) {
            message = "Choose today or a future date. An existing past date may only be kept unchanged.";
        }
        availableFrom.setCustomValidity(message);
        dateError.textContent = message;
    }
    // Leave the native segmented editor and its stable server-rendered minimum alone.
    // Clear the previous error on focus; validate only after editing is finished.
    availableFrom.addEventListener("focus", () => {
        availableFrom.setCustomValidity("");
        dateError.textContent = "";
    });
    availableFrom.addEventListener("blur", validateAvailableDate);
    availableFrom.addEventListener("invalid", validateAvailableDate);
    const input = document.getElementById("id_photos");
    const previews = document.getElementById("photo-previews");
    let files = retainedFiles;
    let urls = [];
    function renderPhotos() {
        urls.forEach(url => URL.revokeObjectURL(url));
        urls = [];
        previews.replaceChildren();
        const transfer = new DataTransfer();
        const keptPhotos = document.querySelectorAll('#existing-photos input:not(:checked)').length;
        files.forEach((file, index) => {
            transfer.items.add(file);
            const figure = document.createElement("figure");
            figure.className = "listing-photo-preview";
            const image = document.createElement("img");
            image.src = URL.createObjectURL(file);
            urls.push(image.src);
            image.alt = `Selected photo ${index + 1}`;
            const caption = document.createElement("figcaption");
            caption.textContent = `${index === 0 && keptPhotos === 0 ? "Cover - " : ""}${file.name}`;
            const remove = document.createElement("button");
            remove.type = "button";
            remove.textContent = "Remove";
            remove.setAttribute("aria-label", `Remove ${file.name}`);
            remove.addEventListener("click", () => { files.splice(index, 1); renderPhotos(); });
            figure.append(image, caption, remove);
            previews.append(figure);
        });
        input.files = transfer.files;
    }
    if (files.length) renderPhotos();
    document.querySelectorAll('#existing-photos input').forEach(checkbox => checkbox.addEventListener("change", renderPhotos));
    input.addEventListener("change", () => { files.push(...input.files); renderPhotos(); });
    window.addEventListener("pagehide", () => urls.forEach(url => URL.revokeObjectURL(url)));

    const container = document.getElementById("listing-map");
    const latitude = document.getElementById("id_latitude");
    const longitude = document.getElementById("id_longitude");
    const status = document.getElementById("listing-map-status");
    let map, marker;
    let locationVersion = 0;
    const cityInput = document.getElementById("id_city");
    const addressInput = document.getElementById("id_address");
    function invalidateLocationRequests() {
        locationVersion += 1;
        results.replaceChildren();
        searchStatus.textContent = "";
        currentStatus.textContent = "";
        return locationVersion;
    }
    function isCurrent(version) {
        return version === locationVersion && container.isConnected;
    }
    cityInput.addEventListener("input", invalidateLocationRequests);
    addressInput.addEventListener("input", invalidateLocationRequests);
    let selectedLabel = "Saved location";
    function point() {
        const lat = Number(latitude.value), lon = Number(longitude.value);
        return latitude.value && longitude.value && Number.isFinite(lat) && Number.isFinite(lon) && Math.abs(lat) <= 90 && Math.abs(lon) <= 180 ? [lat, lon] : null;
    }
    function updateMarker() {
        const selected = point();
        if (!selected || !map) return;
        if (marker) marker.setLatLng(selected);
        else {
            marker = L.marker(selected, {draggable:true, title:"Property location"}).addTo(map);
            marker.on("dragstart", invalidateLocationRequests);
            marker.on("dragend", () => choose(marker.getLatLng().wrap()));
        }
        map.panTo(selected);
        status.textContent = `${selectedLabel}: ${selected[0].toFixed(6)}, ${selected[1].toFixed(6)}. Drag the pin or click the map to adjust.`;
    }
    function choose(selected, label = "Manually adjusted pin") {
        invalidateLocationRequests();
        selectedLabel = label;
        latitude.value = selected.lat.toFixed(6);
        longitude.value = selected.lng.toFixed(6);
        updateMarker();
    }
    latitude.addEventListener("change", updateMarker);
    longitude.addEventListener("change", updateMarker);
    const currentLocation = document.getElementById("use-current-location");
    const currentStatus = document.getElementById("current-location-status");
    currentLocation.addEventListener("click", () => {
        if (!map) { currentStatus.textContent = "The map is unavailable. Your existing pin is retained."; return; }
        if (!navigator.geolocation || !window.isSecureContext) {
            currentStatus.textContent = "Current location requires HTTPS or localhost and browser location support. Search the address or select a pin manually.";
            return;
        }
        const gpsVersion = invalidateLocationRequests();
        currentLocation.disabled = true;
        currentStatus.textContent = "Requesting your current location...";
        navigator.geolocation.getCurrentPosition(async position => {
            if (!isCurrent(gpsVersion)) { currentLocation.disabled = false; return; }
            choose({lat: position.coords.latitude, lng: position.coords.longitude}, "Current location");
            map.setView([position.coords.latitude, position.coords.longitude], 16);
            const reverseVersion = locationVersion;
            currentStatus.textContent = "Location selected. Looking up the address...";
            const body = new FormData();
            body.set("mode", "reverse");
            body.set("latitude", position.coords.latitude);
            body.set("longitude", position.coords.longitude);
            const controller = new AbortController();
            const timeout = setTimeout(() => controller.abort(), 10000);
            try {
                const response = await fetch(search.dataset.url, {
                    method: "POST", body, credentials: "same-origin", signal: controller.signal,
                    headers: {"X-CSRFToken": document.querySelector('[name="csrfmiddlewaretoken"]').value}
                });
                const data = await response.json();
                if (!isCurrent(reverseVersion)) return;
                const result = data.results?.[0];
                if (!response.ok || !result?.address) throw new Error("Address unavailable");
                if (result.city) cityInput.value = result.city;
                addressInput.value = result.address;
                if (result.locality) document.getElementById("id_locality").value = result.locality;
                currentStatus.textContent = "Location and nearby address selected. Please confirm or add address details and adjust the pin if needed.";
            } catch (error) {
                if (isCurrent(reverseVersion)) currentStatus.textContent = "Location selected. Please enter or confirm the address.";
            } finally {
                clearTimeout(timeout);
                currentLocation.disabled = false;
            }
        }, error => {
            currentLocation.disabled = false;
            if (!isCurrent(gpsVersion)) return;
            const messages = {1: "Location permission was denied.", 2: "Your current location is unavailable.", 3: "Location request timed out."};
            currentStatus.textContent = `${messages[error.code] || "Could not get your location."} Your address and existing pin are unchanged. Search the address or select a pin manually.`;
            currentLocation.disabled = false;
        }, {enableHighAccuracy: true, timeout: 10000, maximumAge: 0});
    });
    const search = document.getElementById("find-listing-location");
    const searchStatus = document.getElementById("location-search-status");
    const results = document.getElementById("location-search-results");
    search.addEventListener("click", async () => {
        const searchVersion = invalidateLocationRequests();
        const body = new FormData();
        for (const name of ["city", "address"]) {
            const value = document.getElementById(`id_${name}`).value.trim();
            if (!value) {
                searchStatus.textContent = "Enter city and address before searching.";
                document.getElementById(`id_${name}`).focus();
                return;
            }
            body.set(name, value);
        }
        search.disabled = true;
        searchStatus.textContent = "Finding matching locations...";
        const controller = new AbortController();
        const timeout = setTimeout(() => controller.abort(), 10000);
        try {
            const response = await fetch(search.dataset.url, {
                method: "POST", body, credentials: "same-origin", signal: controller.signal,
                headers: {"X-CSRFToken": document.querySelector('[name="csrfmiddlewaretoken"]').value}
            });
            const data = await response.json();
            if (!isCurrent(searchVersion)) return;
            if (!response.ok) throw new Error(data.error || "Location search failed. Select a pin manually or retry.");
            searchStatus.textContent = data.results.length ? "Select a matching location below. Your address will not change." : "No matching locations found. Try a broader address or select a pin manually.";
            data.results.forEach(result => {
                const item = document.createElement("li");
                const button = document.createElement("button");
                button.type = "button";
                button.textContent = result.label;
                button.addEventListener("click", () => {
                    if (!isCurrent(searchVersion)) return;
                    if (!map) {
                        searchStatus.textContent = "The map is unavailable. Reload to select a pin; your entered details are retained.";
                        return;
                    }
                    if (result.locality) document.getElementById("id_locality").value = result.locality;
                    choose({lat: result.latitude, lng: result.longitude}, result.label);
                    map.setView([result.latitude, result.longitude], 16);
                    searchStatus.textContent = "Location selected. Adjust the pin for accuracy.";
                    container.focus();
                });
                item.append(button);
                results.append(item);
            });
        } catch (error) {
            if (!isCurrent(searchVersion)) return;
            searchStatus.textContent = error instanceof SyntaxError || error instanceof TypeError ? "Could not reach location search. Retry or select a pin manually; your entered details are retained." : error.message;
        } finally {
            clearTimeout(timeout);
            search.disabled = false;
        }
    });
    const form = document.querySelector(".owner-listing-form");
    form.addEventListener("submit", async event => {
        event.preventDefault();
        validateAvailableDate();
        if (!form.reportValidity()) return;
        invalidateLocationRequests();
        const publish = form.querySelector('[type="submit"]');
        publish.disabled = true;
        try {
            const response = await fetch(window.location.href, {method:"POST", body:new FormData(form), credentials:"same-origin", headers:{"X-Requested-With":"XMLHttpRequest"}});
            if (response.ok && response.headers.get("Content-Type")?.includes("application/json")) {
                const result = await response.json();
                window.location.assign(result.redirect_url);
                return;
            }
            if (response.redirected) {
                window.location.assign(response.url);
                return;
            }
            const documentResponse = new DOMParser().parseFromString(await response.text(), "text/html");
            const updatedForm = documentResponse.querySelector(".owner-listing-form");
            if (!response.ok || !updatedForm) throw new Error("Submission unavailable");
            if (map) map.remove();
            urls.forEach(url => URL.revokeObjectURL(url));
            form.replaceWith(updatedForm);
            const summary = updatedForm.querySelector(".listing-errors p");
            if (summary) summary.textContent = "Please correct the errors below. Your details and selected photos are retained.";
            initializeListingForm(files);
            updatedForm.querySelector(".listing-errors")?.scrollIntoView({block:"center"});
        } catch (error) {
            let notice = form.querySelector(".submission-error");
            if (!notice) {
                notice = document.createElement("p");
                notice.className = "submission-error listing-errors";
                notice.setAttribute("role", "alert");
                form.prepend(notice);
            }
            notice.textContent = "Could not confirm submission. Check My Listings before retrying; your entered details remain here.";
            notice.scrollIntoView({block:"center"});
            publish.disabled = false;
        }
    });
    if (!window.L || !window.RoomerMaps) {
        status.textContent = "Map could not load. Your details and saved pin are retained. Reload to select a new pin.";
        return;
    }
    try {
        map = RoomerMaps.create(container, point() || [27.7172,85.3240], 12, () => {
            status.textContent = "Map tiles could not load. Your pin is retained; retry when your connection is available.";
        });
        map.on("click", event => choose(event.latlng.wrap()));
        container.addEventListener("keydown", event => {
            if (event.key === "Enter" && event.target === container) {
                event.preventDefault(); choose(map.getCenter().wrap());
            }
        });
        status.textContent = "Click to place the pin, drag it to adjust, or pan with arrow keys and press Enter.";
        updateMarker();
    } catch (error) {
        status.textContent = "Map could not start. Your entered details and saved pin are retained. Reload to select a new pin.";
    }
})();
