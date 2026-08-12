"""Writing the standalone three.js browser preview.

OpenSpace needs OpenGL 4.6; macOS stops at 4.1.  This module renders the same
geometry the .asset files describe -- same positions, same radii, same
exaggeration, same textures -- in WebGL, so the scene can be checked on a
machine that cannot run OpenSpace.

The output is one self-contained HTML file that loads three.js from a CDN
import map.  No build step, no bundler, so it works on GitHub Pages as-is.
"""

import json

from .assets import spin_axis_vector
from .io import PARSEC_M, RSUN_M
from .texture import COLORMAP, PROT_COLORMAP, colormap_rgb, colormap_stops

# three.js from a CDN, pinned.  An import map keeps `import ... from "three"`
# working in a plain <script type="module"> with no bundler involved.
THREE_VERSION = "0.160.0"


def build_scene_data(entries, all_targets, exaggeration):
    """Assemble the JSON payload the page needs.

    `entries` are (target, texture filename, vmax) for stars that have a map;
    `all_targets` is every unique star, mapped or not, for the point cloud.
    """
    textured = {(t["star"], t["epoch"]): (png, vmax) for t, png, vmax in entries}
    rsun_pc = RSUN_M / PARSEC_M          # 1 solar radius, in parsecs

    # Point-cloud colour by rotation period, matching prot.cmap in the .speck
    # build so the two renderers agree on what a colour means.
    periods = [t["prot_d"] for t in all_targets if t["prot_d"] is not None]
    p_lo, p_hi = (min(periods), max(periods)) if periods else (0.0, 1.0)
    prot_ramp = colormap_rgb(PROT_COLORMAP, 64)

    def prot_color(p):
        if p is None or p_hi == p_lo:
            return "#8899aa"
        f = (p - p_lo) / (p_hi - p_lo)
        r, g, b = prot_ramp[min(63, max(0, int(f * 63)))]
        return "#%02x%02x%02x" % (int(r * 255), int(g * 255), int(b * 255))

    stars = []
    for t in all_targets:
        # A star may have several epochs; expose each mapped epoch separately.
        epochs = [(s, e) for (s, e) in textured if s == t["star"]] or [(t["star"], None)]
        for _, epoch in sorted(epochs, key=lambda k: k[1] or ""):
            png, vmax = textured.get((t["star"], epoch), (None, None))
            axis, _ = spin_axis_vector(t["ra_deg"], t["dec_deg"],
                                       t["inclination_deg"] or 90.0)
            stars.append({
                "name": t["name"],
                "epoch": epoch,
                "pos": [t["x_pc"], t["y_pc"], t["z_pc"]],
                "axis": [float(v) for v in axis],
                "radiusPc": t["radius_rsun"] * rsun_pc * exaggeration,
                "radiusRsun": t["radius_rsun"],
                "distPc": t["dist_pc"],
                "prot": t["prot_d"],
                "incl": t["inclination_deg"],
                "teff": t["teff_k"],
                "texture": f"textures/{png}" if png else None,
                "vmax": vmax,
                "color": prot_color(t["prot_d"]),
            })

    # Mapped stars first -- the list should lead with the objects that carry
    # data -- then by catalogue number, sorted numerically rather than as text
    # so 68 and 95 do not land after 587.
    def order(s):
        num = s["name"].rsplit(" ", 1)[-1]
        return (s["texture"] is None,
                int(num) if num.isdigit() else 1 << 30,
                s["epoch"] or "")
    stars.sort(key=order)
    return {
        "stars": stars,
        "exaggeration": exaggeration,
        "colormap": COLORMAP,
        "stops": colormap_stops(24),
        "protRange": [p_lo, p_hi],
    }


def write_preview(entries, all_targets, path, exaggeration):
    """Write `index.html`."""
    data = build_scene_data(entries, all_targets, exaggeration)
    html = (_TEMPLATE
            .replace("__THREE_VERSION__", THREE_VERSION)
            .replace("__SCENE_DATA__", json.dumps(data, indent=None)))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html)
    return path


# ---------------------------------------------------------------------------
# The page itself.  Kept as one template string so the generated file is a
# single self-contained artefact; the only substitutions are the version pin
# and the scene JSON.
# ---------------------------------------------------------------------------

