/* Animated hero background — solar + grid energy map (p5.js).
   A drifting parcel map where some parcels are solar farms (shimmering panel
   rows), connected through substations and transmission lines that carry
   power pulses toward a sun-lit horizon.

   Interactive: moving the cursor electrifies nearby lines and raises an arc
   from the closest substation; clicking an empty parcel builds a new solar
   farm that ties into the grid with a burst of power.

   The canvas itself keeps pointer-events:none so hero buttons stay clickable;
   interaction is tracked via document-level listeners. Falls back to the
   static SVG art when p5 is missing or reduced motion is preferred. */
(function () {
  var host = document.getElementById("gp-hero-canvas");
  if (!host || typeof p5 === "undefined") return;
  if (window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;

  var SKY = [127, 180, 238];   // grid blue
  var SUN = [255, 196, 92];    // solar amber

  new p5(function (s) {
    var W = 0, H = 0;
    var parcels = [], nodes = [], edges = [], pulses = [], bursts = [];
    var mx = -9999, my = -9999, mouseIn = false;

    function sizes() {
      W = host.clientWidth || 1200;
      H = host.clientHeight || 560;
    }

    function parcelCenter(p) {
      return {
        x: (p.a.x + p.b.x + p.c.x + p.d.x) / 4,
        y: (p.a.y + p.b.y + p.c.y + p.d.y) / 4,
      };
    }

    function nearestNode(x, y) {
      var best = null, bd = 1e9;
      for (var i = 0; i < nodes.length; i++) {
        var d = s.dist(x, y, nodes[i].x, nodes[i].y);
        if (d < bd) { bd = d; best = nodes[i]; }
      }
      return { node: best, d: bd };
    }

    function makeSolar(p) {
      p.solar = true;
      p.built = s.millis() / 1000;
    }

    function buildWorld() {
      parcels = []; nodes = []; edges = []; pulses = []; bursts = [];
      var cols = Math.max(8, Math.round(W / 150));
      var rows = Math.max(5, Math.round(H / 110));
      var gx = W / cols, gy = H / rows;
      var pts = [];
      for (var r = 0; r <= rows; r++) {
        pts[r] = [];
        for (var c = 0; c <= cols; c++) {
          pts[r][c] = {
            x: c * gx + (c > 0 && c < cols ? s.random(-gx * 0.2, gx * 0.2) : 0),
            y: r * gy + (r > 0 && r < rows ? s.random(-gy * 0.2, gy * 0.2) : 0),
          };
        }
      }
      for (var r2 = 0; r2 < rows; r2++) {
        for (var c2 = 0; c2 < cols; c2++) {
          if (s.random() < 0.85) {
            parcels.push({
              a: pts[r2][c2], b: pts[r2][c2 + 1], c: pts[r2 + 1][c2 + 1], d: pts[r2 + 1][c2],
              solar: false, built: 0, seed: s.random(1000),
            });
          }
        }
      }
      // substations
      var n = Math.max(9, Math.round(W / 150));
      for (var i = 0; i < n; i++) {
        nodes.push({ x: s.random(W * 0.04, W * 0.96), y: s.random(H * 0.14, H * 0.94) });
      }
      for (var j = 0; j < nodes.length; j++) {
        var ds = nodes
          .map(function (m, k) { return { k: k, d: s.dist(nodes[j].x, nodes[j].y, m.x, m.y) }; })
          .filter(function (o) { return o.k !== j; })
          .sort(function (a, b) { return a.d - b.d; });
        for (var e = 0; e < 2 && e < ds.length; e++) {
          var k2 = ds[e].k;
          var key = Math.min(j, k2) + "-" + Math.max(j, k2);
          if (!edges.some(function (ed) { return ed.key === key; })) {
            edges.push({ key: key, a: nodes[j], b: nodes[k2], len: ds[e].d });
          }
        }
      }
      // seed a few solar farms away from the headline (left half is text)
      var candidates = parcels.filter(function (p) {
        var cc = parcelCenter(p);
        return cc.x > W * 0.45 && cc.y > H * 0.1;
      });
      for (var f = 0; f < Math.min(4, candidates.length); f++) {
        var pick = candidates[Math.floor(s.random(candidates.length))];
        if (!pick.solar) makeSolar(pick);
      }
      // wire each solar farm to its nearest substation
      parcels.forEach(function (p) {
        if (!p.solar) return;
        var cc = parcelCenter(p);
        var nn = nearestNode(cc.x, cc.y);
        if (nn.node) edges.push({ key: "s" + p.seed, a: cc, b: nn.node, len: nn.d, feeder: true });
      });
    }

    function spawnPulse(edge) {
      var ed = edge || edges[Math.floor(s.random(edges.length))];
      if (!ed) return;
      pulses.push({ ed: ed, t: 0, speed: s.random(0.35, 0.7) / Math.max(ed.len / 130, 1), dir: ed.feeder ? 1 : (s.random() < 0.5 ? 1 : -1) });
    }

    // --- interaction (document-level so hero buttons stay clickable) ------
    function toLocal(ev) {
      var r = host.getBoundingClientRect();
      return { x: ev.clientX - r.left, y: ev.clientY - r.top, inside: ev.clientX >= r.left && ev.clientX <= r.right && ev.clientY >= r.top && ev.clientY <= r.bottom };
    }
    document.addEventListener("mousemove", function (ev) {
      var pt = toLocal(ev);
      mouseIn = pt.inside;
      mx = pt.x; my = pt.y;
    }, { passive: true });
    document.addEventListener("click", function (ev) {
      if (ev.target.closest("a,button,input,select,nav,header")) return;
      var pt = toLocal(ev);
      if (!pt.inside) return;
      // build a solar farm on the clicked parcel
      for (var i = 0; i < parcels.length; i++) {
        var p = parcels[i];
        var cc = parcelCenter(p);
        if (s.dist(pt.x, pt.y, cc.x, cc.y) < 70 && !p.solar) {
          makeSolar(p);
          var nn = nearestNode(cc.x, cc.y);
          if (nn.node) {
            var ed = { key: "s" + p.seed, a: cc, b: nn.node, len: nn.d, feeder: true };
            edges.push(ed);
            for (var b = 0; b < 5; b++) setTimeout(spawnPulse.bind(null, ed), b * 160);
          }
          bursts.push({ x: cc.x, y: cc.y, t0: s.millis() / 1000 });
          return;
        }
      }
      bursts.push({ x: pt.x, y: pt.y, t0: s.millis() / 1000 });
    });

    // --- drawing helpers ---------------------------------------------------
    function drawPanels(p, t) {
      // rows of solar panels inside the parcel (interpolated between edges)
      var age = t - p.built;
      var grow = p.built === 0 ? 1 : Math.min(age / 0.9, 1);
      var rowsN = 5;
      for (var i = 1; i <= rowsN * grow; i++) {
        var f = i / (rowsN + 1);
        var x1 = s.lerp(p.a.x, p.d.x, f), y1 = s.lerp(p.a.y, p.d.y, f);
        var x2 = s.lerp(p.b.x, p.c.x, f), y2 = s.lerp(p.b.y, p.c.y, f);
        // shimmer: sun glint sweeping across rows
        var glint = 0.5 + 0.5 * Math.sin(t * 1.6 + p.seed + i * 0.9);
        s.stroke(SUN[0], SUN[1], SUN[2], 60 + 110 * glint);
        s.strokeWeight(2.2);
        var inset = 0.08;
        s.line(s.lerp(x1, x2, inset), s.lerp(y1, y2, inset), s.lerp(x1, x2, 1 - inset), s.lerp(y1, y2, 1 - inset));
      }
      s.noFill();
      s.stroke(SUN[0], SUN[1], SUN[2], 130);
      s.strokeWeight(1.3);
      s.quad(p.a.x, p.a.y, p.b.x, p.b.y, p.c.x, p.c.y, p.d.x, p.d.y);
    }

    function drawArc(x1, y1, x2, y2, alpha) {
      // jagged electric arc
      s.noFill();
      s.stroke(255, 255, 255, alpha);
      s.strokeWeight(1.4);
      s.beginShape();
      s.vertex(x1, y1);
      var segs = 7;
      for (var i = 1; i < segs; i++) {
        var f = i / segs;
        var nx = s.lerp(x1, x2, f) + s.random(-7, 7);
        var ny = s.lerp(y1, y2, f) + s.random(-7, 7);
        s.vertex(nx, ny);
      }
      s.vertex(x2, y2);
      s.endShape();
    }

    s.setup = function () {
      sizes();
      var cnv = s.createCanvas(W, H);
      cnv.parent(host);
      s.pixelDensity(Math.min(window.devicePixelRatio || 1, 2));
      s.frameRate(50);
      buildWorld();
      if ("IntersectionObserver" in window) {
        new IntersectionObserver(function (entries) {
          if (entries[0].isIntersecting) s.loop(); else s.noLoop();
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
      var dx = Math.sin(t * 0.07) * 10;
      var dy = Math.cos(t * 0.05) * 6;
      s.push();
      s.translate(dx, dy);
      var lmx = mx - dx, lmy = my - dy;

      // --- sun: glow + slowly rotating rays (top right, away from headline)
      var sx = W * 0.86, sy = H * 0.12;
      for (var g = 5; g >= 1; g--) {
        s.noStroke();
        s.fill(SUN[0], SUN[1], SUN[2], 9 * g);
        s.circle(sx, sy, 30 + g * 34);
      }
      s.stroke(SUN[0], SUN[1], SUN[2], 110);
      s.strokeWeight(1.5);
      for (var ray = 0; ray < 10; ray++) {
        var ang = t * 0.15 + (ray * s.TWO_PI) / 10;
        var r1 = 42 + 4 * Math.sin(t * 2 + ray);
        var r2 = r1 + 14;
        s.line(sx + Math.cos(ang) * r1, sy + Math.sin(ang) * r1, sx + Math.cos(ang) * r2, sy + Math.sin(ang) * r2);
      }
      s.fill(SUN[0], SUN[1], SUN[2], 200);
      s.noStroke();
      s.circle(sx, sy, 26);

      // --- parcels
      s.noFill();
      for (var i = 0; i < parcels.length; i++) {
        var p = parcels[i];
        var cc = parcelCenter(p);
        var md = mouseIn ? s.dist(lmx, lmy, cc.x, cc.y) : 1e9;
        var hover = Math.max(0, 1 - md / 160);
        s.stroke(255, 255, 255, 26 + 70 * hover);
        s.strokeWeight(1);
        s.quad(p.a.x, p.a.y, p.b.x, p.b.y, p.c.x, p.c.y, p.d.x, p.d.y);
        if (hover > 0.4 && !p.solar) {
          s.fill(SKY[0], SKY[1], SKY[2], 26 * hover);
          s.quad(p.a.x, p.a.y, p.b.x, p.b.y, p.c.x, p.c.y, p.d.x, p.d.y);
          s.noFill();
        }
        if (p.solar) drawPanels(p, t);
      }

      // --- transmission lines (brighten near cursor)
      for (var e = 0; e < edges.length; e++) {
        var ed = edges[e];
        var mxd = mouseIn
          ? Math.min(s.dist(lmx, lmy, ed.a.x, ed.a.y), s.dist(lmx, lmy, ed.b.x, ed.b.y), s.dist(lmx, lmy, (ed.a.x + ed.b.x) / 2, (ed.a.y + ed.b.y) / 2))
          : 1e9;
        var boost = Math.max(0, 1 - mxd / 220);
        s.stroke(SKY[0], SKY[1], SKY[2], (ed.feeder ? 90 : 70) + 120 * boost);
        s.strokeWeight(1.1 + boost);
        s.line(ed.a.x, ed.a.y, ed.b.x, ed.b.y);
      }

      // --- substations: small squares with pulse rings
      for (var nn2 = 0; nn2 < nodes.length; nn2++) {
        var nd = nodes[nn2];
        var ring = (t * 0.55 + nn2 * 0.37) % 1;
        s.noFill();
        s.stroke(SKY[0], SKY[1], SKY[2], 90 * (1 - ring));
        s.strokeWeight(1);
        s.circle(nd.x, nd.y, 6 + ring * 26);
        s.fill(230, 242, 255, 235);
        s.noStroke();
        s.rectMode(s.CENTER);
        s.rect(nd.x, nd.y, 6, 6, 1);
      }

      // --- electric arc from nearest substation to cursor
      if (mouseIn) {
        var near = nearestNode(lmx, lmy);
        if (near.node && near.d < 190) {
          var a2 = 150 * (1 - near.d / 190);
          if (s.random() < 0.75) drawArc(near.node.x, near.node.y, lmx, lmy, a2);
          s.noStroke();
          s.fill(255, 255, 255, a2);
          s.circle(lmx, lmy, 3.5);
        }
      }

      // --- power pulses
      if (s.random() < 0.14 && pulses.length < 26) spawnPulse();
      for (var q = pulses.length - 1; q >= 0; q--) {
        var pu = pulses[q];
        pu.t += pu.speed * (s.deltaTime / 1000);
        if (pu.t >= 1) { pulses.splice(q, 1); continue; }
        var tt = pu.dir === 1 ? pu.t : 1 - pu.t;
        var x = s.lerp(pu.ed.a.x, pu.ed.b.x, tt);
        var y = s.lerp(pu.ed.a.y, pu.ed.b.y, tt);
        var fade = Math.sin(pu.t * Math.PI);
        // trail
        for (var tr = 1; tr <= 3; tr++) {
          var tb = Math.max(0, tt - tr * 0.03 * pu.dir);
          s.noStroke();
          s.fill(SKY[0], SKY[1], SKY[2], 60 * fade / tr);
          s.circle(s.lerp(pu.ed.a.x, pu.ed.b.x, tb), s.lerp(pu.ed.a.y, pu.ed.b.y, tb), 5 - tr);
        }
        s.fill(255, 255, 255, 230 * fade);
        s.circle(x, y, 3.4);
        s.fill(SKY[0], SKY[1], SKY[2], 80 * fade);
        s.circle(x, y, 11);
      }

      // --- click bursts
      for (var bb = bursts.length - 1; bb >= 0; bb--) {
        var bu = bursts[bb];
        var ba = t - bu.t0;
        if (ba > 0.9) { bursts.splice(bb, 1); continue; }
        var bf = 1 - ba / 0.9;
        s.noFill();
        s.stroke(SUN[0], SUN[1], SUN[2], 190 * bf);
        s.strokeWeight(1.6);
        s.circle(bu.x, bu.y, ba * 130);
        s.stroke(255, 255, 255, 120 * bf);
        s.circle(bu.x, bu.y, ba * 70);
      }
      s.pop();
    };
  });
})();
