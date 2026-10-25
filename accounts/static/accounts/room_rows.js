"use strict";

document.querySelectorAll("[data-room-row]").forEach(row => {
    const controls = document.querySelector(`[data-room-controls="${row.id}"]`);
    if (!controls || !row.querySelector(".room-card")) return;
    controls.hidden = false;
    const previous = controls.querySelector('[data-row-direction="-1"]');
    const next = controls.querySelector('[data-row-direction="1"]');
    function updateControls() {
        previous.disabled = row.scrollLeft <= 2;
        next.disabled = row.scrollLeft >= row.scrollWidth - row.clientWidth - 2;
    }
    controls.addEventListener("click", event => {
        const button = event.target.closest("[data-row-direction]");
        if (!button || button.disabled) return;
        const card = row.querySelector(".room-card");
        const step = card.getBoundingClientRect().width + parseFloat(getComputedStyle(row).columnGap);
        row.scrollBy({left: Number(button.dataset.rowDirection) * step,
            behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "instant" : "smooth"});
    });
    row.addEventListener("scroll", updateControls, {passive:true});
    const observer = new ResizeObserver(updateControls);
    observer.observe(row);
    row.querySelectorAll(".room-card").forEach(card => observer.observe(card));
    row.addEventListener("keydown", event => {
        if (event.target !== row) return;
        if (event.key === "ArrowLeft" || event.key === "ArrowRight") {
            event.preventDefault();
            (event.key === "ArrowLeft" ? previous : next).click();
        }
    });
    // Native touch/trackpad scrolling remains intact. Suppress only the trailing
    // pointer click of a horizontal swipe, never keyboard activation of actions.
    let startX = 0, startY = 0, tracking = false, swiped = false, swipeTime = 0;
    row.addEventListener("pointerdown", event => {
        startX = event.clientX;
        startY = event.clientY;
        tracking = true;
        swiped = false;
    }, {passive:true});
    row.addEventListener("pointermove", event => {
        if (tracking && Math.abs(event.clientX - startX) > 10 && Math.abs(event.clientX - startX) > Math.abs(event.clientY - startY)) {
            swiped = true;
            swipeTime = Date.now();
        }
    }, {passive:true});
    row.addEventListener("pointerup", () => { tracking = false; });
    row.addEventListener("pointercancel", () => { tracking = false; });
    row.addEventListener("click", event => {
        if (event.detail && swiped && Date.now() - swipeTime < 700) {
            event.preventDefault();
            event.stopImmediatePropagation();
        }
    }, true);
    row.querySelectorAll("img").forEach(image => { image.draggable = false; });
    updateControls();
});
