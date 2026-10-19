// Shared helpers for the Handoffs, Waitlist and Conversations tabs.
// Rows are built with textContent only: caller text is untrusted.
window.Biz = (function () {
  var data = {};
  try {
    data = JSON.parse(document.getElementById("biz-data").textContent);
  } catch (e) {
    data = {};
  }

  function request(method, url, body) {
    var opts = { method: method, headers: { Accept: "application/json" } };
    if (body !== undefined) {
      opts.headers["Content-Type"] = "application/json";
      opts.body = JSON.stringify(body);
    }
    return fetch(url, opts).then(function (r) {
      if (!r.ok) throw new Error("HTTP " + r.status);
      return r.json();
    });
  }

  function el(tag, className, text) {
    var n = document.createElement(tag);
    if (className) n.className = className;
    if (text !== undefined && text !== null) n.textContent = text;
    return n;
  }

  function setRows(container, nodes, emptyText) {
    container.textContent = "";
    if (!nodes.length) {
      container.appendChild(el("p", "empty", emptyText || "No data yet"));
      return;
    }
    nodes.forEach(function (n) {
      container.appendChild(n);
    });
  }

  // One "Could not load" line where the rows would be.
  function failRows(container, text) {
    container.textContent = "";
    container.appendChild(el("p", "empty", text));
  }

  // An inline line after `node` when a save fails; clearError removes it on the next success.
  function saveError(node) {
    var next = node.nextElementSibling;
    if (next && next.classList.contains("send-error")) return;
    var line = el("span", "send-error", "Could not save. Try again.");
    line.setAttribute("role", "alert");
    node.insertAdjacentElement("afterend", line);
  }

  function clearError(node) {
    var next = node.nextElementSibling;
    if (next && next.classList.contains("send-error")) next.remove();
  }

  function adjustWaiting(delta) {
    var v = document.querySelector("[data-tile=handoffs-waiting] .tile-value");
    if (!v) return;
    var n = parseInt(v.textContent, 10);
    if (!isNaN(n)) v.textContent = String(Math.max(0, n + delta));
  }

  function label(code) {
    var s = String(code || "").replace(/_/g, " ");
    return s.charAt(0).toUpperCase() + s.slice(1);
  }

  return {
    data: data,
    getJSON: function (url) {
      return request("GET", url);
    },
    postJSON: function (url, body) {
      return request("POST", url, body === undefined ? {} : body);
    },
    el: el,
    setRows: setRows,
    failRows: failRows,
    saveError: saveError,
    clearError: clearError,
    adjustWaiting: adjustWaiting,
    label: label,
  };
})();
