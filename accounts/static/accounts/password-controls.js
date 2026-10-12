"use strict";

document.querySelectorAll(".password-toggle").forEach((button) => {
    const input = document.getElementById(button.getAttribute("aria-controls"));
    button.hidden = false;
    button.parentElement.classList.add("controls-ready");
    button.addEventListener("click", () => {
        const visible = input.type === "password";
        input.type = visible ? "text" : "password";
        button.setAttribute("aria-pressed", String(visible));
        button.setAttribute("aria-label", `${visible ? "Hide" : "Show"} ${button.dataset.passwordLabel}`);
    });
});

document.querySelectorAll(".password-help").forEach((container) => {
    const button = container.querySelector(".password-help-toggle");
    const popover = container.querySelector(".password-help-content");
    let pinned = false;

    // Hide help only after enhancement, so the requirements remain available without JS.
    button.hidden = false;
    popover.hidden = true;
    popover.classList.add("is-popover");
    container.parentElement.classList.add("controls-ready");

    function positionPopover() {
        if (popover.hidden) return;
        const margin = 16;
        const rect = button.getBoundingClientRect();
        const width = Math.min(320, window.innerWidth - margin * 2);
        popover.style.width = `${width}px`;
        popover.style.maxHeight = `${window.innerHeight - margin * 2}px`;
        popover.style.left = `${Math.max(margin, Math.min(rect.left, window.innerWidth - width - margin))}px`;
        const height = popover.getBoundingClientRect().height;
        const top = rect.bottom + 8 + height <= window.innerHeight - margin
            ? rect.bottom + 8 : rect.top - height - 8;
        popover.style.top = `${Math.max(margin, Math.min(top, window.innerHeight - height - margin))}px`;
    }

    function open() {
        popover.hidden = false;
        button.setAttribute("aria-expanded", "true");
        positionPopover();
    }

    function close() {
        pinned = false;
        popover.hidden = true;
        button.setAttribute("aria-expanded", "false");
    }

    container.addEventListener("mouseenter", open);
    container.addEventListener("mouseleave", (event) => {
        if (!pinned && !container.contains(event.relatedTarget) && !container.contains(document.activeElement)) close();
    });
    container.addEventListener("focusin", open);
    container.addEventListener("focusout", (event) => {
        if (!container.contains(event.relatedTarget)) close();
    });
    button.addEventListener("click", () => {
        if (pinned) close();
        else { pinned = true; open(); }
    });
    document.addEventListener("keydown", (event) => {
        if (event.key === "Escape") close();
    });
    document.addEventListener("click", (event) => {
        if (!container.contains(event.target)) close();
    });
    // Fixed positioning avoids the card's clipping and keeps help inside the viewport.
    window.addEventListener("resize", positionPopover);
    window.addEventListener("scroll", positionPopover, true);
});
