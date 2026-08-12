"""Tests for the ZDI pipeline.

The important one is `test_surface_averages_match_catalogue`: it re-derives the
mean field strength from every ingested map and checks it against the value
published in the catalogue. That single test covers the file format, the unit
conversion, the grid interpretation and the component ordering all at once --
if any of them were wrong, the numbers would not agree.

    pytest -q
"""

import csv
import math
from pathlib import Path

import numpy as np
import pytest

from zdiviz import assets, io, texture

ROOT = Path(__file__).parent.parent
MAPS = ROOT / "data" / "maps"
TARGETS = ROOT / "targets.csv"
# The full catalogue is not published; these tests fall back to targets.csv and
# skip the catalogue cross-check when it is absent.
FULL = ROOT / "full_sample_dataframe.csv"


@pytest.fixture(scope="module")
def bound():
    targets, _ = io.load_targets(TARGETS)
    matched, problems = io.match_maps(targets, io.discover_maps(MAPS))
    assert not problems, f"maps that could not be bound to a row: {problems}"
    return matched


# --- the catalogue cross-check -------------------------------------------

@pytest.mark.skipif(not FULL.exists(),
                    reason="full_sample_dataframe.csv is not published")
def test_surface_averages_match_catalogue(bound):
    """Mean |B| and mean |B_r| recomputed from each map match the catalogue.

    The inversion grid is equal-area, so every cell carries the same weight and
    a plain unweighted mean over cells *is* the surface average -- no
    cos(latitude) weighting. Tolerance is 1%: the catalogue values are rounded
    to two decimals, which alone is a few tenths of a percent on the smaller
    fields.
    """
    published = {(r["Star_Name"], r["Obs_Year"]): r
                 for r in csv.DictReader(open(FULL))}
    assert bound, "no maps found"

    for (star, epoch), path in sorted(bound.items()):
        raw = io.read_invers_dat(path)
        br = np.concatenate(raw["br"])
        blat = np.concatenate(raw["blat"])
        bphi = np.concatenate(raw["bphi"])

        got_b = np.mean(np.sqrt(br**2 + blat**2 + bphi**2))
        got_br = np.mean(np.abs(br))
        row = published[(star, epoch)]

        assert got_b == pytest.approx(float(row["B_surf_av"]), rel=0.01), \
            f"{star}/{epoch}: mean|B|"
        assert got_br == pytest.approx(float(row["Br"]), rel=0.01), \
            f"{star}/{epoch}: mean|Br|"


# --- map format and resampling -------------------------------------------

def test_native_grid_is_equal_area(bound):
    """Latitude bands are evenly spaced and cell counts follow cos(latitude)."""
    raw = io.read_invers_dat(next(iter(bound.values())))
    lat = raw["lat"]
    spacing = np.diff(lat)
    # atol covers the file's own rounding: latitudes are printed to 3 decimals,
    # so consecutive gaps come out as 4.737 or 4.736.
    assert np.allclose(spacing, spacing[0], atol=2e-3), \
        "latitude bands are not evenly spaced"
    assert spacing[0] == pytest.approx(180.0 / len(lat), abs=2e-3)

    counts = np.array([len(x) for x in raw["lon"]])
    # Cell width in longitude times cos(lat) should be near-constant.
    area = np.cos(np.radians(lat)) / counts
    assert area.max() / area.min() < 1.35, "cells are not close to equal-area"


def test_longitudes_are_half_offset_and_ascending(bound):
    """Each band's longitudes are (j + 0.5) * 360/n, ascending."""
    raw = io.read_invers_dat(next(iter(bound.values())))
    for lon in raw["lon"]:
        expected = (np.arange(len(lon)) + 0.5) * 360.0 / len(lon)
        assert np.allclose(lon, expected, atol=1e-3)


