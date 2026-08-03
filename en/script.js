"use strict";
document.addEventListener("DOMContentLoaded", () => {
  const cfg = window.ABADDON_CONFIG || {};
  const status = String(cfg.status || cfg.statusText || "ONLINE").toUpperCase();
  const discordUrl = cfg.discordUrl || cfg.discordInvite || "#";
  const botUrl = cfg.botInviteUrl || cfg.botInvite || discordUrl;
  document.querySelectorAll("[data-version]").forEach((el) => { el.textContent = cfg.version || "v10.9.4"; });
  document.querySelectorAll("[data-status]").forEach((el) => { el.textContent = status; });
  document.querySelectorAll("[data-status-note]").forEach((el) => { el.textContent = cfg.statusNote || ""; });
  document.querySelectorAll("[data-live-dot]").forEach((dot) => {
    dot.classList.remove("online", "offline");
    dot.classList.add(status === "ONLINE" ? "online" : "offline");
  });
  document.querySelectorAll("[data-bot-link]").forEach((el) => { el.href = botUrl; el.target = "_blank"; el.rel = "noopener"; });
  document.querySelectorAll("[data-discord-link]").forEach((el) => { el.href = discordUrl; el.target = "_blank"; el.rel = "noopener"; });
  const button = document.querySelector("[data-menu-button]");
  const nav = document.querySelector("[data-site-nav]");
  if (button && nav) button.addEventListener("click", () => nav.classList.toggle("open"));
  const toast = document.getElementById("copy-toast");
  document.querySelectorAll("[data-copy-command]").forEach((el) => el.addEventListener("click", async () => {
    const value = el.dataset.copyCommand || "";
    try {
      await navigator.clipboard.writeText(value);
      if (toast) {
        toast.textContent = `Copied: ${value}`;
        toast.classList.add("show");
        setTimeout(() => toast.classList.remove("show"), 1500);
      }
    } catch (_) { /* clipboard may be blocked */ }
  }));
  const search = document.getElementById("english-command-search");
  if (search) search.addEventListener("input", () => {
    const value = search.value.trim().toLowerCase();
    document.querySelectorAll(".command-card[data-search]").forEach((card) => {
      card.hidden = Boolean(value) && !String(card.dataset.search || "").includes(value);
    });
  });
});
