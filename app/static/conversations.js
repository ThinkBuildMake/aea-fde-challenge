(function () {
  var B = window.Biz;
  var listEl = document.getElementById("convo-list");
  var detailEl = document.getElementById("detail");

  function outcomeOf(outcome) {
    var o = B.data.outcomes || {};
    return o[outcome || "active"] || [B.label(outcome), "muted"];
  }
  function whatOf(intent) {
    return (B.data.intents || {})[intent] || "Other";
  }
  function whenOf(startedAt) {
    var m = Math.max(0, Math.floor((Date.now() - new Date(startedAt).getTime()) / 60000));
    if (m < 60) return m + " min";
    if (m < 1440) return Math.floor(m / 60) + " h";
    var d = Math.floor(m / 1440);
    return d + (d === 1 ? " day" : " days");
  }

  function renderTurn(t) {
    var d = B.el("div", "turn");
    d.dataset.seq = t.seq;
    if (t.callerText) d.appendChild(B.el("div", null, "Caller: " + t.callerText));
    if (t.replyText) d.appendChild(B.el("div", null, "Agent: " + t.replyText));
    if (t.traceId) {
      var trace = B.el("div", "turn-trace");
      var a = B.el("a", "trace-link", "Open trace");
      a.href = (B.data.traceBase || "") + "/trace/" + encodeURIComponent(t.traceId);
      a.target = "_blank";
      a.rel = "noopener";
      trace.appendChild(a);
      d.appendChild(trace);
    }
    return d;
  }

  function renderDetail(detail) {
    var s = detail.summary;
    var oc = outcomeOf(s.outcome);
    var id = s.publicId;
    detailEl.textContent = "";
    detailEl.appendChild(B.el("h2", "detail-title", whatOf(s.intent) + " (" + oc[0] + ")"));

    var meta = [id, s.turnCount + (s.turnCount === 1 ? " turn" : " turns")];
    var timed = detail.turns.filter(function (t) {
      return t.latencyMs !== null && t.latencyMs !== undefined;
    })[0];
    if (timed) meta.push("first reply " + (timed.latencyMs / 1000).toFixed(1) + " s");
    if (s.outcomeReason) meta.push("reason: " + B.label(s.outcomeReason).toLowerCase());
    var cost = s.costUsd;
    meta.push("cost $" + cost.toFixed(cost > 0 && cost < 0.01 ? 4 : 2));
    detailEl.appendChild(B.el("div", "meta", meta.join(" · ")));

    var tr = B.el("div", "transcript");
    detail.turns.forEach(function (t) {
      tr.appendChild(renderTurn(t));
    });
    if (s.solved === "yes") tr.appendChild(B.el("div", null, "Caller tapped: yes, that solved it"));
    else if (s.solved === "no") tr.appendChild(B.el("div", null, "Caller tapped: no"));
    detailEl.appendChild(tr);

    var toolNames = [];
    detail.turns.forEach(function (t) {
      (t.toolsCalled || []).forEach(function (c) {
        if (toolNames.indexOf(c.name) < 0) toolNames.push(c.name);
      });
    });
    detailEl.appendChild(B.el("div", "convo-tools", "Tools called: " + (toolNames.length ? toolNames.join(", ") : "none")));

    var flagged = !!(s.flagged || (detail.flags && detail.flags.length));
    var buttons = B.el("div", "btn-row");
    var flagBtn = B.el("button", "btn-flag");
    flagBtn.type = "button";
    var evalBtn = B.el("button", "btn-eval", "Turn into a test scenario");
    evalBtn.type = "button";
    evalBtn.disabled = !s.outcome || s.outcome === "active";
    buttons.appendChild(flagBtn);
    buttons.appendChild(evalBtn);
    detailEl.appendChild(buttons);

    var box = null;
    var savedLine = B.el("p", "eval-saved");
    savedLine.hidden = true;

    function paintFlag() {
      flagBtn.textContent = flagged ? "Flagged as wrong (undo)" : "Flag as wrong";
      flagBtn.classList.toggle("on", flagged);
    }
    function closeBox() {
      if (box) box.remove();
      box = null;
    }
    function openBox() {
      box = B.el("form", "flag-box");
      var lab = B.el("label", null, "What was wrong? (note saved with the flag)");
      lab.htmlFor = "note";
      var input = B.el("input");
      input.id = "note";
      input.type = "text";
      input.autocomplete = "off";
      input.placeholder = "e.g. quoted the old $79 fee, then press Enter";
      var last = flagged && detail.flags && detail.flags.length ? detail.flags[detail.flags.length - 1].note : "";
      if (flagged) {
        input.value = last;
        input.disabled = true;
      }
      box.appendChild(lab);
      box.appendChild(input);
      var ask = null;
      box.addEventListener("submit", function (e) {
        e.preventDefault();
        var note = input.value.trim();
        if (flagged) return;
        if (!note) {
          if (!ask) {
            ask = B.el("p", "flag-note-needed", "A note saying what was wrong is required.");
            ask.setAttribute("role", "alert");
            box.appendChild(ask);
          }
          return;
        }
        input.disabled = true;
        B.postJSON("/conversations/" + encodeURIComponent(id) + "/flag", { note: note })
          .then(function () {
            flagged = true;
            if (ask) ask.remove();
            ask = null;
            paintFlag();
            B.clearError(flagBtn);
          })
          .catch(function () {
            input.disabled = false;
            B.saveError(flagBtn);
          });
      });
      detailEl.insertBefore(box, savedLine);
      if (!flagged) input.focus();
    }
    flagBtn.addEventListener("click", function () {
      if (flagged || box) {
        // Undo is local to this page: there is no route to delete a flag.
        flagged = false;
        paintFlag();
        closeBox();
        return;
      }
      openBox();
    });
    paintFlag();

    function showSaved(scenarioId) {
      savedLine.textContent =
        "Saved as a candidate test scenario: eval/candidates/" +
        scenarioId +
        ".json. Review it, then add it to the eval set.";
      savedLine.hidden = false;
    }
    evalBtn.addEventListener("click", function () {
      evalBtn.disabled = true;
      B.postJSON("/conversations/" + encodeURIComponent(id) + "/eval-candidate")
        .then(function (b) {
          showSaved(b.candidate.scenarioId);
          B.clearError(evalBtn);
        })
        .catch(function () {
          B.saveError(evalBtn);
        })
        .then(function () {
          evalBtn.disabled = !s.outcome || s.outcome === "active";
        });
    });

    detailEl.appendChild(savedLine);
    if (detail.evalCandidate) showSaved(detail.evalCandidate.scenarioId);
    if (flagged) openBox();
  }

  var latest = null;

  function select(btn, id) {
    latest = id;
    Array.prototype.forEach.call(listEl.children, function (c) {
      c.classList.toggle("selected", c === btn);
    });
    B.getJSON("/conversations/" + encodeURIComponent(id))
      .then(function (detail) {
        if (id === latest) renderDetail(detail);
      })
      .catch(function () {
        if (id === latest) B.failRows(detailEl, "Could not load this conversation.");
      });
  }

  B.getJSON("/conversations?limit=50")
    .then(function (body) {
      var items = body.conversations || [];
      var btns = items.map(function (c) {
        var oc = outcomeOf(c.outcome);
        var b = B.el("button", "convo-btn");
        b.type = "button";
        b.dataset.publicId = c.publicId;
        b.appendChild(B.el("span", "when", whenOf(c.startedAt)));
        b.appendChild(B.el("span", "what", whatOf(c.intent)));
        b.appendChild(B.el("span", "outcome " + oc[1], oc[0]));
        b.addEventListener("click", function () {
          select(b, c.publicId);
        });
        return b;
      });
      B.setRows(listEl, btns);
      if (btns.length) select(btns[0], items[0].publicId);
      else detailEl.appendChild(B.el("p", "empty", "No data yet"));
    })
    .catch(function () {
      B.failRows(listEl, "Could not load conversations. Reload to try again.");
    });
})();