def test_resampling_preserves_the_surface_average(bound):
    """Area-weighting the raster recovers the equal-area mean to within 2%.

    The raster oversamples the poles, so it must be cos(latitude)-weighted --
    unlike the native grid, which must not be.
    """
    for path in list(bound.values())[:5]:
        raw = io.read_invers_dat(path)
        native = np.mean(np.abs(np.concatenate(raw["br"])))

        grid = io.resample_equirectangular(raw, "br", nlon=512, nlat=256)
        lat = 90.0 - (np.arange(256) + 0.5) * 180.0 / 256
        w = np.cos(np.radians(lat))[:, None]
        weighted = (np.abs(grid) * w).sum() / (w.sum() * grid.shape[1])

        assert weighted == pytest.approx(native, rel=0.02), path.name


def test_raster_orientation_is_north_at_row_zero(bound):
    """Row 0 of the raster is the north pole, matching image and texture order."""
    for path in list(bound.values())[:5]:
        raw = io.read_invers_dat(path)
        grid = io.resample_equirectangular(raw, "br", nlon=256, nlat=128)
        assert grid[0].mean() == pytest.approx(raw["br"][-1].mean(), abs=1.0)
        assert grid[-1].mean() == pytest.approx(raw["br"][0].mean(), abs=1.0)


def test_kilogauss_is_converted_to_gauss(bound):
    """Field values are gauss, i.e. 1000x the raw file column."""
    path = next(iter(bound.values()))
    raw_col = np.loadtxt(path, skiprows=1)[:, 3]
    parsed = np.concatenate(io.read_invers_dat(path)["br"])
    assert np.isclose(np.abs(parsed).max(), np.abs(raw_col).max() * 1000.0)


# --- filename conventions -------------------------------------------------

@pytest.mark.parametrize("stem,expected", [
    ("409_2022_map", ("409", "2022")),   # two-epoch star, year explicit
    ("133_map",      ("133", None)),     # single-epoch star, year omitted
    ("409_2022",     ("409", "2022")),
    ("68",           ("68", None)),
])
def test_parse_map_name(stem, expected):
    assert io.parse_map_name(stem) == expected


def test_ambiguous_epoch_is_refused_not_guessed():
    """A year-less filename for a two-epoch star must be reported, not guessed."""
    targets, _ = io.load_targets(TARGETS)
    two_epoch = next(t["star"] for t in targets
                     if sum(x["star"] == t["star"] for x in targets) > 1)
    found = {(two_epoch, None): Path(f"{two_epoch}_map.dat")}
    matched, problems = io.match_maps(targets, found)
    assert not matched
    assert problems and "omits the epoch" in problems[0][1]


# --- geometry -------------------------------------------------------------

@pytest.mark.parametrize("ra,dec,inc", [
    (67.97, 15.50, 42.07), (0.0, 0.0, 90.0), (120.0, -40.0, 10.0),
    (300.0, 80.0, 65.0), (45.0, 90.0, 30.0), (210.0, -89.5, 75.0),
])
def test_spin_axis_makes_the_right_angle_with_the_line_of_sight(ra, dec, inc):
    """The axis sits `inc` degrees from the direction back to the observer."""
    axis, _ = assets.spin_axis_vector(ra, dec, inc)
    r = np.array([math.cos(math.radians(dec)) * math.cos(math.radians(ra)),
                  math.cos(math.radians(dec)) * math.sin(math.radians(ra)),
                  math.sin(math.radians(dec))])
    got = math.degrees(math.acos(np.clip(np.dot(axis, -r), -1, 1)))
    assert got == pytest.approx(inc, abs=1e-6)
    assert np.linalg.norm(axis) == pytest.approx(1.0)


