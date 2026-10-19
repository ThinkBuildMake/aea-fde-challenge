(function () {
  var B = window.Biz;

  function row(h) {
    var done = h.status === "followed_up";
    var r = B.el("div", "row handoff-row");
    r.dataset.id = h.id;

    var who = (h.caller && h.caller.name) || "No account match";
    if (h.caller && h.caller.phone) who += ", " + h.caller.phone;
    r.appendChild(B.el("span", "who", who));

    var summary = B.el("span", "summary");
    if (h.kind === "safety_stop") {
      var mark = B.el("span", "mark stop", "Safety stop");
      mark.dataset.mark = "safety_stop";
      summary.appendChild(mark);
    }
    // The mark already says "Safety stop"; do not repeat it as the reason.
    var text = h.kind === "safety_stop" && h.reason === "safety_stop" ? "" : B.label(h.reason);
    if (h.byError) text += ", after an error";
    if (h.toldCaller) text += (text ? ". " : "") + "Told: " + h.toldCaller;
    summary.appendChild(document.createTextNode(text));
    r.appendChild(summary);

    r.appendChild(
      B.el("span", "window", h.preferredWindow ? "Prefers " + h.preferredWindow : "No preference")
    );

    var btn = B.el("button", "btn-toggle");
    btn.type = "button";
    function paint() {
      btn.textContent = done ? "Followed up (undo)" : "Mark followed up";
      btn.classList.toggle("done", done);
    }
    paint();
    btn.addEventListener("click", function () {
      btn.disabled = true;
      B.postJSON("/handoffs/" + h.id + "/followed-up", { followedUp: !done })
        .then(function () {
          done = !done;
          paint();
          B.adjustWaiting(done ? -1 : 1);
        })
        .catch(function () {})
        .then(function () {
          btn.disabled = false;
        });
    });
    r.appendChild(btn);
    return r;
  }

  B.getJSON("/handoffs")
    .then(function (body) {
      B.setRows(document.getElementById("rows"), (body.handoffs || []).map(row));
    })
    .catch(function () {
      B.setRows(document.getElementById("rows"), []);
    });
})();