_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>ZDI &middot; Hyades surface maps</title>
<style>
  /* Palette taken from the subject: the diverging polarity scale, blue for
     field into the surface and red for field out of it, over a deep blue-black
     rather than pure black. Type is monospaced throughout -- the vernacular of
     observing logs. */
  :root {
    --bg:        #060a14;
    --panel:     rgba(10, 15, 28, 0.9);
    --line:      #22304c;
    --ink:       #d7e0ee;
    --ink-dim:   #8b9cbb;
    --inward:    #5580c4;
    --outward:   #cf5548;
    --focus:     #8db2e8;
    --mono: ui-monospace, "SF Mono", SFMono-Regular, Menlo, Consolas, monospace;
  }
  * { box-sizing: border-box; }
  html, body { height: 100%; margin: 0; }
  body {
    background: var(--bg);
    color: var(--ink);
    font: 14.5px/1.6 var(--mono);
    overflow: hidden;
    -webkit-font-smoothing: antialiased;
  }
  canvas { display: block; }
  #view { position: fixed; inset: 0; }

  /* --- shared panel treatment --- */
  .panel {
    background: var(--panel);
    border: 1px solid var(--line);
    backdrop-filter: blur(10px);
    box-shadow: 0 12px 32px rgba(0, 0, 0, 0.45);
  }

  /* One flex column on the left, so the target list takes exactly the space
     the masthead and readout leave it and nothing can overlap. */
  #rail {
    position: fixed; top: 16px; left: 16px; bottom: 16px; width: 388px;
    display: flex; flex-direction: column; gap: 10px;
  }

  /* --- masthead --- */
  #head { flex: 0 0 auto; padding: 14px 18px; }
  #head h1 {
    margin: 0 0 8px; font-size: 15px; font-weight: 700;
    letter-spacing: 0.1em; text-transform: uppercase;
  }
  #head p { margin: 0; color: var(--ink-dim); font-size: 13px; }
  .warn {
    margin-top: 10px; padding-top: 10px; border-top: 1px solid var(--line);
    color: var(--ink); font-size: 13px;
  }
  .warn b { color: var(--outward); font-weight: 700; }
  #protowarn {
    display: none; position: fixed; top: 16px; left: 50%;
    transform: translateX(-50%); z-index: 10; max-width: 560px;
    padding: 10px 16px; text-align: center;
    background: rgba(30, 14, 14, 0.92); border: 1px solid var(--outward);
    color: var(--ink);
  }
  #protowarn code {
    background: rgba(255, 255, 255, 0.08); padding: 0 4px; color: var(--ink);
  }
  #wide {
    display: block; width: 100%; margin-top: 12px; padding: 9px;
    background: none; border: 1px solid var(--line); color: var(--ink);
    font: inherit; font-size: 13px; cursor: pointer; letter-spacing: 0.08em;
  }
  #wide:hover { background: rgba(141, 178, 232, 0.1); border-color: var(--focus); }
  kbd {
    font: inherit; font-size: 0.85em; color: var(--ink-dim);
    border: 1px solid var(--line); padding: 1px 5px;
  }

  /* --- target list --- */
  #targets {
    flex: 1 1 auto; min-height: 0; overflow-y: auto; padding: 8px;
    scrollbar-width: thin; scrollbar-color: var(--line) transparent;
  }
  #targets::-webkit-scrollbar { width: 8px; }
  #targets::-webkit-scrollbar-thumb { background: var(--line); }
  #targets::-webkit-scrollbar-track { background: transparent; }
  #targets h2 {
    margin: 5px 8px 9px; font-size: 12px; font-weight: 700;
    letter-spacing: 0.16em; text-transform: uppercase; color: var(--ink-dim);
  }
  .target {
    display: block; width: 100%; text-align: left; cursor: pointer;
    padding: 8px 10px; margin-bottom: 2px;
    background: none; border: 0; border-left: 2px solid transparent;
    color: var(--ink); font: inherit; font-size: 14px;
  }
  .target:hover { background: rgba(141, 178, 232, 0.08); }
  .target[aria-current="true"] {
    background: rgba(141, 178, 232, 0.14); border-left-color: var(--focus);
  }
  .target .row { display: flex; justify-content: space-between; gap: 10px; }
  .target .name { font-weight: 600; }
  .target .sub { color: var(--ink-dim); font-size: 12.5px; margin-top: 2px; }
  .target.nomap .name { color: var(--ink-dim); font-weight: 400; }
  .tag {
    font-size: 11.5px; font-weight: 700; letter-spacing: 0.08em;
    text-transform: uppercase; color: var(--outward);
  }
  /* Swatch repeats the point-cloud colour, so the list and the scene agree. */
  .swatch {
    display: inline-block; width: 7px; height: 7px; margin-right: 8px;
    vertical-align: 1px;
  }

  /* --- readout --- */
  #readout { flex: 0 0 auto; padding: 14px 18px; }
  #readout h2 {
    margin: 0 0 10px; font-size: 14px; font-weight: 700; letter-spacing: 0.08em;
  }
  #readout dl {
    margin: 0; display: grid; grid-template-columns: auto 1fr; gap: 5px 16px;
  }
  #readout dt { color: var(--ink-dim); font-size: 12.5px; align-self: center; }
  #readout dd {
    margin: 0; text-align: right; font-size: 15px; font-weight: 600;
    font-variant-numeric: tabular-nums;
  }
  #ro-epochs:not(:empty) { display: flex; gap: 8px; margin-top: 13px; }
  .epoch {
    flex: 1; padding: 8px; background: none; border: 1px solid var(--line);
    color: var(--ink-dim); font: inherit; font-size: 13px; cursor: pointer;
    letter-spacing: 0.08em;
  }
  .epoch:hover { color: var(--ink); border-color: var(--focus); }
  .epoch[aria-pressed="true"] {
    color: var(--ink); border-color: var(--focus);
    background: rgba(141, 178, 232, 0.14);
  }

  /* --- the polarity scale bar: legend and structural anchor --- */
  #scale {
    position: fixed; right: 30px; top: 50%; transform: translateY(-50%);
    display: flex; align-items: stretch; gap: 14px; pointer-events: none;
  }
  #scale .bar {
    width: 18px; height: 46vh; min-height: 240px;
    border: 1px solid var(--line);
    box-shadow: 0 12px 32px rgba(0, 0, 0, 0.45);
  }
  #scale .ticks {
    display: flex; flex-direction: column; justify-content: space-between;
    text-align: left; font-variant-numeric: tabular-nums;
  }
  /* A tick mark on each label ties it to its exact height on the gradient --
     without it "outward"/"0"/"inward" read as a loose list rather than as
     marks on an instrument scale. */
  #scale .ticks span {
    display: block; padding-left: 12px; border-left: 1px solid var(--line);
  }
  #scale .ticks b {
    display: block; color: var(--ink); font-size: 15px; font-weight: 700;
    line-height: 1.25;
  }
  #scale .ticks small {
    display: block; font-size: 10.5px; letter-spacing: 0.06em;
    text-transform: uppercase; color: var(--ink-dim); font-weight: 400;
  }
  #scale .axis {
    writing-mode: vertical-rl; text-orientation: mixed;
    font-size: 11px; font-weight: 600; letter-spacing: 0.2em;
    text-transform: uppercase; color: var(--ink-dim); align-self: center;
  }

  /* --- accessibility --- */
  :focus-visible { outline: 2px solid var(--focus); outline-offset: 1px; }
  .sr {
    position: absolute; width: 1px; height: 1px; overflow: hidden;
    clip: rect(0 0 0 0); white-space: nowrap;
  }
  @media (prefers-reduced-motion: reduce) {
    * { transition: none !important; }
  }