@pytest.mark.parametrize("ra,dec,inc", [
    (67.97, 15.50, 42.07), (0.0, 0.0, 90.0), (300.0, 80.0, 65.0),
    (45.0, 90.0, 30.0), (210.0, -89.5, 75.0),
])
def test_euler_angles_reproduce_the_axis(ra, dec, inc):
    """Rebuilding R = Rx(a)Ry(b)Rz(c) puts its third column on the spin axis.

    This is the check that the Euler convention written into the .asset files
    means what the rest of the code assumes it means.
    """
    def rx(t): c, s = math.cos(t), math.sin(t); return np.array([[1,0,0],[0,c,-s],[0,s,c]])
    def ry(t): c, s = math.cos(t), math.sin(t); return np.array([[c,0,s],[0,1,0],[-s,0,c]])
    def rz(t): c, s = math.cos(t), math.sin(t); return np.array([[c,-s,0],[s,c,0],[0,0,1]])

    axis, _ = assets.spin_axis_vector(ra, dec, inc)
    a, b, c = assets.spin_axis_rotation(ra, dec, inc)
    R = rx(a) @ ry(b) @ rz(c)
    assert np.allclose(R[:, 2], axis, atol=1e-9)
    assert np.linalg.det(R) == pytest.approx(1.0)          # a rotation, not a reflection


def test_distance_and_cartesian_position_are_consistent():
    """|xyz| equals 1000/parallax, and the direction round-trips to RA/Dec."""
    ra, dec, plx = 67.969, 15.499, 21.8718
    x, y, z = io.icrs_to_cartesian_pc(ra, dec, plx)
    assert math.sqrt(x*x + y*y + z*z) == pytest.approx(1000.0 / plx)
    assert math.degrees(math.atan2(y, x)) % 360 == pytest.approx(ra, abs=1e-6)
    assert math.degrees(math.asin(z / (1000.0 / plx))) == pytest.approx(dec, abs=1e-6)


# --- catalogue handling ---------------------------------------------------

def test_rows_missing_required_fields_are_skipped_not_patched(tmp_path):
    """A row without a parallax is dropped and reported, never filled in."""
    p = tmp_path / "t.csv"
    p.write_text(
        "Star_Name,Obs_Year,RAdeg,DEdeg,Plx,Radius_Rsun_final,Prot,new_i,Teff_bprp\n"
        "1,2020,10.0,20.0,20.0,0.8,10.0,45.0,4500\n"     # complete
        "2,2020,10.0,20.0,,0.8,10.0,45.0,4500\n"         # no parallax
        "3,2020,10.0,20.0,-5.0,0.8,10.0,45.0,4500\n")    # negative parallax
    targets, skipped = io.load_targets(p)
    assert [t["star"] for t in targets] == ["1"]
    assert len(skipped) == 2
    assert all(t["parallax_mas"] > 0 for t in targets)


def test_optional_fields_may_be_absent(tmp_path):
    """Missing Prot/inclination/Teff are None, not zero or a placeholder."""
    p = tmp_path / "t.csv"
    p.write_text(
        "Star_Name,Obs_Year,RAdeg,DEdeg,Plx,Radius_Rsun_final,Prot,new_i,Teff_bprp\n"
        "1,2020,10.0,20.0,20.0,0.8,,,\n")
    targets, _ = io.load_targets(p)
    assert targets[0]["prot_d"] is None
    assert targets[0]["inclination_deg"] is None
    assert targets[0]["teff_k"] is None


# --- texture --------------------------------------------------------------

def test_colour_scale_is_symmetric_about_zero():
    """A map with a strong positive tail still scales to +-max|B_r|."""
    grid = np.concatenate([np.full((10, 10), -5.0), np.full((10, 10), 40.0)])
    assert texture.symmetric_limit(grid) == 40.0


def test_texture_is_2to1_and_zero_maps_to_the_colormap_centre(tmp_path):
    from PIL import Image
    grid = np.zeros((64, 128))
    grid[0, 0] = 10.0
    grid[-1, -1] = -10.0
    out = tmp_path / "t.png"
    vmax = texture.to_png(grid, out)
    assert vmax == 10.0

    im = np.asarray(Image.open(out))
    assert im.shape[1] == 2 * im.shape[0], "not 2:1"
    # A zero cell must land on the colormap's midpoint, the same colour for
    # any map -- that is what makes the scale comparable across a single star.
    mid = np.asarray(texture._cmap()(0.5)[:3]) * 255
    assert np.allclose(im[32, 64], mid, atol=1)
