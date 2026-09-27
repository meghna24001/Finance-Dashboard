/**
 * FinSight — Sidebar Toggle
 */
(function () {
  var sidebar, overlay, hamburger;

  function open() {
    sidebar.classList.add("is-open");
    overlay.classList.add("is-open");
    hamburger.setAttribute("aria-expanded", "true");
    document.body.style.overflow = "hidden";
  }

  function close() {
    sidebar.classList.remove("is-open");
    overlay.classList.remove("is-open");
    hamburger.setAttribute("aria-expanded", "false");
    document.body.style.overflow = "";
  }

  function toggle() {
    if (sidebar.classList.contains("is-open")) close(); else open();
  }

  document.addEventListener("DOMContentLoaded", function () {
    sidebar = document.querySelector(".sidebar");
    overlay = document.querySelector(".sidebar-overlay");
    hamburger = document.querySelector(".hamburger");
    if (!sidebar || !hamburger) return;

    hamburger.addEventListener("click", toggle);
    if (overlay) overlay.addEventListener("click", close);

    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape") close();
    });

    // Close on nav link click (mobile)
    sidebar.querySelectorAll(".sidebar__link").forEach(function (link) {
      link.addEventListener("click", function () {
        if (window.innerWidth < 1024) close();
      });
    });
  });
})();
