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

// Tenant panel is nonmodal: tab freely; restore the bell when focused panel content closes.
const tenantNotifications = document.querySelector("[data-tenant-notifications]");
if (tenantNotifications) {
    const toggle = tenantNotifications.querySelector("summary");
    const panel = tenantNotifications.querySelector(".notification-panel");
    tenantNotifications.addEventListener("toggle", () => {
        toggle.setAttribute("aria-expanded", String(tenantNotifications.open));
        if (tenantNotifications.open) panel.querySelector("h2").focus();
        else if (panel.contains(document.activeElement)) toggle.focus();
    });
}
// Enhance the shared forms in all roles; normal POST remains available without JavaScript.
document.addEventListener("click", event => {
    if (event.target.closest("[data-notification-read]")) event.stopPropagation();
});
document.addEventListener("submit", async event => {
    const form = event.target.closest("form[data-notification-read]");
    if (!form) return;
    event.preventDefault();
    event.stopPropagation();
    if (form.dataset.submitting) return;
    const button = form.querySelector('button[type="submit"]');
    const panel = form.closest(".notification-panel");
    const list = panel?.querySelector(".tenant-notification-list");
    const panelScroll = panel?.scrollTop;
    const listScroll = list?.scrollTop;
    const originalLabel = button.textContent;
    form.dataset.submitting = "true";
    button.disabled = true;
    form.querySelector(".notification-action-error")?.remove();
    try {
        const response = await fetch(form.action, {
            method: "POST", body: new FormData(form), credentials: "same-origin",
            headers: {"X-Requested-With": "XMLHttpRequest", "Accept": "application/json"}
        });
        if (!response.ok || response.redirected) throw new Error("Read update failed");
        const data = await response.json();
        if (!Array.isArray(data.read_ids) || !Number.isInteger(data.unread_count)) throw new Error("Invalid response");
        const readIds = new Set(data.read_ids.map(String));
        document.querySelectorAll("[data-notification-id]").forEach(notification => {
            if (!readIds.has(notification.dataset.notificationId)) return;
            notification.classList.remove("unread");
            const action = notification.querySelector("[data-notification-read]");
            if (action) {
                const hadFocus = action.contains(document.activeElement);
                const label = document.createElement("span");
                label.className = "notification-read-label";
                label.textContent = "Read";
                action.replaceWith(label);
                if (hadFocus) {
                    label.tabIndex = -1;
                    label.focus({preventScroll:true});
                }
            }
        });
        document.querySelectorAll("[data-tenant-notifications] summary").forEach(toggle => {
            toggle.setAttribute("aria-label", `Notifications${data.unread_count ? `, ${data.unread_count} unread` : ""}`);
            let badge = toggle.querySelector(".notification-badge");
            if (!data.unread_count) badge?.remove();
            else {
                if (!badge) {
                    badge = document.createElement("span");
                    badge.className = "notification-badge";
                    badge.setAttribute("aria-hidden", "true");
                    toggle.append(badge);
                }
                badge.textContent = data.unread_count;
            }
        });
        document.querySelectorAll(".notification-mark-all").forEach(action => { action.disabled = !data.unread_count; });
    } catch (error) {
        const notice = document.createElement("span");
        notice.className = "notification-action-error";
        notice.setAttribute("role", "alert");
        notice.textContent = "Could not update. Please retry.";
        form.append(notice);
        button.textContent = "Retry";
    } finally {
        delete form.dataset.submitting;
        if (form.isConnected && !form.querySelector(".notification-action-error")) button.textContent = originalLabel;
        if (form.isConnected && (form.querySelector(".notification-action-error") || !button.classList.contains("notification-mark-all"))) button.disabled = false;
        if (panel) panel.scrollTop = panelScroll;
        if (list) list.scrollTop = listScroll;
    }
});