</style>
</head>
<body>
<div id="view"></div>

<div id="protowarn" role="alert">
  Opened as a local file &mdash; textures cannot load this way (a browser
  security rule). Serve this folder, e.g. <code>python -m http.server</code>,
  or view it on GitHub Pages.
</div>

<div id="rail">
<header class="panel" id="head">
  <h1>Hyades &middot; ZDI surface maps</h1>
  <p>Radial magnetic field <i>B</i><sub>r</sub> wrapped onto spheres at Gaia
     positions. ICRS Cartesian, parsecs. Click a star &mdash; in the list, or
     any point in the scene &mdash; to open its map.</p>
  <p class="warn">Stellar radii exaggerated <b id="exag">&mdash;</b>&times;.
     Positions and distances are true.</p>
  <button type="button" id="wide">Cluster overview <kbd>esc</kbd></button>
</header>

<nav class="panel" id="targets" aria-label="Target list">
  <h2>Targets</h2>
  <div id="list"></div>
</nav>

<section class="panel" id="readout" aria-live="polite">
  <h2 id="ro-name">&mdash;</h2>
  <dl id="ro-body"></dl>
  <div id="ro-epochs" aria-label="Observing epoch"></div>
</section>
</div>

<aside id="scale" aria-hidden="true">
  <div class="axis">Polarity</div>
  <div class="bar" id="scale-bar"></div>
  <div class="ticks">
    <span><b id="sc-hi">&mdash;</b><small>outward</small></span>
    <span><b>0</b></span>
    <span><b id="sc-lo">&mdash;</b><small>inward</small></span>
  </div>
