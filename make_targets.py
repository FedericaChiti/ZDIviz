#!/usr/bin/env python3
"""Derive `targets.csv` from the full research catalogue.

    python make_targets.py full_sample_dataframe.csv

The working catalogue behind this project carries ~100 columns of analysis --
X-ray luminosities, mass-loss rates, torques, Rossby numbers -- none of which
this pipeline reads.  `targets.csv` is the nine-column subset that it does,
and is what ships in the repository.

The column list is imported from `zdiviz.io`, not restated here, so the
published file cannot drift out of step with what the loader expects.
"""

import argparse
import csv
from pathlib import Path

from zdiviz.io import CATALOG_COLUMNS

ROOT = Path(__file__).parent


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("source", nargs="?", default=ROOT / "full_sample_dataframe.csv",
                   type=Path, help="the full catalogue to subset")
    p.add_argument("-o", "--out", default=ROOT / "targets.csv", type=Path)
    args = p.parse_args()

    keep = list(CATALOG_COLUMNS)          # source column names, in order
    with open(args.source, newline="") as f:
        rows = list(csv.DictReader(f))

    missing = [c for c in keep if c not in (rows[0] if rows else {})]
    if missing:
        raise SystemExit(f"{args.source.name} is missing required columns: {missing}")

    with open(args.out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=keep, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)

    dropped = len(rows[0]) - len(keep) if rows else 0
    print(f"{args.out.name}: {len(rows)} rows, {len(keep)} columns "
          f"({dropped} columns dropped)")
    print("kept: " + ", ".join(keep))


if __name__ == "__main__":
    main()
