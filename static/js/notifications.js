/**
 * FinSight — Notification Bell
 */
(function () {
  var userId = document.body.getAttribute("data-user-id") || "anonymous";
  var SEEN_KEY = "finsight-notif-seen-" + userId;

  function getSeenIds() {
    try { return JSON.parse(localStorage.getItem(SEEN_KEY) || "[]"); }
    catch (e) { return []; }
  }
  function markSeen(ids) {
    localStorage.setItem(SEEN_KEY, JSON.stringify(ids.slice(-100)));
  }
  function timeAgo(isoString) {
    var diff = (Date.now() - new Date(isoString).getTime()) / 1000;
    if (diff < 60) return "just now";
    if (diff < 3600) return Math.floor(diff / 60) + "m ago";
    if (diff < 86400) return Math.floor(diff / 3600) + "h ago";
    return Math.floor(diff / 86400) + "d ago";
  }
  function escapeHtml(value) {
    return String(value).replace(/[&<>"']/g, function (char) {
      return {"&":"&amp;", "<":"&lt;", ">":"&gt;", "\"":"&quot;", "'":"&#39;"}[char];
    });
  }

  document.addEventListener("DOMContentLoaded", function () {
    var btn = document.querySelector(".notif-btn");
    var panel = document.querySelector(".notif-panel");
    var badge = document.querySelector(".notif-badge");
    var list = document.querySelector(".notif-list");
    var markAllBtn = document.querySelector(".notif-panel__mark");
    if (!btn || !panel) return;

    var loaded = false;
    var allNotifs = [];

    function renderList(notifs) {
      var seen = getSeenIds();
      var unread = notifs.filter(function (n) { return !seen.includes(n.id); });
      badge.hidden = unread.length === 0;
      badge.textContent = unread.length > 99 ? "99+" : String(unread.length);
      btn.setAttribute("aria-label", unread.length ? "Notifications, " + unread.length + " new" : "Notifications");
      if (!notifs.length) {
        list.innerHTML = '<div class="notif-empty">🎉 You\'re all caught up!</div>';
        return;
      }
      list.innerHTML = notifs.map(function (n) {
        var isUnread = !seen.includes(n.id);
        return '<div class="notif-item ' + (isUnread ? "notif-item--unread" : "") + '">' +
          '<span class="notif-icon">' + escapeHtml(n.icon) + '</span>' +
          '<div class="notif-text">' +
          '<div class="notif-msg">' + escapeHtml(n.message) + '</div>' +
          '<div class="notif-time">' + escapeHtml(timeAgo(n.created_at)) + '</div>' +
          '</div></div>';
      }).join("");
    }

    function loadNotifs() {
      if (loaded) return;
      list.innerHTML = '<div class="notif-empty">Loading…</div>';
      fetch("/api/notifications", { credentials: "same-origin" })
        .then(function (r) { return r.json(); })
        .then(function (data) {
          allNotifs = data.notifications || [];
          loaded = true;
          renderList(allNotifs);
        })
        .catch(function () {
          list.innerHTML = '<div class="notif-empty">Could not load notifications.</div>';
        });
    }

    btn.addEventListener("click", function (e) {
      e.stopPropagation();
      var open = !panel.hidden;
      panel.hidden = open;
      if (!open) {
        loadNotifs();
      } else {
        // mark all seen on close
        var ids = allNotifs.map(function (n) { return n.id; });
        markSeen(ids);
        badge.hidden = true;
      }
    });

    if (markAllBtn) {
      markAllBtn.addEventListener("click", function () {
        var ids = allNotifs.map(function (n) { return n.id; });
        markSeen(ids);
        badge.hidden = true;
        renderList(allNotifs);
      });
    }

    document.addEventListener("click", function (e) {
      if (!panel.hidden && !panel.contains(e.target) && e.target !== btn) {
        panel.hidden = true;
        var ids = allNotifs.map(function (n) { return n.id; });
        markSeen(ids);
        badge.hidden = true;
      }
    });

    // Check unread count on page load (without fetching full list)
    fetch("/api/notifications", { credentials: "same-origin" })
      .then(function (r) { return r.json(); })
      .then(function (data) {
        allNotifs = data.notifications || [];
        renderList(allNotifs);
        loaded = true;
      })
      .catch(function () {});
  });
})();