</aside>
<p class="sr">Vertical bar on the right is the magnetic polarity scale: red is
   field directed out of the stellar surface, blue is field directed into it.
   The scale is symmetric about zero.</p>

<script type="importmap">
{ "imports": {
    "three": "https://unpkg.com/three@__THREE_VERSION__/build/three.module.js",
    "three/addons/": "https://unpkg.com/three@__THREE_VERSION__/examples/jsm/"
} }
</script>

<script type="module">
import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';

const DATA = __SCENE_DATA__;
const REDUCED = matchMedia('(prefers-reduced-motion: reduce)').matches;

// Local files opened by double-click can't have their images read into a
// WebGL texture -- browsers refuse cross-origin pixel access, and a bare
// file:// document counts as cross-origin from itself. The scene still loads
// (it's inline JSON), only the maps stay blank, so this is the single most
// likely support question and worth catching before anyone has to ask it.
if (location.protocol === 'file:') {
  document.getElementById('protowarn').style.display = 'block';
}

/* ---- 1. scene ---------------------------------------------------------- */
// World axes are ICRS Cartesian in parsecs, used directly as three.js units,
// so "up" is ICRS +Z (north celestial pole), not the three.js default +Y.
const UP = new THREE.Vector3(0, 0, 1);

// preserveDrawingBuffer keeps the rendered frame readable after it is drawn,
// so the canvas can be saved as an image (right-click, or canvas.toDataURL).
// Costs a little memory; worth it for a tool people will want figures out of.
const renderer = new THREE.WebGLRenderer({
  antialias: true, logarithmicDepthBuffer: true, preserveDrawingBuffer: true
});
renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
document.getElementById('view').appendChild(renderer.domElement);

const scene = new THREE.Scene();
scene.background = new THREE.Color(0x060a14);

// Distances span ~50 pc while exaggerated radii are ~1e-3 pc, hence the very
// small near plane and the logarithmic depth buffer above.
const camera = new THREE.PerspectiveCamera(45, 1, 1e-4, 5e3);
camera.up.copy(UP);

const controls = new OrbitControls(camera, renderer.domElement);
controls.enableDamping = !REDUCED;
controls.dampingFactor = 0.08;

/* ---- 2. the cluster ---------------------------------------------------- */
// DATA.stars has one row per (star, epoch), so a two-epoch star appears twice.
// Anything positional -- the sphere, the marker point, the reticle, the centre
// of the view -- must work from unique stars instead, or those stars get
// duplicated on top of themselves.
const uniqueStars = [...new Map(DATA.stars.map(s => [s.name, s])).values()];

// Star name -> its first row in DATA.stars, i.e. the epoch a click in the
// scene should open (the epoch buttons handle switching from there).
const primaryIndex = new Map();
DATA.stars.forEach((s, i) => { if (!primaryIndex.has(s.name)) primaryIndex.set(s.name, i); });

