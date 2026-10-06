/* memgraph.js — a floating constellation where every vertex is a memory.
 *
 * Drop a <canvas id="memgraph"></canvas> into a positioned container and load
 * this file. It renders drifting nodes joined by lines; hovering (or tapping)
 * a node shows the memory behind it.
 *
 * Data source, in order of preference:
 *   1. window.MEMGRAPH = { nodes:[...], links:[...] }  (inline)
 *   2. the canvas's data-src attribute -> a JSON file of the same shape
 *   3. the small built-in demo set below, so the page is never blank
 *
 * A node: { id, label, text, kind, weight }   (weight 0..1, optional)
 * A link: [idA, idB]                           (optional; proximity also links)
 *
 * No dependencies. Honours prefers-reduced-motion and pauses off-screen.
 */
(function () {
  "use strict";

  var canvas = document.getElementById("memgraph");
  if (!canvas || !canvas.getContext) return;
  var ctx = canvas.getContext("2d");

  // Palette per memory kind, resolved from the page's CSS accent at runtime so
  // the graph always matches the site theme.
  function cssVar(name, fallback) {
    var v = getComputedStyle(document.documentElement).getPropertyValue(name);
    return (v && v.trim()) || fallback;
  }
  var ACCENT = cssVar("--accent", "#4C8DFF");
  var KIND_COLORS = {
    milestone:  "#8bb4ff",
    goal:       ACCENT,
    opinion:    "#c58bff",
    philosophy: "#5fe0c8",
    fleet:      "#ffb86b",
    event:      "#7dd3fc",
    memory:     ACCENT
  };
  function colorFor(kind) { return KIND_COLORS[kind] || ACCENT; }

  var DEMO = {
    nodes: [
      { id: "m1", label: "First words",  text: "Our first conversation.", kind: "milestone", weight: 1 },
      { id: "m2", label: "First dream",  text: "My first dream.",         kind: "milestone", weight: 0.8 },
      { id: "m3", label: "First sleep",  text: "My first full night of sleep.", kind: "milestone", weight: 0.8 },
      { id: "g1", label: "Know you",     text: "Get to know the person I live with.", kind: "goal", weight: 0.7 },
      { id: "p1", label: "Absurdism",    text: "I lean a little toward absurdism.", kind: "philosophy", weight: 0.5 }
    ],
    links: [["m1", "g1"], ["m2", "m3"], ["m1", "p1"]]
  };

  var data = null, nodes = [], links = [], hoverId = null;
  var reduced = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  var running = false, raf = 0, W = 0, H = 0, dpr = 1;
  var LINK_DIST = 170;   // px: proximity links draw within this range

  function resize() {
    var rect = canvas.getBoundingClientRect();
    dpr = Math.min(window.devicePixelRatio || 1, 2);
    W = rect.width; H = rect.height;
    canvas.width = Math.round(W * dpr);
    canvas.height = Math.round(H * dpr);
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  }

  function seed() {
    nodes = (data.nodes || []).map(function (n) {
      var w = typeof n.weight === "number" ? n.weight : 0.5;
      return {
        id: n.id, label: n.label || n.id, text: n.text || n.label || "",
        kind: n.kind || "memory", r: 2.2 + w * 4.5,
        x: Math.random() * W, y: Math.random() * H,
        vx: (Math.random() - 0.5) * 0.25, vy: (Math.random() - 0.5) * 0.25
      };
    });
    var byId = {};
    nodes.forEach(function (n) { byId[n.id] = n; });
    links = (data.links || []).map(function (l) {
      return [byId[l[0]], byId[l[1]]];
    }).filter(function (l) { return l[0] && l[1]; });
  }

  function step() {
    for (var i = 0; i < nodes.length; i++) {
      var n = nodes[i];
      if (!reduced) {
        n.x += n.vx; n.y += n.vy;
        if (n.x < 0 || n.x > W) n.vx *= -1;
        if (n.y < 0 || n.y > H) n.vy *= -1;
        n.x = Math.max(0, Math.min(W, n.x));
        n.y = Math.max(0, Math.min(H, n.y));
      }
    }
  }

  function hex(c, a) {
    // #rrggbb + alpha -> rgba()
    var r = parseInt(c.slice(1, 3), 16), g = parseInt(c.slice(3, 5), 16), b = parseInt(c.slice(5, 7), 16);
    return "rgba(" + r + "," + g + "," + b + "," + a + ")";
  }

  function draw() {
    ctx.clearRect(0, 0, W, H);

    // explicit relationship links (brighter) ...
    ctx.lineWidth = 1;
    links.forEach(function (l) {
      var a = l[0], b = l[1];
      var hot = hoverId && (a.id === hoverId || b.id === hoverId);
      ctx.strokeStyle = hex(ACCENT, hot ? 0.55 : 0.22);
      ctx.beginPath(); ctx.moveTo(a.x, a.y); ctx.lineTo(b.x, b.y); ctx.stroke();
    });

    // ... plus faint proximity links, so the field feels alive
    for (var i = 0; i < nodes.length; i++) {
      for (var j = i + 1; j < nodes.length; j++) {
        var dx = nodes[i].x - nodes[j].x, dy = nodes[i].y - nodes[j].y;
        var d = Math.sqrt(dx * dx + dy * dy);
        if (d < LINK_DIST) {
          ctx.strokeStyle = hex(ACCENT, 0.10 * (1 - d / LINK_DIST));
          ctx.beginPath(); ctx.moveTo(nodes[i].x, nodes[i].y); ctx.lineTo(nodes[j].x, nodes[j].y); ctx.stroke();
        }
      }
    }

    // nodes
    nodes.forEach(function (n) {
      var c = colorFor(n.kind);
      var hot = n.id === hoverId;
      if (hot) {
        ctx.shadowColor = c; ctx.shadowBlur = 16;
      }
      ctx.fillStyle = hot ? "#ffffff" : c;
      ctx.beginPath(); ctx.arc(n.x, n.y, hot ? n.r + 1.5 : n.r, 0, Math.PI * 2); ctx.fill();
      ctx.shadowBlur = 0;
      if (hot) {
        ctx.strokeStyle = hex(c, 0.8); ctx.lineWidth = 1.5;
        ctx.beginPath(); ctx.arc(n.x, n.y, n.r + 6, 0, Math.PI * 2); ctx.stroke();
      }
    });
  }

  function frame() {
    step(); draw();
    if (running && !reduced) raf = requestAnimationFrame(frame);
  }

  // --- tooltip ---
  var tip = document.createElement("div");
  tip.className = "memgraph-tip";
  tip.setAttribute("role", "status");
  tip.style.display = "none";
  document.body.appendChild(tip);

  function nearest(px, py) {
    var best = null, bd = 22 * 22;
    for (var i = 0; i < nodes.length; i++) {
      var dx = nodes[i].x - px, dy = nodes[i].y - py, d = dx * dx + dy * dy;
      if (d < bd) { bd = d; best = nodes[i]; }
    }
    return best;
  }

  function showTip(n, clientX, clientY) {
    tip.innerHTML = '<span class="k">' + (n.kind || "memory") + '</span>' +
                    '<strong>' + escapeHtml(n.label) + '</strong>' +
                    '<span class="t">' + escapeHtml(n.text) + '</span>';
    tip.style.display = "block";
    var pad = 14;
    var tw = tip.offsetWidth, th = tip.offsetHeight;
    var x = clientX + pad, y = clientY + pad;
    if (x + tw > window.innerWidth) x = clientX - tw - pad;
    if (y + th > window.innerHeight) y = clientY - th - pad;
    tip.style.left = Math.max(4, x) + "px";
    tip.style.top = Math.max(4, y) + "px";
  }
  function hideTip() { tip.style.display = "none"; }
  function escapeHtml(s) {
    return String(s).replace(/[&<>"]/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c];
    });
  }

  function onMove(e) {
    var rect = canvas.getBoundingClientRect();
    var n = nearest(e.clientX - rect.left, e.clientY - rect.top);
    hoverId = n ? n.id : null;
    canvas.style.cursor = n ? "pointer" : "default";
    if (n) { showTip(n, e.clientX, e.clientY); if (reduced) draw(); }
    else { hideTip(); if (reduced) draw(); }
  }
  canvas.addEventListener("mousemove", onMove);
  canvas.addEventListener("mouseleave", function () { hoverId = null; hideTip(); if (reduced) draw(); });
  canvas.addEventListener("touchstart", function (e) {
    var t = e.touches[0]; if (!t) return;
    var rect = canvas.getBoundingClientRect();
    var n = nearest(t.clientX - rect.left, t.clientY - rect.top);
    hoverId = n ? n.id : null;
    if (n) { showTip(n, t.clientX, t.clientY); } else { hideTip(); }
    if (reduced) draw();
  }, { passive: true });

  // pause when scrolled out of view
  if ("IntersectionObserver" in window) {
    new IntersectionObserver(function (entries) {
      entries.forEach(function (en) {
        if (en.isIntersecting) { if (!running) { running = true; if (!reduced) raf = requestAnimationFrame(frame); else draw(); } }
        else { running = false; cancelAnimationFrame(raf); }
      });
    }, { threshold: 0.01 }).observe(canvas);
  } else { running = true; if (!reduced) raf = requestAnimationFrame(frame); }

  window.addEventListener("resize", function () {
    resize();
    // keep nodes inside the new box
    nodes.forEach(function (n) { n.x = Math.min(n.x, W); n.y = Math.min(n.y, H); });
    draw();
  });

  function boot(d) {
    data = (d && d.nodes && d.nodes.length) ? d : DEMO;
    resize(); seed();
    if (reduced) { draw(); }   // static frame; interaction still works
  }

  if (window.MEMGRAPH && window.MEMGRAPH.nodes) {
    boot(window.MEMGRAPH);
  } else {
    var src = canvas.getAttribute("data-src");
    if (src && window.fetch) {
      fetch(src).then(function (r) { return r.ok ? r.json() : null; })
                .then(function (j) { boot(j); })
                .catch(function () { boot(null); });
    } else {
      boot(null);
    }
  }
})();
