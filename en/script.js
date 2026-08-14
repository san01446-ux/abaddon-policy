"use strict";

(() => {
  const cfg = window.ABADDON_CONFIG || {};
  const botUrl = String(cfg.botInviteUrl || "").trim();
  const serverUrl = String(cfg.serverInviteUrl || "").trim();

  document.querySelectorAll("[data-bot-link]").forEach((el) => {
    if (botUrl) el.href = botUrl;
    el.target = "_blank";
    el.rel = "noopener";
  });
  document.querySelectorAll("[data-server-link]").forEach((el) => {
    if (serverUrl) el.href = serverUrl;
    el.target = "_blank";
    el.rel = "noopener";
  });

  const menuButton = document.querySelector("[data-menu-button]");
  const nav = document.querySelector("[data-site-nav]");
  menuButton?.addEventListener("click", () => nav?.classList.toggle("open"));
  nav?.querySelectorAll("a").forEach((link) => link.addEventListener("click", () => nav.classList.remove("open")));
})();