const centre = new THREE.Vector3();
uniqueStars.forEach(s => centre.add(new THREE.Vector3(...s.pos)));
centre.divideScalar(uniqueStars.length);

const loader = new THREE.TextureLoader();
const objects = new Map();          // list index -> Object3D to fly to
const anchors = new Map();          // list index -> world position

/* A latitude-longitude graticule at 30-degree spacing. The whole point of the
   project is that these maps are spherical, so the sphere needs to read as a
   sphere and not as a shaded ball; the grid does that honestly, whereas a
   light source would darken half the data. */
function graticule(r, seg = 96) {
  const pts = [], eq = [];
  for (let lat = -60; lat <= 60; lat += 30) {
    const t = THREE.MathUtils.degToRad(lat);
    const rr = r * Math.cos(t), y = r * Math.sin(t);
    const into = (lat === 0) ? eq : pts;
    for (let i = 0; i < seg; i++) {
      const a = i / seg * Math.PI * 2, b = (i + 1) / seg * Math.PI * 2;
      into.push(rr * Math.cos(a), y, rr * Math.sin(a),
                rr * Math.cos(b), y, rr * Math.sin(b));
    }
  }
  for (let lon = 0; lon < 360; lon += 30) {
    const p = THREE.MathUtils.degToRad(lon);
    for (let i = 0; i < seg / 2; i++) {
      const a = -Math.PI / 2 + i / (seg / 2) * Math.PI;
      const b = -Math.PI / 2 + (i + 1) / (seg / 2) * Math.PI;
      pts.push(r * Math.cos(a) * Math.cos(p), r * Math.sin(a), r * Math.cos(a) * Math.sin(p),
               r * Math.cos(b) * Math.cos(p), r * Math.sin(b), r * Math.cos(b) * Math.sin(p));
    }
  }
  const mk = (arr, opacity) => {
    const g = new THREE.BufferGeometry();
    g.setAttribute('position', new THREE.Float32BufferAttribute(arr, 3));
    return new THREE.LineSegments(g, new THREE.LineBasicMaterial(
      { color: 0x0d1420, transparent: true, opacity }));
  };
  const group = new THREE.Group();
  group.add(mk(pts, 0.35), mk(eq, 0.6));
  return group;
}

/* The rotation axis, drawn through the poles. Inclination is the one
   orientation angle ZDI constrains, so it should be visible, not implied. */
function spinAxis(r) {
  const g = new THREE.BufferGeometry();
  g.setAttribute('position', new THREE.Float32BufferAttribute(
    [0, -r * 1.45, 0, 0, r * 1.45, 0], 3));
  return new THREE.LineSegments(g, new THREE.LineBasicMaterial(
    { color: 0x7fa8e0, transparent: true, opacity: 0.5 }));
}

const meshFor = new Map();          // star name -> its one Mesh

DATA.stars.forEach((s, i) => {
  anchors.set(i, new THREE.Vector3(...s.pos));
  if (!s.texture) return;           // no map: this star is only a marker point

  if (!meshFor.has(s.name)) {
    // The sphere is created untextured. 28 maps at 2048x1024 would be ~235 MB
    // of GPU memory if loaded up front, for a scene where only the star you
    // have flown to is ever more than a pixel wide -- so textures load on
    // selection. Unlit: the texture is the measurement, and any shading term
    // would make B_r unreadable against the polarity scale on the right.
    const mesh = new THREE.Mesh(
      new THREE.SphereGeometry(s.radiusPc, 128, 96),
      new THREE.MeshBasicMaterial({ color: 0x16202f })
    );
    mesh.position.copy(new THREE.Vector3(...s.pos));
    // SphereGeometry's pole is +Y; swing it onto the star's spin axis so the
    // visible pole matches the inclination the inversion assumed.
    mesh.quaternion.setFromUnitVectors(
      new THREE.Vector3(0, 1, 0), new THREE.Vector3(...s.axis).normalize());
    mesh.add(graticule(s.radiusPc * 1.004), spinAxis(s.radiusPc));
    scene.add(mesh);
    meshFor.set(s.name, mesh);
  }
  // Both epochs of a star point at the same sphere; selecting one swaps its map.
  objects.set(i, meshFor.get(s.name));
});

