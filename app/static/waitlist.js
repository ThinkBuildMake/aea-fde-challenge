(function () {
  var B = window.Biz;
  var SERVICE = { hvac_repair: "HVAC repair", hvac_tune_up: "Tune-up", plumbing: "Plumbing" };
  var DAYS = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];

  function hour(hhmm) {
    var h = parseInt(hhmm.split(":")[0], 10);
    return String(h % 12 || 12);
  }
  function range(w) {
    var p = String(w).split("-");
    return p.length === 2 ? hour(p[0]) + " to " + hour(p[1]) : String(w);
  }
  function ago(seconds) {
    if (seconds < 60) return "Just now";
    if (seconds < 3600) return Math.floor(seconds / 60) + " min ago";
    if (seconds < 86400) return Math.floor(seconds / 3600) + " h ago";
    var d = Math.floor(seconds / 86400);
    return d + (d === 1 ? " day ago" : " days ago");
  }

  function row(w) {
    var r = B.el("div", "row waitlist-row");
    var who = [w.caller.name, w.caller.city, w.zone].filter(Boolean).join(", ");
    r.appendChild(B.el("span", "who", who));
    var day = DAYS[new Date(w.held.date + "T00:00:00Z").getUTCDay()];
    var svc = SERVICE[w.serviceType] || B.label(w.serviceType);
    r.appendChild(
      B.el("span", "want", svc + ", earlier than " + day + " " + w.held.date + " " + range(w.held.window))
    );
    r.appendChild(B.el("span", "since", ago(w.waitingSeconds)));
    return r;
  }

  B.getJSON("/waitlist")
    .then(function (body) {
      B.setRows(document.getElementById("rows"), (body.entries || []).map(row));
    })
    .catch(function () {
      B.setRows(document.getElementById("rows"), []);
    });
})();
