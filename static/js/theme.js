/**
 * FinSight — Theme Manager (Light / Dark / Auto)
 * Runs before the DOM renders to avoid flash of wrong theme.
 */
(function () {
  var STORAGE_KEY = "finsight-theme";
  var THEMES = ["light", "dark", "auto"];

  function getTheme() {
    return localStorage.getItem(STORAGE_KEY) || "auto";
  }

  function applyTheme(theme) {
    var html = document.documentElement;
    if (theme === "dark") {
      html.setAttribute("data-theme", "dark");
    } else if (theme === "light") {
      html.setAttribute("data-theme", "light");
    } else {
      // "auto" — follow OS
      var prefersDark = window.matchMedia("(prefers-color-scheme: dark)").matches;
      html.setAttribute("data-theme", prefersDark ? "dark" : "light");
    }
    html.setAttribute("data-theme-pref", theme);
  }

  // Apply immediately on load (before paint)
  applyTheme(getTheme());

  // Listen for OS preference changes when on "auto"
  var mq = window.matchMedia("(prefers-color-scheme: dark)");
  mq.addEventListener("change", function () {
    if (getTheme() === "auto") applyTheme("auto");
  });

  window.FinSightTheme = {
    get: getTheme,
    set: function (theme) {
      if (!THEMES.includes(theme)) return;
      localStorage.setItem(STORAGE_KEY, theme);
      applyTheme(theme);
      updateToggle(theme);
    },
    cycle: function () {
      var current = getTheme();
      var next = THEMES[(THEMES.indexOf(current) + 1) % THEMES.length];
      window.FinSightTheme.set(next);
    },
  };

  function updateToggle(theme) {
    var btn = document.querySelector("[data-theme-toggle]");
    if (!btn) return;
    var icons = { light: "☀️", dark: "🌙", auto: "🖥️" };
    var labels = { light: "Light mode", dark: "Dark mode", auto: "Auto mode" };
    var iconEl = btn.querySelector(".theme-toggle__icon");
    var labelEl = btn.querySelector(".theme-toggle__label");
    if (iconEl) iconEl.textContent = icons[theme] || "🖥️";
    if (labelEl) labelEl.textContent = labels[theme] || "Auto mode";
    btn.setAttribute("title", "Switch theme (currently: " + theme + ")");
  }

  document.addEventListener("DOMContentLoaded", function () {
    updateToggle(getTheme());
    var btn = document.querySelector("[data-theme-toggle]");
    if (btn) {
      btn.addEventListener("click", function () {
        window.FinSightTheme.cycle();
      });
    }
  });
})();
