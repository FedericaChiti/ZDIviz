# ZDIviz

Turn Zeeman-Doppler Imaging maps into 3D assets: OpenSpace scene files for the
dome, and a self-contained three.js page for the browser — one codebase, two
renderers, the same geometry in both. **The browser preview is what's proven:
built, rendered, and checked in-browser (screenshot below). The OpenSpace
assets are written to the platform's documented schema but have not yet been
loaded on hardware that can run them** — see [Status](#status).

![Browser preview: the 2022 ZDI radial-field map of [RSP2011] 587 wrapped onto a sphere, with the target list and the polarity scale bar](docs/preview.png)

**19 Hyades K dwarfs · 28 ZDI maps across two epochs · one build command.**

---

## Why

Zeeman-Doppler Imaging inverts a time series of circularly polarised line
profiles into a map of the magnetic field across a rotating stellar surface
(Semel 1989, A&A 225, 456; Donati & Brown 1997, A&A 326, 1135; see Kochukhov
2016, LNP 914, 177 for the review). The inversion is spherical from beginning
to end: it solves for the field on a spherical grid, using the rotational
modulation of a sphere to break the degeneracy between latitude bands.

Then, essentially every published ZDI map is printed as a flat Mollweide
projection.

The projection is a reasonable concession to paper. But it discards the
geometry the inversion actually recovered, and with it the things that geometry
governs: which pole is visible at a given inclination, how the field connects
across the surface, how the topology looks from a direction that is not the
line of sight. Field topology is not a cosmetic detail — it sets the structure
of the stellar wind and the size of the Alfvén surface, and therefore how much
a close-in planet's atmosphere is eroded (Vidotto et al. 2013, A&A 557, A67).

This tool wraps the maps back onto spheres and puts each sphere at the star's
true position from Gaia parallax. In the Hyades that is a real cluster in real
3D, not a scatter plot on the sky.

## Install and run

Python 3.9+, three dependencies, no compilation step.

```bash
pip install -r requirements.txt
```

```bash
python build.py
```

Everything lands in `docs/` (that name, not `build/`, is required — it's one of the only two folders GitHub Pages' "Deploy from a branch" option can serve):

| Output | What it is |
|---|---|
| `textures/*.png` | equirectangular B_r maps, 2048×1024, diverging scale symmetric about zero |
| `hyades.speck` | Digital Universe point catalogue, parsecs, with `datavar` headers |
| `hyades.label` | labels for the point cloud |
| `prot.cmap` | colour table for the point cloud, keyed on rotation period |
| `zdi_stars.asset` | one `RenderableSphere` per mapped star, `StaticTranslation` in metres |
| `hyades_cloud.asset` | the cluster as a point cloud |
| `index.html` | the browser preview |

Open `docs/index.html` — over `http://`, not `file://`, since the textures are
fetched:

```bash
python -m http.server -d docs 8000
```

To change the radius scaling (see below):

```bash
python build.py --exaggeration 1e5
```

Tests:

```bash
pip install pytest && pytest -q
```

## Input data

### Target catalogue — `targets.csv`

`targets.csv` holds one row per (star, epoch) with the nine columns the build
reads. It is generated from the full working catalogue, which carries ~100
columns of analysis this project has no use for and which is not published
here:

```bash
python make_targets.py full_sample_dataframe.csv
```

The column list lives in `zdiviz.io.CATALOG_COLUMNS` and is imported by
`make_targets.py` rather than restated, so the published file cannot drift out
of step with the loader.

| Column | Meaning | Units | Required |
|---|---|---|---|
| `Star_Name` | catalogue number; the SIMBAD designation is `[RSP2011] <n>` | — | yes |
| `Obs_Year` | epoch of the observing run; keys the star to its map | year | yes |
| `RAdeg` | right ascension, ICRS | deg | yes |
| `DEdeg` | declination, ICRS | deg | yes |
| `Plx` | Gaia parallax | mas | yes |
| `Radius_Rsun_final` | stellar radius | R☉ | yes |
| `Prot` | rotation period | d | no |
| `new_i` | rotation-axis inclination | deg | no |
| `Teff_bprp` | effective temperature from Gaia BP−RP | K | no |

Nine of the 19 stars were observed in both 2020 and 2022, which is why the
catalogue has 28 rows: rows are keyed on `(Star_Name, Obs_Year)`, not on the
star alone.

Rows missing a required field, or with a non-positive parallax, are **skipped
and reported** — never filled in with a placeholder. Optional fields that are
absent are written as `-999.0` in the `.speck` (the format has no NaN) and
render as `—` in the browser.

### ZDI maps — `data/maps/`

Two filename conventions are accepted, with an optional `_map` suffix:

| Pattern | Example | Epoch comes from |
|---|---|---|
| `<star>_<year>_map.dat` | `409_2022_map.dat` | the filename |
| `<star>_map.dat` | `133_map.dat` | the catalogue, **only** if that star has exactly one epoch |

A year-less filename for a star with two epochs is **reported and skipped**,
not guessed at. Any map that cannot be tied to a catalogue row is named in the
build log with the reason. The loader also accepts `.npy` and `.fits` grids,
which are assumed to be already rectangular with rows running north to south.

The `.dat` products of the INVERS inversion code are **not** rectangular
lat-lon grids. They are variable-resolution *equal-area* grids: the number of
longitude samples per latitude band tracks cos(lat), so a 38-band map has 4
cells at the poles and 77 at the equator, 1876 in total. The columns are

```
N   Lat (deg)   Lon (deg)   Br (kG)   Blat (kG)   Bphi (kG)   Scalar
```

with latitude bands ascending south → north at 180/38 = 4.7368° spacing, and
longitudes at `(j + 0.5) × 360/n` within each band.

`zdiviz/io.py` reads that grid natively and resamples it onto the
rectangular raster — periodic interpolation in longitude within each band, then
linear interpolation in latitude. No spherical-harmonic refit, so no angular
power is introduced that the inversion did not recover.

The maps carry the full vector field. **This tool uses the radial component
`B_r` only.** The meridional and azimuthal components are parsed and available
in `read_invers_dat`, but nothing downstream consumes them.

#### Verification

Because the grid is equal-area, every cell carries the same weight, so a plain
unweighted mean over cells *is* the surface average — no cos-latitude
weighting. That gives a free, strong check on the loader: recompute the surface
averages from the ingested data and compare them to the values published in the
catalogue.

Across **all 28 maps**, for both mean |B| and mean |B_r|, the worst
disagreement is **0.56%**, and most are under 0.3%:

| Map | mean \|B\| ingested | catalogue | mean \|B_r\| ingested | catalogue |
|---|---|---|---|---|
| 409 / 2022 | 22.64 G | 22.55 | 20.71 G | 20.61 |
| 587 / 2022 | 87.97 G | 88.18 | 27.33 G | 27.32 |
| 198 / 2020 | 5.16 G | 5.16 | 4.74 G | 4.74 |
| 571 / 2020 | 52.91 G | 53.05 | 10.17 G | 10.17 |

Getting that agreement requires the file format, the kG→G conversion, the
equal-area grid interpretation *and* the component ordering all to be right at
once, so it is the check worth running. It is `test_surface_averages_match_catalogue`
in `tests/`, and it runs over every map, not the four shown here.

## Choices worth stating

**Radius exaggeration — 3×10⁵ by default.** A 0.65 R☉ star at 45 pc subtends
about 10⁻⁸ of its own distance. At true scale every sphere is far below one
pixel and the scene is empty. So the radii are multiplied by `--exaggeration`,
default `3e5`. Positions and distances are **not** touched. The factor is
printed in the header comment of every `.asset` file, in the build log, and in
the browser HUD. Exaggeration is standard practice in astrovisualisation and it
is fine; hiding it is not.

**Distance is the direct parallax inversion,** `d[pc] = 1000 / plx[mas]`. For
the Hyades this is defensible: parallaxes near 20 mas with ~0.1% errors, so the
nonlinearity of 1/ϖ and the asymmetry of the distance posterior are negligible.
It would *not* be defensible for a faint or distant sample, where the correct
approach is a Bayesian distance with a proper distance prior (Bailer-Jones et
al. 2021, AJ 161, 147). If this pipeline is ever pointed at something farther
away, that is the line to change — `icrs_to_cartesian_pc` in `zdiviz/io.py`.

**The colour scale is forced symmetric about zero,** at ±max|B_r| per map. The
sign of B_r is the physical quantity: field entering the surface versus leaving
it. An independently-scaled positive and negative end would make a spot look
stronger purely because it happened to be the positive one. Each star is scaled
to its own maximum, so the bar is a per-target legend and **colours are not
comparable between stars** — the readout gives the numerical limit.

**Inclination is applied; the position angle on the sky is not.** Each sphere
is tilted so the angle between its rotation axis and the line of sight equals
the star's inclination — the one orientation angle ZDI genuinely constrains.
The axis's position angle on the sky is *not* constrained by the technique, so
it is fixed by convention (the axis leans toward ICRS north). Likewise the
longitude zero point is rotational phase, which is arbitrary; longitude 0 is
placed at texture column 0.

**Surfaces are rendered unlit.** The texture is a measurement, so no light
source is allowed to darken half of it. A 30° graticule carries the sphericity
instead.

**One sphere per star, not per map.** Nine stars have two epochs. They get a
single sphere at a single position, and the epoch switch swaps the texture on
it — so you compare the two maps in place, without the camera moving. Building
one sphere per row would stack coincident spheres and z-fight.

**Textures load on selection, not up front.** 28 maps at 2048×1024 is ~235 MB
of GPU memory if loaded eagerly, in a scene where only the star you have flown
to is ever more than a pixel across.

## Repository layout

```
build.py                  single entry point
make_targets.py           full catalogue -> targets.csv
targets.csv               the 9 columns the build reads, 28 rows
data/maps/                28 ZDI maps -- local only, gitignored
zdiviz/
  io.py                   read maps + catalogue, resample, ICRS geometry
  texture.py              lat-lon grid -> equirectangular PNG
  speck.py                -> .speck / .label / .cmap
  assets.py               -> OpenSpace .asset Lua config
  preview.py              -> standalone three.js HTML
tests/                    pytest; run with `pytest -q`
docs/                     generated; committed so GitHub Pages can serve it
                          (docs/preview.png is the one hand-picked exception --
                          build.py never touches it)
docs/preview.png          the screenshot above
```

Nothing here executes Lua. A `.speck` is a text table and an `.asset` is a Lua
config file; both are written as plain text from Python.

### OpenSpace version note

The point-cloud renderable was renamed at OpenSpace 0.20:
`RenderableBillboardsCloud` → `RenderablePointCloud`, and its properties were
regrouped at the same time (`ScaleExponent` and `ColorMap` moved under
`SizeSettings` and `Coloring`). The generated assets target **0.20+**. The name
is a module-level constant, `POINT_CLOUD_RENDERABLE` in
`zdiviz/assets.py`, with the older name and the property differences
noted beside it.

## Status

- **Browser preview: verified.** Built and rendered in a browser; geometry,
  texture orientation, target selection, the epoch switch, camera easing, and
  the reduced-motion and keyboard-focus paths were all exercised. The
  screenshot above is that build.
- **Loader: verified against the data.** Grid structure, axis ordering and unit
  conversion confirmed against the files; recomputed surface averages match the
  catalogue to better than 0.6% across all 28 maps (above). `pytest -q` — 27
  tests, all passing.
- **OpenSpace assets: written to the documented schema, not yet loaded.** The
  `.asset` and `.speck` files follow the documented format, and the numbers in
  them (positions in metres, radii, Euler angles) are unit-tested against an
  independent construction of the same rotation. But they have **not** been
  opened in OpenSpace and **not** been run on a dome. Treat the schema as
  plausible-but-unconfirmed until someone loads it on a 4.6-capable machine.

The split exists because OpenSpace requires OpenGL 4.6 and macOS caps at 4.1,
so the assets cannot be tested on the machine that generates them.

## Data and citation

The ZDI maps and the stellar parameters are from my own work on the Hyades
K dwarfs. If you use this code, cite the ZDI method papers above; if you use
the maps, please get in touch first.

## License

MIT — see [LICENSE](LICENSE).
