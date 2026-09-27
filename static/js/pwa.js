// Turns the website into an installable app.
(function () {
  // 1. Register the service worker (needs https, or localhost while testing).
  if ("serviceWorker" in navigator) {
    window.addEventListener("load", function () {
      navigator.serviceWorker.register("/sw.js").catch(function () {
        // Not fatal: the site works normally without it.
      });
    });
  }

  // 2. The "Install the app" box on the Profile page.
  var panel = document.querySelector("[data-install-panel]");
  if (!panel) return;

  var button = panel.querySelector("[data-install-button]");
  var iosNote = panel.querySelector("[data-install-ios]");
  var installedNote = panel.querySelector("[data-installed]");
  var defaultNote = panel.querySelector("[data-install-default]");
  var offered = null;

  function show(element, visible) {
    if (element) element.hidden = !visible;
  }

  var standalone =
    (window.matchMedia && window.matchMedia("(display-mode: standalone)").matches) ||
    window.navigator.standalone === true;
  var ua = navigator.userAgent || "";
  var isIos = /iphone|ipad|ipod/i.test(ua) || (/macintosh/i.test(ua) && navigator.maxTouchPoints > 1);

  if (standalone) {
    show(defaultNote, false);
    show(installedNote, true);
    return;
  }
  if (isIos) {
    // iPhones never offer a button. People install from the Share menu instead.
    show(defaultNote, false);
    show(iosNote, true);
  }

  window.addEventListener("beforeinstallprompt", function (event) {
    event.preventDefault(); // keep the browser's own banner quiet; we show our button
    offered = event;
    show(defaultNote, false);
    show(button, true);
  });

  if (button) {
    button.addEventListener("click", function () {
      if (!offered) return;
      offered.prompt();
      offered.userChoice.then(function () {
        offered = null;
        show(button, false);
      });
    });
  }

  window.addEventListener("appinstalled", function () {
    show(button, false);
    show(defaultNote, false);
    show(installedNote, true);
  });
})();