/* Every star, including the mapped ones, also gets a screen-space point. These
   are markers, not objects: fixed pixel size, so they never masquerade as a
   physical scale the way a sphere would. Colour follows rotation period,
   matching prot.cmap in the .speck build. */
const pointGeom = new THREE.BufferGeometry();
pointGeom.setAttribute('position', new THREE.Float32BufferAttribute(
  uniqueStars.flatMap(s => s.pos), 3));
pointGeom.setAttribute('color', new THREE.Float32BufferAttribute(
  uniqueStars.flatMap(s => {
    const c = new THREE.Color(s.color); return [c.r, c.g, c.b];
  }), 3));
scene.add(new THREE.Points(pointGeom, new THREE.PointsMaterial({
  size: 5, sizeAttenuation: false, vertexColors: true,
  transparent: true, opacity: 0.9, depthWrite: false
})));

/* A reticle on the stars that actually carry a map. At cluster scale an
   exaggerated sphere is still sub-pixel, so without this there is no way to
   tell which points have data behind them. */
function reticleTexture() {
  const c = document.createElement('canvas');
  c.width = c.height = 64;
  const g = c.getContext('2d');
  g.strokeStyle = '#c1483c';
  g.lineWidth = 3;
  g.strokeRect(10, 10, 44, 44);
  const t = new THREE.CanvasTexture(c);
  t.colorSpace = THREE.SRGBColorSpace;
  return t;
}
const mapped = uniqueStars.filter(s => s.texture);
let reticles = null;
if (mapped.length) {
  const g = new THREE.BufferGeometry();
  g.setAttribute('position', new THREE.Float32BufferAttribute(
    mapped.flatMap(s => s.pos), 3));
  reticles = new THREE.Points(g, new THREE.PointsMaterial({
    size: 18, sizeAttenuation: false, map: reticleTexture(),
    transparent: true, opacity: 0.75, depthWrite: false, depthTest: false
  }));
  scene.add(reticles);
}

// The reticle is a cluster-scale wayfinding mark. Once the camera is close
// enough that the sphere itself is legible, it has done its job -- and since
// it ignores depth it would otherwise sit on top of the map.
const RETICLE_FADE_PC = 0.5;

// The Sun, as a reference point for the cluster's distance.
const sunGeom = new THREE.BufferGeometry();
sunGeom.setAttribute('position', new THREE.Float32BufferAttribute([0, 0, 0], 3));
scene.add(new THREE.Points(sunGeom, new THREE.PointsMaterial(
  { size: 7, sizeAttenuation: false, color: 0xf0e6c8, depthWrite: false })));

/* Put the selected epoch's B_r map on that star's sphere, fetching it the
   first time and reusing it afterwards, so flipping between epochs is
   instant once both are in hand. */
const texCache = new Map();

function showTexture(i) {
  const s = DATA.stars[i], mesh = objects.get(i);
  if (!mesh || !s.texture) return;

  const apply = tex => {
    mesh.material.map = tex;
    mesh.material.color.set(0xffffff);   // stop tinting once the map is on
    mesh.material.needsUpdate = true;
  };
  if (texCache.has(s.texture)) { apply(texCache.get(s.texture)); return; }

  loader.load(
    s.texture,
    tex => {
      tex.colorSpace = THREE.SRGBColorSpace;
      texCache.set(s.texture, tex);
      // A slow fetch must not overwrite a map the user has since moved on from.
      if (current === i) apply(tex);
    },
    undefined,
    () => {   // load failed: wrong path, missing file, or (usually) file://
      if (location.protocol === 'file:') {
        document.getElementById('protowarn').style.display = 'block';
      } else {
        console.error(`ZDIviz: could not load texture "${s.texture}"`);
      }
    }
  );
}

/* ---- 3. camera moves --------------------------------------------------- */
let anim = null;

function flyTo(target, distance) {
  // Approach along the current view direction so the framing stays continuous.
  const dir = camera.position.clone().sub(controls.target).normalize();
  const endPos = target.clone().add(dir.multiplyScalar(distance));
  if (REDUCED) {                       // no motion: cut straight to the view
    camera.position.copy(endPos);
    controls.target.copy(target);
    return;
  }
  anim = {
    t: 0, dur: 900,
    fromPos: camera.position.clone(), toPos: endPos,
    fromTgt: controls.target.clone(), toTgt: target.clone(),
    last: performance.now()
  };
}

