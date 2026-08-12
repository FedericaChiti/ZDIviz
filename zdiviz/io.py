"""Reading ZDI maps and the target catalogue.

The maps produced by the Kochukhov INVERS inversion code are *not* stored on a
rectangular latitude-longitude grid.  They sit on a variable-resolution
equal-area grid: every cell subtends the same solid angle, so the number of
longitude samples in a latitude band falls off roughly as cos(lat) -- 4 cells
at the poles, 77 at the equator.  This module's job is to read that ragged
grid and resample it onto the plain rectangular raster the rest of the
pipeline (and any texture mapper) expects.
"""

from pathlib import Path
import csv
import re
import numpy as np

# --- Physical constants ---------------------------------------------------

PARSEC_M = 3.0856775814913673e16   # metres in one parsec
RSUN_M = 6.957e8                   # metres in one solar radius


# --- ZDI maps -------------------------------------------------------------

# Column layout of the INVERS `inversLSD_maptxt.dat` product.  Field columns
# are in kilogauss; we convert to gauss on read.
_COL_LAT, _COL_LON, _COL_BR, _COL_BLAT, _COL_BPHI = 1, 2, 3, 4, 5
_KG_TO_G = 1000.0


def read_invers_dat(path):
    """Read one INVERS .dat map into its native ragged equal-area form.

    Returns a dict with, for each of the three field components, a list of
    1D arrays -- one per latitude band, ordered south to north:

        {"lat": (nbands,) band centres in degrees, ascending,
         "lon": [ (n_i,) longitudes in degrees, ascending, per band ],
         "br"/"blat"/"bphi": [ (n_i,) field values in gauss, per band ]}

    No interpolation happens here; this is the file exactly as written.
    """
    raw = np.loadtxt(path, skiprows=1)
    if raw.ndim != 2 or raw.shape[1] < 6:
        raise ValueError(f"{Path(path).name}: expected >=6 columns, got {raw.shape}")

    lat_col = raw[:, _COL_LAT]
    # Group rows into latitude bands.  Round first: the file prints latitudes
    # to 3 decimals, so exact float equality within a band is not guaranteed.
    bands = np.unique(np.round(lat_col, 3))

    out = {"lat": bands, "lon": [], "br": [], "blat": [], "bphi": []}
    for band in bands:
        rows = raw[np.round(lat_col, 3) == band]
        order = np.argsort(rows[:, _COL_LON])          # enforce ascending longitude
        rows = rows[order]
        out["lon"].append(rows[:, _COL_LON])
        out["br"].append(rows[:, _COL_BR] * _KG_TO_G)
        out["blat"].append(rows[:, _COL_BLAT] * _KG_TO_G)
        out["bphi"].append(rows[:, _COL_BPHI] * _KG_TO_G)
    return out


def resample_equirectangular(ragged, component="br", nlon=2048, nlat=1024):
    """Resample a ragged equal-area map onto a rectangular lat-lon raster.

    Two passes, both linear, no spherical-harmonic refit -- we do not want to
    inject angular power the inversion never recovered:

      1. within each latitude band, interpolate periodically in longitude
         onto the output longitude column centres;
      2. between the two bracketing bands, interpolate linearly in latitude.

    Output rows run north (+90) to south (-90), which is the row order image
    files and equirectangular texture samplers expect.  Output columns run
    longitude 0 -> 360.
    """
    src_lat = ragged["lat"]                             # ascending, south -> north
    src_val = ragged[component]

    # Output cell centres.
    out_lon = (np.arange(nlon) + 0.5) * 360.0 / nlon
    out_lat = 90.0 - (np.arange(nlat) + 0.5) * 180.0 / nlat   # north -> south

    # Pass 1: every source band, resampled onto the common longitude grid.
    # np.interp is not periodic, so we wrap one sample around each end.
    bands = np.empty((len(src_lat), nlon))
    for i, (lon, val) in enumerate(zip(ragged["lon"], src_val)):
        lon_w = np.concatenate(([lon[-1] - 360.0], lon, [lon[0] + 360.0]))
        val_w = np.concatenate(([val[-1]], val, [val[0]]))
        bands[i] = np.interp(out_lon, lon_w, val_w)

    # Pass 2: linear in latitude.  Beyond the outermost band centres (the file
    # samples to +-87.6, not the poles) we hold the polar band value rather
    # than extrapolating to a fabricated pole value.
    idx = np.clip(np.searchsorted(src_lat, out_lat), 1, len(src_lat) - 1)
    lo, hi = src_lat[idx - 1], src_lat[idx]
    w = np.clip((out_lat - lo) / (hi - lo), 0.0, 1.0)[:, None]
    return (1.0 - w) * bands[idx - 1] + w * bands[idx]


