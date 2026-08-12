#!/usr/bin/env python3
"""Build every output from the target catalogue and the ZDI maps.

    python build.py

Reads  : full_sample_dataframe.csv, data/maps/<star>_<year>.dat
Writes : build/textures/*.png      equirectangular B_r textures, 2048x1024
         build/hyades.speck        Digital Universe point catalogue, parsecs
         build/hyades.label        labels for the point cloud
         build/prot.cmap           colour table for the point cloud
         build/zdi_stars.asset     one RenderableSphere per mapped star
         build/hyades_cloud.asset  the cluster as a point cloud
         build/index.html          browser preview (open this on macOS)
"""

import argparse
import shutil
from pathlib import Path

from zdiviz import io, texture, speck, assets, preview

ROOT = Path(__file__).parent
BUILD = ROOT / "build"

# Texture resolution. 2048x1024 is 2:1 as an equirectangular map must be, and
# oversamples the ~77-cell equatorial resolution of the inversion by a wide
# margin -- the limit here is the data, not the raster.
TEX_NLON, TEX_NLAT = 2048, 1024


def main():
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--targets", type=Path, default=ROOT / "targets.csv")
    p.add_argument("--maps", type=Path, default=ROOT / "data" / "maps")
    p.add_argument("--out", type=Path, default=BUILD)
    p.add_argument("--exaggeration", type=float, default=3.0e5,
                   help="stellar radius scale factor (default: 3e5). "
                        "True radii are ~1e-8 of interstellar distances, so "
                        "unscaled spheres are sub-pixel. Stated in every output.")
    args = p.parse_args()

    # 1. Fresh output tree ------------------------------------------------
    if args.out.exists():
        shutil.rmtree(args.out)
    (args.out / "textures").mkdir(parents=True)

    # 2. Target catalogue -------------------------------------------------
    targets, skipped = io.load_targets(args.targets)
    stars = io.unique_stars(targets)
    print(f"catalogue : {len(targets)} rows -> {len(stars)} unique stars")
    for label, reason in skipped:
        print(f"  skipped {label}: {reason}")

    # 3. One texture per (star, epoch) that has a map on disk -------------
    found = io.discover_maps(args.maps)
    bound, problems = io.match_maps(targets, found)
    print(f"maps      : {len(found)} files in {args.maps}, {len(bound)} bound to rows")
    # A map that cannot be tied to a catalogue row is a real inconsistency,
    # not a warning to bury -- name the file and the reason.
    for name, reason in problems:
        print(f"  ! {name}: {reason}")

    entries = []
    for target in sorted(targets, key=lambda t: (int(t["star"]) if t["star"].isdigit()
                                                 else 1 << 30, t["epoch"])):
        path = bound.get((target["star"], target["epoch"]))
        if path is None:
            continue
        grid = io.load_map(path, component="br", nlon=TEX_NLON, nlat=TEX_NLAT)
        png = f"{target['slug']}_{target['epoch']}_br.png"
        vmax = texture.to_png(grid, args.out / "textures" / png)
        entries.append((target, png, vmax))
        print(f"  {target['name']:<16} {target['epoch']}  "
              f"scale +/-{vmax:6.1f} G   mean|Br| {abs(grid).mean():5.1f} G")

    matched = {(t["star"], t["epoch"]) for t, _, _ in entries}
    if not entries:
        raise SystemExit(
            f"No usable maps. Expected files named <Star_Name>_<Obs_Year>.dat "
            f"in {args.maps}.")

    # 4. Point catalogue --------------------------------------------------
    speck.write_speck(stars, args.out / "hyades.speck", mapped_keys=matched)
    speck.write_label(stars, args.out / "hyades.label")
    speck.write_cmap(args.out / "prot.cmap",
                     texture.colormap_rgb(texture.PROT_COLORMAP, 32))
    print(f"speck     : {len(stars)} points, "
          f"{len(speck.DATAVARS) + 1} datavars, parsecs")

    # 5. OpenSpace scene --------------------------------------------------
    periods = [s["prot_d"] for s in stars if s["prot_d"] is not None]
    assets.write_star_assets(entries, args.out, exaggeration=args.exaggeration)
    assets.write_cloud_asset(args.out, n_points=len(stars),
                             prot_range=(min(periods), max(periods)))
    print(f"assets    : zdi_stars.asset ({len(entries)} spheres), "
          f"hyades_cloud.asset ({assets.POINT_CLOUD_RENDERABLE})")

    # 6. Browser preview --------------------------------------------------
    preview.write_preview(entries, stars, args.out / "index.html",
                          exaggeration=args.exaggeration)
    print(f"preview   : index.html")
    print(f"\nradius exaggeration {args.exaggeration:.6g}x "
          f"(positions and distances are true)")
    print(f"open {args.out / 'index.html'}")


if __name__ == "__main__":
    main()