function overview() {
  current = -1;
  [...listEl.children].forEach(el => el.setAttribute('aria-current', 'false'));
  document.getElementById('ro-name').textContent = 'Hyades ZDI sample';
  document.getElementById('ro-epochs').innerHTML = '';
  document.getElementById('ro-body').innerHTML =
    `<dt>stars</dt><dd>${uniqueStars.length}</dd>` +
    `<dt>with B_r map</dt><dd>${mapped.length}</dd>` +
    `<dt>maps (all epochs)</dt><dd>${DATA.stars.filter(s => s.texture).length}</dd>` +
    `<dt>P_rot range</dt><dd>${DATA.protRange.map(p => p.toFixed(2)).join('–')} d</dd>`;
  document.getElementById('sc-hi').textContent = '—';
  document.getElementById('sc-lo').textContent = '—';
  flyTo(centre, 26);
}

/* ---- 4. HUD ------------------------------------------------------------ */
const fmt = (v, d = 2, unit = '') =>
  (v === null || v === undefined) ? '—' : v.toFixed(d) + unit;

document.getElementById('exag').textContent =
  DATA.exaggeration.toLocaleString('en-US');

// Build the polarity bar from the same colormap that produced the textures.
document.getElementById('scale-bar').style.background =
  'linear-gradient(to top, ' + DATA.stops.join(', ') + ')';

const listEl = document.getElementById('list');
let current = -1;

DATA.stars.forEach((s, i) => {
  const b = document.createElement('button');
  b.className = 'target' + (s.texture ? '' : ' nomap');
  b.type = 'button';
  b.innerHTML =
    `<span class="row"><span class="name">` +
    `<i class="swatch" style="background:${s.color}"></i>${s.name}</span>` +
    `<span class="tag">${s.texture ? s.epoch : ''}</span></span>` +
    `<span class="row sub"><span>${fmt(s.distPc, 2, ' pc')}</span>` +
    `<span>P&#8339; ${fmt(s.prot, 2, ' d')}</span>` +
    `<span>i ${fmt(s.incl, 0, '°')}</span></span>`;
  b.addEventListener('click', () => select(i));
  listEl.appendChild(b);
});

function select(i, move = true) {
  const s = DATA.stars[i];
  current = i;
  showTexture(i);
  [...listEl.children].forEach((el, k) =>
    el.setAttribute('aria-current', k === i ? 'true' : 'false'));

  document.getElementById('ro-name').textContent =
    s.name + (s.epoch ? '  ·  ' + s.epoch : '');

  const rows = [
    ['distance',    fmt(s.distPc, 2, ' pc')],
    ['radius',      fmt(s.radiusRsun, 3, ' R☉')],
    ['P_rot',       fmt(s.prot, 2, ' d')],
    ['inclination', fmt(s.incl, 1, '°')],
    ['T_eff',       fmt(s.teff, 0, ' K')],
    ['max |B_r|',   s.vmax === null ? 'no map' : fmt(s.vmax, 1, ' G')],
  ];
  document.getElementById('ro-body').innerHTML =
    rows.map(([k, v]) => `<dt>${k}</dt><dd>${v}</dd>`).join('');

  /* Nine of these stars were observed in two epochs. Switching between them
     without moving the camera is the clearest way to see the field itself
     reorganise -- the comparison a pair of flat maps makes hard. */
  const sib = DATA.stars
    .map((o, k) => ({ o, k }))
    .filter(({ o }) => o.name === s.name && o.texture);
  const ep = document.getElementById('ro-epochs');
  if (sib.length > 1) {
    ep.innerHTML = sib.map(({ o, k }) =>
      `<button type="button" class="epoch" data-i="${k}" ` +
      `aria-pressed="${k === i}">${o.epoch}</button>`).join('');
    ep.querySelectorAll('.epoch').forEach(b => b.addEventListener('click',
      () => select(+b.dataset.i, false)));   // swap the map, hold the camera
  } else {
    ep.innerHTML = '';
  }

  // The polarity scale is per-star: each map is scaled to its own max|B_r|.
  document.getElementById('sc-hi').textContent =
    s.vmax === null ? '—' : '+' + s.vmax.toFixed(0) + ' G';
  document.getElementById('sc-lo').textContent =
    s.vmax === null ? '—' : '−' + s.vmax.toFixed(0) + ' G';

  // Mapped stars are framed on the sphere; unmapped ones have no size to
  // frame, so approach to a fixed few-parsec standoff instead.
  if (move) flyTo(anchors.get(i), s.texture ? s.radiusPc * 6.5 : 2.0);
}