def load_map(path, component="br", nlon=2048, nlat=1024):
    """Load any supported map file as an (nlat, nlon) equirectangular array.

    .dat  -> INVERS ragged equal-area text, resampled (the real case)
    .npy  -> already a rectangular grid, used as-is
    .fits -> ditto, via astropy

    For the already-rectangular formats we assume rows run north to south; if
    yours run the other way, flip them here and nothing downstream changes.
    """
    path = Path(path)
    suffix = path.suffix.lower()

    if suffix in (".dat", ".txt"):
        return resample_equirectangular(read_invers_dat(path), component, nlon, nlat)

    if suffix == ".npy":
        arr = np.load(path)
    elif suffix in (".fits", ".fit"):
        from astropy.io import fits          # lazy import: FITS support is optional
        arr = fits.getdata(path)
    else:
        raise ValueError(f"{path.name}: unsupported map format '{suffix}'")

    arr = np.asarray(arr, dtype=float)
    if arr.ndim != 2:
        raise ValueError(f"{path.name}: expected a 2D lat-lon grid, got {arr.shape}")
    return arr


MAP_SUFFIXES = (".dat", ".txt", ".npy", ".fits", ".fit")


def parse_map_name(stem):
    """Split a map filename stem into (star, epoch-or-None).

    Both conventions in use are accepted, with an optional `_map` suffix:

        409_2022_map.dat -> ("409", "2022")   two-epoch star, year is explicit
        133_map.dat      -> ("133", None)     single-epoch star, year omitted
        409_2022.dat     -> ("409", "2022")

    A missing epoch is left as None rather than guessed; `match_maps` resolves
    it against the catalogue, and refuses to if the answer is ambiguous.
    """
    parts = stem.split("_")
    if parts and parts[-1].lower() == "map":
        parts = parts[:-1]
    if not parts or not parts[0]:
        return None, None
    epoch = None
    if len(parts) > 1 and re.fullmatch(r"(?:19|20)\d{2}", parts[-1]):
        epoch = parts[-1]
        parts = parts[:-1]
    return "_".join(parts), epoch


def discover_maps(map_dir):
    """Index the map directory. Returns {(star, epoch-or-None): Path}."""
    found = {}
    for p in sorted(Path(map_dir).glob("*.*")):
        if p.suffix.lower() not in MAP_SUFFIXES:
            continue
        star, epoch = parse_map_name(p.stem)
        if star:
            found[(star, epoch)] = p
    return found


def match_maps(targets, found):
    """Bind discovered map files to catalogue rows.

    Returns ({(star, epoch): Path}, problems), where `problems` is a list of
    (filename, reason) for files that could not be bound.  Nothing is guessed:
    a file whose name omits the epoch is only resolved when the catalogue lists
    exactly one epoch for that star.
    """
    epochs_of = {}
    for t in targets:
        epochs_of.setdefault(t["star"], []).append(t["epoch"])

    matched, problems = {}, []
    for (star, epoch), path in sorted(found.items(), key=lambda kv: kv[1].name):
        known = epochs_of.get(star)
        if not known:
            problems.append((path.name, f"no catalogue row for star {star}"))
        elif epoch is None and len(known) == 1:
            matched[(star, known[0])] = path
        elif epoch is None:
            problems.append((path.name, f"filename omits the epoch and star {star} "
                                        f"has {len(known)} ({', '.join(sorted(known))}) "
                                        f"- rename it <star>_<year>_map.dat"))
        elif epoch not in known:
            problems.append((path.name, f"no catalogue row for star {star}, epoch {epoch}"))
        else:
            matched[(star, epoch)] = path
    return matched, problems


