"use strict";
document.querySelectorAll("form[data-location-search]").forEach((form, index) => {
    const input = form.querySelector('input[name="q"], input[name="preferred_location"]');
    if (!input) return;
    let wrapper = input.closest(".location-autocomplete");
    if (!wrapper) {
        wrapper = document.createElement("div");
        wrapper.className = "location-autocomplete";
        input.before(wrapper);
        wrapper.append(input);
    }
    const list = document.createElement("ul");
    list.id = `location-suggestions-${index}`;
    list.className = "location-suggestions";
    list.setAttribute("role", "listbox");
    list.setAttribute("aria-label", "Matching places");
    list.hidden = true;
    const status = document.createElement("p");
    status.id = `location-status-${index}`;
    status.className = "location-search-status";
    status.setAttribute("role", "status");
    wrapper.append(list, status);
    const provider = document.createElement("small");
    provider.className = "location-search-status";
    provider.append("Suggestions: ");
    const credit = document.createElement("a");
    credit.href = "https://photon.komoot.io/";
    credit.textContent = "Photon / OpenStreetMap";
    credit.target = "_blank";
    credit.rel = "noopener";
    provider.append(credit);
    wrapper.append(provider);
    input.setAttribute("role", "combobox");
    input.setAttribute("aria-autocomplete", "list");
    input.setAttribute("aria-controls", list.id);
    input.setAttribute("aria-expanded", "false");
    input.setAttribute("aria-describedby", [input.getAttribute("aria-describedby"), status.id].filter(Boolean).join(" "));
    input.autocomplete = "off";
    const names = ["latitude", "longitude", "point_location", "resolved_label", "location_token", "point_source"];
    const field = name => form.elements.namedItem(name);
    let version = 0, timer, controller, active = -1, places = [], lastRequest = 0;
    function close() {
        list.hidden = true;
        input.setAttribute("aria-expanded", "false");
        input.removeAttribute("aria-activedescendant");
        active = -1;
    }
    function validSelection() {
        return field("latitude")?.value !== "" && field("longitude")?.value !== ""
            && field("point_location")?.value === input.value.trim()
            && (field("location_token")?.value || ["map", "gps"].includes(field("point_source")?.value));
    }
    function select(place) {
        ++version;
        clearTimeout(timer);
        controller?.abort();
        input.value = place.q;
        names.forEach(name => { if (field(name)) field(name).value = place[name] || ""; });
        input.setCustomValidity("");
        close();
        status.textContent = `Selected: ${place.q}`;
        input.dispatchEvent(new Event("locationselected"));
        input.focus();
    }
    async function lookup(current) {
        if (current !== version) return;
        lastRequest = Date.now();
        const requestController = new AbortController();
        controller = requestController;
        const timeout = setTimeout(() => requestController.abort(), 10000);
        const body = new FormData();
        body.set("q", input.value.trim());
        status.textContent = "Finding locations...";
        try {
            const response = await fetch(form.dataset.locationUrl, {
                method:"POST", body, credentials:"same-origin", signal:requestController.signal,
                headers:{"X-CSRFToken":form.dataset.csrf, "Accept":"application/json"}
            });
            const data = await response.json();
            if (current !== version) return;
            if (!response.ok || response.redirected) throw new Error(data.error || "Location lookup failed.");
            places = data.results;
            list.replaceChildren();
            places.forEach((place, number) => {
                const option = document.createElement("li");
                option.id = `${list.id}-${number}`;
                option.setAttribute("role", "option");
                option.setAttribute("aria-selected", "false");
                option.textContent = place.q;
                option.addEventListener("mousedown", event => event.preventDefault());
                option.addEventListener("click", () => select(place));
                list.append(option);
            });
            list.hidden = !places.length;
            input.setAttribute("aria-expanded", String(Boolean(places.length)));
            status.textContent = places.length ? "Choose a location from the suggestions." : "No locations found. Try a more specific area or city.";
        } catch (error) {
            if (current === version) {
                close();
                status.textContent = "Location lookup unavailable. Edit the location to retry, or select a map point on Find Rooms.";
            }
        } finally { clearTimeout(timeout); }
    }
    input.addEventListener("input", () => {
        // Restoring a selected value must not erase its matching point metadata.
        if (validSelection()) return;
        ++version;
        clearTimeout(timer);
        controller?.abort();
        names.forEach(name => { if (field(name)) field(name).value = ""; });
        ["area", "city", "resolve"].forEach(name => { if (field(name)) field(name).value = ""; });
        input.setCustomValidity("");
        close();
        if (input.value.trim().length < 2) { status.textContent = "Enter at least two characters to find a location."; return; }
        status.textContent = "Finding locations...";
        const current = version;
        // Match the shared provider throttle; never request on every keystroke.
        timer = setTimeout(() => lookup(current), Math.max(500, 2100 - (Date.now() - lastRequest)));
    });
    input.addEventListener("keydown", event => {
        if (event.key === "Escape") {
            if (!list.hidden) { event.preventDefault(); event.stopPropagation(); }
            ++version; clearTimeout(timer); controller?.abort(); close(); return;
        }
        if (list.hidden) return;
        if (["ArrowDown", "ArrowUp"].includes(event.key)) {
            event.preventDefault();
            active = (active + (event.key === "ArrowDown" ? 1 : -1) + places.length) % places.length;
            [...list.children].forEach((option, number) => option.setAttribute("aria-selected", String(number === active)));
            input.setAttribute("aria-activedescendant", list.children[active].id);
            list.children[active].scrollIntoView({block:"nearest"});
        } else if (event.key === "Enter" && active >= 0) {
            event.preventDefault(); select(places[active]);
        }
    });
    form.addEventListener("submit", event => {
        if ((input.value.trim() || form.querySelector('[name="search"]')) && !validSelection()) {
            event.preventDefault();
            status.textContent = "Choose a location from the suggestions.";
            input.setCustomValidity(status.textContent);
            input.reportValidity();
            input.focus();
        }
    });
    document.addEventListener("click", event => { if (!wrapper.contains(event.target)) close(); });
    input.addEventListener("blur", close);
});