/* ---- 4b. click a star directly in the scene ---------------------------- */
// Every star's marker is drawn at a fixed screen size (sizeAttenuation:
// false), so picking is done in screen space too, rather than with
// THREE.Raycaster's world-space distance test -- that way the click target
// matches what the eye actually sees as "the point", at any zoom level, in
// the cluster overview or zoomed into another star.
const PICK_RADIUS_PX = 14;
const pickVec = new THREE.Vector3();

function pickStar(px, py, w, h) {
  let best = null, bestDist = PICK_RADIUS_PX;
  for (const s of uniqueStars) {
    pickVec.set(...s.pos).project(camera);
    if (pickVec.z < -1 || pickVec.z > 1) continue;        // behind the camera
    const x = (pickVec.x * 0.5 + 0.5) * w;
    const y = (1 - (pickVec.y * 0.5 + 0.5)) * h;
    const d = Math.hypot(x - px, y - py);
    if (d < bestDist) { bestDist = d; best = s; }
  }
  return best ? primaryIndex.get(best.name) : null;
}

const dom = renderer.domElement;
let downAt = null;

dom.addEventListener('pointerdown', e => { downAt = [e.clientX, e.clientY]; });

dom.addEventListener('pointerup', e => {
  const start = downAt;
  downAt = null;
  // A drag (orbiting the camera) must not also count as a click.
  if (!start || Math.hypot(e.clientX - start[0], e.clientY - start[1]) > 6) return;
  const r = dom.getBoundingClientRect();
  const hit = pickStar(e.clientX - r.left, e.clientY - r.top, r.width, r.height);
  if (hit !== null) select(hit);
});

dom.addEventListener('pointermove', e => {
  const r = dom.getBoundingClientRect();
  const hit = pickStar(e.clientX - r.left, e.clientY - r.top, r.width, r.height);
  dom.style.cursor = hit !== null ? 'pointer' : '';
});

/* ---- 5. loop ----------------------------------------------------------- */
function resize() {
  const w = innerWidth, h = innerHeight;
  camera.aspect = w / h;
  camera.updateProjectionMatrix();
  renderer.setSize(w, h);
}
addEventListener('resize', resize);
resize();

// Start looking at the whole cluster from a little off its centre.
camera.position.copy(centre).add(new THREE.Vector3(0, -26, 8));
controls.target.copy(centre);

const easeInOut = t => t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2;

renderer.setAnimationLoop(() => {
  if (anim) {
    const now = performance.now();
    anim.t = Math.min(1, anim.t + (now - anim.last) / anim.dur);
    anim.last = now;
    const e = easeInOut(anim.t);
    camera.position.lerpVectors(anim.fromPos, anim.toPos, e);
    controls.target.lerpVectors(anim.fromTgt, anim.toTgt, e);
    if (anim.t >= 1) anim = null;
  }
  if (reticles) {
    reticles.visible = mapped.every(s =>
      camera.position.distanceTo(new THREE.Vector3(...s.pos)) > RETICLE_FADE_PC);
  }
  controls.update();
  renderer.render(scene, camera);
});

document.getElementById('wide').addEventListener('click', overview);
addEventListener('keydown', e => { if (e.key === 'Escape') overview(); });

// Open on the first mapped star if there is one, otherwise the whole cluster.
const first = DATA.stars.findIndex(s => s.texture);
if (first >= 0) select(first); else overview();
</script>
</body>
</html>
"""
