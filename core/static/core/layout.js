"use strict";

const menuButton = document.querySelector(".menu-toggle");
const navigation = document.getElementById("site-navigation");
const mobileScreen = window.matchMedia("(max-width: 700px)");

if (menuButton && navigation) {
    menuButton.hidden = false;
    function resetMenu() {
        // Without JS navigation stays visible; only the enhanced mobile menu collapses.
        navigation.hidden = mobileScreen.matches;
        menuButton.setAttribute("aria-expanded", String(!navigation.hidden));
    }
    menuButton.addEventListener("click", () => {
        navigation.hidden = !navigation.hidden;
        menuButton.setAttribute("aria-expanded", String(!navigation.hidden));
    });
    document.addEventListener("keydown", (event) => {
        const notifications = document.querySelector(".header-dropdown[open]");
        if (event.key === "Escape" && notifications) {
            notifications.open = false;
            notifications.querySelector("summary").focus();
            return;
        }
        if (event.key === "Escape" && mobileScreen.matches && !navigation.hidden) {
            navigation.hidden = true;
            menuButton.setAttribute("aria-expanded", "false");
            menuButton.focus();
        }
    });
    document.addEventListener("click", (event) => {
        const notifications = document.querySelector(".header-dropdown[open]");
        if (notifications && !notifications.contains(event.target)) notifications.open = false;
    });
    mobileScreen.addEventListener("change", resetMenu);
    resetMenu();
}

document.querySelectorAll(".message-dismiss").forEach((button) => {
    button.hidden = false;
    button.addEventListener("click", () => {
        const message = button.closest(".site-message");
        const nextButton = message.nextElementSibling?.querySelector(".message-dismiss");
        message.remove();
        // Keep keyboard focus on a useful control after removing the focused button.
        if (nextButton) nextButton.focus();
        else document.getElementById("main-content").focus();
    });
});

// Native details remain keyboard-usable without JS; keep only one dropdown open.
document.querySelectorAll(".header-dropdown").forEach((dropdown) => {
    dropdown.addEventListener("toggle", () => {
        if (dropdown.open) document.querySelectorAll(".header-dropdown").forEach((other) => {
            if (other !== dropdown) other.open = false;
        });
    });
});
