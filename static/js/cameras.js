/* cameras.js — RIFT fleet camera wall.
 *
 * One tile per robot in the live roster (/fleet, falling back to /robots).
 * A robot's camera stream URL comes from, in order:
 *   1. a per-robot override you set here (kept in this browser), or
 *   2. a "camera..." entry in the robot's advertised capabilities:
 *        "camera:<port>/<path>"   -> http://<ip>:<port>/<path>
 *        "camera:<path>"          -> http://<ip>:<path>
 *        "camera:http://host..."  -> used as-is
 *        "camera"                 -> http://<ip>:81/stream  (ESP32-CAM default)
 * No camera found -> a clear "NO CAMERA" placeholder, so the wall is honest
 * and fills in as cameras come online. MJPEG loads in a plain <img>, which is
 * not blocked cross-origin.
 */
(function () {
  "use strict";

  var grid = document.getElementById("camGrid");
  var meta = document.getElementById("camMeta");
  var empty = document.getElementById("empty");
  var tiles = {};                  // name -> { el, img, src }
  var LS_KEY = "rift.cam.overrides";

  function overrides() {
    try { return JSON.parse(localStorage.getItem(LS_KEY) || "{}"); } catch (e) { return {}; }
  }
  function saveOverride(name, url) {
    var o = overrides();
    if (url) o[name] = url; else delete o[name];
    try { localStorage.setItem(LS_KEY, JSON.stringify(o)); } catch (e) {}
  }

  function camUrlFor(robot) {
    var ov = overrides()[robot.name];
    if (ov) return ov;
    var caps = robot.capabilities || [];
    for (var i = 0; i < caps.length; i++) {
      var c = String(caps[i]);
      if (c.toLowerCase().indexOf("camera") !== 0) continue;
      var rest = c.slice(6).replace(/^[:\s]+/, "");   // after "camera"
      if (!rest) return "http://" + robot.ip + ":81/stream";
      if (/^https?:\/\//i.test(rest)) return rest;
      if (rest[0] === "/") return "http://" + robot.ip + rest;
      return "http://" + robot.ip + ":" + rest;        // "<port>/<path>" or "<port>"
    }
    return null;
  }

  function tile(robot) {
    var el = document.createElement("div");
    el.className = "cam off";
    el.innerHTML =
      '<div class="bar">' +
        '<span class="dot"></span>' +
        '<span class="name"></span>' +
        '<button class="gear" title="Set camera source">&#9881;</button>' +
        '<span class="type"></span>' +
      '</div>' +
      '<div class="view">' +
        '<img alt="">' +
        '<div class="ph"><span class="big">&#128247;</span>NO CAMERA</div>' +
      '</div>' +
      '<div class="src"></div>';
    el.querySelector(".name").textContent = robot.name;
    el.querySelector(".type").textContent = robot.type || "robot";
    el.querySelector(".gear").addEventListener("click", function (e) {
      e.stopPropagation();
      var cur = overrides()[robot.name] || "";
      var next = window.prompt(
        "Camera stream URL for " + robot.name + "\n(an MJPEG / snapshot URL; blank to clear override)", cur);
      if (next === null) return;
      saveOverride(robot.name, next.trim());
      apply(robot);
    });
    el.querySelector(".view").addEventListener("click", function () {
      var img = el.querySelector("img");
      if (el.classList.contains("live") && img.requestFullscreen) img.requestFullscreen();
    });
    grid.appendChild(el);
    var rec = { el: el, img: el.querySelector("img"), src: null };
    rec.img.addEventListener("error", function () { setOff(robot.name); });
    rec.img.addEventListener("load", function () { setLive(robot.name); });
    tiles[robot.name] = rec;
    return rec;
  }

  function setLive(name) { var t = tiles[name]; if (t) { t.el.classList.remove("off"); t.el.classList.add("live"); } }
  function setOff(name)  { var t = tiles[name]; if (t) { t.el.classList.remove("live"); t.el.classList.add("off"); } }

  function apply(robot) {
    var rec = tiles[robot.name] || tile(robot);
    rec.el.querySelector(".type").textContent = robot.type || "robot";
    var url = camUrlFor(robot);
    var srcLine = rec.el.querySelector(".src");
    if (!url) {
      rec.src = null; rec.img.removeAttribute("src"); setOff(robot.name);
      srcLine.textContent = "no camera advertised — set one with ⚙";
      return;
    }
    // cache-bust so a reconnect actually re-requests the stream
    var bust = url + (url.indexOf("?") < 0 ? "?" : "&") + "_t=" + Date.now();
    if (rec.src !== url) { rec.src = url; rec.img.src = bust; }
    srcLine.textContent = url;
  }

  function render(robots) {
    var seen = {};
    robots.forEach(function (r) { seen[r.name] = true; apply(r); });
    // drop tiles for robots that left
    Object.keys(tiles).forEach(function (name) {
      if (!seen[name]) { tiles[name].el.remove(); delete tiles[name]; }
    });
    var n = robots.length;
    empty.style.display = n ? "none" : "block";
    var live = Object.keys(tiles).filter(function (k) { return tiles[k].el.classList.contains("live"); }).length;
    meta.textContent = n + (n === 1 ? " robot" : " robots") + " · " + live + " live";
  }

  function poll() {
    fetch("/fleet")
      .then(function (r) { return r.ok ? r.json() : fetch("/robots").then(function (r2) { return r2.json(); }); })
      .then(function (d) { render((d && d.robots) || []); })
      .catch(function () { meta.textContent = "fleet unreachable"; });
  }

  poll();
  setInterval(poll, 10000);
})();