# --- Target catalogue -----------------------------------------------------

# Columns pulled from full_sample_dataframe.csv, mapped to internal names.
# Everything else in that file (activity indices, torques, photometry) is
# irrelevant to the geometry and is ignored.
CATALOG_COLUMNS = {
    "Star_Name": "star",
    "Obs_Year": "epoch",
    "RAdeg": "ra_deg",
    "DEdeg": "dec_deg",
    "Plx": "parallax_mas",
    "Radius_Rsun_final": "radius_rsun",
    "Prot": "prot_d",
    "new_i": "inclination_deg",
    "Teff_bprp": "teff_k",
}

# Without these a star has no position or no size, so it cannot be placed.
REQUIRED = ("ra_deg", "dec_deg", "parallax_mas", "radius_rsun")

# SIMBAD designation for this sample: Star_Name holds the RSP2011 number.
NAME_PREFIX = "[RSP2011] "


def load_targets(path):
    """Read the target catalogue into a list of dicts.

    One entry per (star, epoch) row.  Rows missing any REQUIRED field, or with
    a non-positive parallax, are dropped -- never patched with a placeholder.
    Returns (targets, skipped) where `skipped` is a list of (label, reason).
    """
    targets, skipped = [], []
    with open(path, newline="") as f:
        for row in csv.DictReader(f):
            rec = {}
            for src, dst in CATALOG_COLUMNS.items():
                text = (row.get(src) or "").strip()
                if dst in ("star", "epoch"):
                    rec[dst] = text
                else:
                    try:
                        rec[dst] = float(text)
                    except ValueError:
                        rec[dst] = None        # blank or unparseable -> absent

            label = f"{NAME_PREFIX}{rec['star']}"
            missing = [k for k in REQUIRED if rec[k] is None]
            if missing:
                skipped.append((label, "missing " + ", ".join(missing)))
                continue
            if rec["parallax_mas"] <= 0:
                skipped.append((label, "non-positive parallax"))
                continue

            rec["name"] = label
            rec["slug"] = f"RSP2011_{rec['star']}"     # filesystem/Lua-safe
            rec["x_pc"], rec["y_pc"], rec["z_pc"] = icrs_to_cartesian_pc(
                rec["ra_deg"], rec["dec_deg"], rec["parallax_mas"])
            rec["dist_pc"] = 1000.0 / rec["parallax_mas"]
            targets.append(rec)
    return targets, skipped


def unique_stars(targets):
    """Collapse multi-epoch rows to one entry per star, keeping the earliest.

    Stellar geometry (position, radius, period, inclination) is identical
    across epochs in this catalogue -- only the magnetic map changes -- so the
    point cloud should show each star once.
    """
    seen = {}
    for t in sorted(targets, key=lambda r: r["epoch"]):
        seen.setdefault(t["star"], t)
    return list(seen.values())


# --- Geometry -------------------------------------------------------------

def icrs_to_cartesian_pc(ra_deg, dec_deg, parallax_mas):
    """Sky position + parallax -> ICRS Cartesian coordinates in parsecs.

    Distance is the direct parallax inversion, d[pc] = 1000 / plx[mas].  That
    is sound for a nearby, high-precision sample like the Hyades (plx ~ 20 mas
    at ~2% precision); for faint or distant stars a Bayesian distance is the
    better choice (Bailer-Jones et al. 2021, AJ 161, 147).
    """
    d = 1000.0 / parallax_mas
    ra, dec = np.radians(ra_deg), np.radians(dec_deg)
    return (d * np.cos(dec) * np.cos(ra),
            d * np.cos(dec) * np.sin(ra),
            d * np.sin(dec))
