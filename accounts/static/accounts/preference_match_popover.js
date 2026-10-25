"use strict";
(() => {
    const button = document.querySelector(".match-info-button");
    const panel = document.getElementById("preference-match-popover");
    if (!button || !panel) return;
    // Position outside card overflow, while keeping the description associated by ID.
    document.body.append(panel);
    let pinned = false, closeTimer;
    function position() {
        if (panel.hidden) return;
        const rect = button.getBoundingClientRect();
        const width = document.documentElement.clientWidth;
        const height = window.innerHeight;
        panel.style.maxHeight = `${Math.max(80, height - 24)}px`;
        const size = panel.getBoundingClientRect();
        panel.style.left = `${Math.max(12, Math.min(rect.right - size.width, width - size.width - 12))}px`;
        const below = rect.bottom + 8;
        panel.style.top = `${Math.max(12, Math.min(below + size.height <= height - 12 ? below : rect.top - size.height - 8, height - size.height - 12))}px`;
    }
    function open() {
        clearTimeout(closeTimer);
        panel.hidden = false;
        button.setAttribute("aria-expanded", "true");
        position();
    }
    function close() {
        clearTimeout(closeTimer);
        panel.hidden = true;
        button.setAttribute("aria-expanded", "false");
        pinned = false;
    }
    function leave() {
        if (!pinned && document.activeElement !== button) closeTimer = setTimeout(close, 180);
    }
    button.addEventListener("pointerenter", event => { if (event.pointerType === "mouse") open(); });
    button.addEventListener("pointerleave", leave);
    button.addEventListener("focus", () => { if (button.matches(":focus-visible")) open(); });
    button.addEventListener("blur", leave);
    button.addEventListener("click", () => {
        if (pinned) close();
        else { pinned = true; open(); }
    });
    panel.addEventListener("pointerenter", () => clearTimeout(closeTimer));
    panel.addEventListener("pointerleave", leave);
    document.addEventListener("keydown", event => {
        if (event.key === "Escape" && !panel.hidden) {
            event.preventDefault(); close();
        }
    });
    document.addEventListener("click", event => {
        if (!button.contains(event.target) && !panel.contains(event.target)) close();
    });
    window.addEventListener("resize", position);
    window.addEventListener("scroll", position, true);
})();
