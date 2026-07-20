/* Animated hero background — map-style parcel grid + energy network (p5.js).
   Draws over the hero's navy gradient: drifting parcel outlines, a transmission
   node graph, pulses traveling along lines, and parcels that periodically
   highlight like a site selection. Falls back to the static SVG when p5 is
   unavailable or the user prefers reduced motion. */
(function () {
  var host = document.getElementById("gp-hero-canvas");
  if (!host || typeof p5 === "undefined") return;
  if (window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;

  var SKY = [127, 180, 238];

  new p5(function (s) {
    var W = 0, H = 0;
    var nodes = [], edges = [], pulses = [], parcels = [];
    var highlight = null;
    var running = true;

    function sizes() {
      W = host.clientWidth || 1200;
      H = host.clientHeight || 560;
    }

    function buildWorld() {
      nodes = []; edges = []; pulses = []; parcels = [];
      // --- parcel grid (map feel): irregular quads on a jittered lattice
      var cols = Math.max(8, Math.round(W / 150));
      var rows = Math.max(5, Math.round(H / 110));
      var gx = W / cols, gy = H / rows;
      var pts = [];
      for (var r = 0; r <= rows; r++) {
        pts[r] = [];
        for (var c = 0; c <= cols; c++) {
          pts[r][c] = {
            x: c * gx + (c > 0 && c < cols ? s.random(-gx * 0.22, gx * 0.22) : 0),
            y: r * gy + (r > 0 && r < rows ? s.random(-gy * 0.22, gy * 0.22) : 0),
          };
        }
      }
      for (var r2 = 0; r2 < rows; r2++) {
        for (var c2 = 0; c2 < cols; c2++) {
          if (s.random() < 0.82) {
            parcels.push({
              a: pts[r2][c2], b: pts[r2][c2 + 1], c: pts[r2 + 1][c2 + 1], d: pts[r2 + 1][c2],
              base: s.random(0.03, 0.075),
            });
          }
        }
      }
      // --- transmission network: sparse nodes, each linked to 2 nearest
      var n = Math.max(10, Math.round(W / 110));
      for (var i = 0; i < n; i++) {
        nodes.push({ x: s.random(W * 0.03, W * 0.97), y: s.random(H * 0.12, H * 0.95), r: s.random(2, 3.2) });
      }
      for (var j = 0; j < nodes.length; j++) {
        var dists = nodes
          .map(function (m, k) { return { k: k, d: s.dist(nodes[j].x, nodes[j].y, m.x, m.y) }; })
          .filter(function (o) { return o.k !== j; })
          .sort(function (a, b) { return a.d - b.d; });
        for (var e = 0; e < 2 && e < dists.length; e++) {
          var k2 = dists[e].k;
          var key = Math.min(j, k2) + "-" + Math.max(j, k2);
          if (!edges.some(function (ed) { return ed.key === key; })) {
            edges.push({ key: key, a: nodes[j], b: nodes[k2], len: dists[e].d });
          }
        }
      }
    }

    function spawnPulse() {
      if (!edges.length) return;
      var ed = edges[Math.floor(s.random(edges.length))];
      pulses.push({ ed: ed, t: 0, speed: s.random(0.28, 0.55) / Math.max(ed.len / 120, 1), dir: s.random() < 0.5 ? 1 : -1 });
    }

    s.setup = function () {
      sizes();
      var cnv = s.createCanvas(W, H);
      cnv.parent(host);
      s.pixelDensity(Math.min(window.devicePixelRatio || 1, 2));
      s.frameRate(45);
      buildWorld();
      // pause offscreen — the hero scrolls away quickly
      if ("IntersectionObserver" in window) {
        new IntersectionObserver(function (entries) {
          running = entries[0].isIntersecting;
          if (running) s.loop(); else s.noLoop();
        }).observe(host);
      }
      var art = document.getElementById("gp-hero-art");
      if (art) art.style.display = "none";
    };

    s.windowResized = function () {
      sizes();
      s.resizeCanvas(W, H);
      buildWorld();
    };

    s.draw = function () {
      s.clear();
      var t = s.millis() / 1000;
      // slow map drift
      var dx = Math.sin(t * 0.08) * 14 + Math.cos(t * 0.031) * 6;
      var dy = Math.cos(t * 0.06) * 8;
      s.push();
      s.translate(dx, dy);

      // parcels
      s.noFill();
      for (var i = 0; i < parcels.length; i++) {
        var p = parcels[i];
        s.stroke(255, 255, 255, p.base * 255);
        s.strokeWeight(1);
        s.quad(p.a.x, p.a.y, p.b.x, p.b.y, p.c.x, p.c.y, p.d.x, p.d.y);
      }

      // parcel highlight cycle (site selection feel)
      if (!highlight && s.random() < 0.008 && parcels.length) {
        highlight = { p: parcels[Math.floor(s.random(parcels.length))], t0: t };
      }
      if (highlight) {
        var age = t - highlight.t0;
        var a = age < 0.8 ? age / 0.8 : age < 3.2 ? 1 : 1 - (age - 3.2) / 1.2;
        if (age > 4.4) highlight = null;
        else {
          var hp = highlight.p;
          s.fill(SKY[0], SKY[1], SKY[2], 26 * a);
          s.stroke(SKY[0], SKY[1], SKY[2], 140 * a);
          s.strokeWeight(1.2);
          s.quad(hp.a.x, hp.a.y, hp.b.x, hp.b.y, hp.c.x, hp.c.y, hp.d.x, hp.d.y);
          s.noFill();
        }
      }

      // transmission lines
      for (var e = 0; e < edges.length; e++) {
        var ed = edges[e];
        s.stroke(SKY[0], SKY[1], SKY[2], 46);
        s.strokeWeight(1);
        s.line(ed.a.x, ed.a.y, ed.b.x, ed.b.y);
      }

      // nodes
      s.noStroke();
      for (var nn = 0; nn < nodes.length; nn++) {
        var nd = nodes[nn];
        var tw = 0.6 + 0.4 * Math.sin(t * 1.4 + nn * 1.7);
        s.fill(SKY[0], SKY[1], SKY[2], 120 * tw);
        s.circle(nd.x, nd.y, nd.r * 2);
      }

      // pulses along lines
      if (s.random() < 0.06 && pulses.length < 14) spawnPulse();
      for (var q = pulses.length - 1; q >= 0; q--) {
        var pu = pulses[q];
        pu.t += pu.speed * (s.deltaTime / 1000) * 60 * 0.016;
        if (pu.t >= 1) { pulses.splice(q, 1); continue; }
        var tt = pu.dir === 1 ? pu.t : 1 - pu.t;
        var x = s.lerp(pu.ed.a.x, pu.ed.b.x, tt);
        var y = s.lerp(pu.ed.a.y, pu.ed.b.y, tt);
        var fade = Math.sin(pu.t * Math.PI);
        s.fill(255, 255, 255, 190 * fade);
        s.circle(x, y, 2.6);
        s.fill(SKY[0], SKY[1], SKY[2], 60 * fade);
        s.circle(x, y, 9);
      }
      s.pop();
    };
  });
})();
