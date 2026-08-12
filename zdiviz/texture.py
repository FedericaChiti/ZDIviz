"""Rendering a B_r raster to an equirectangular PNG texture.

The only non-obvious choice here is the colour scale.  ZDI maps are published
with a diverging scale forced symmetric about zero, because the sign of B_r is
the physical quantity of interest -- field entering the surface versus leaving
it -- and an asymmetric scale would make a spot look stronger simply because
it happened to be the positive one.  So the limits are always +-max|B_r|.
"""

import matplotlib
import numpy as np
from PIL import Image

# Blue = negative B_r (field into the surface), red = positive (out of it).
# Near-universal convention in the ZDI literature.  The browser preview samples
# this same colormap for its polarity bar, so the legend cannot drift from the
# texture it describes.
COLORMAP = "RdBu_r"


# Sequential scale for the cluster point cloud, keyed on rotation period.
# Sequential, not diverging: period has no meaningful zero point to diverge
# about, unlike B_r.
PROT_COLORMAP = "viridis"


def _cmap():
    # matplotlib.colormaps is the supported accessor from 3.5 onwards;
    # cm.get_cmap was deprecated in 3.7 and removed in 3.9.
    return matplotlib.colormaps[COLORMAP]


def colormap_rgb(name, n=32):
    """Sample any matplotlib colormap as a list of (r, g, b) floats in 0-1."""
    return [tuple(float(c) for c in row[:3])
            for row in matplotlib.colormaps[name](np.linspace(0.0, 1.0, n))]


def symmetric_limit(grid):
    """The colour-scale limit: max|B_r| over the map, in gauss."""
    return float(np.nanmax(np.abs(grid)))


def colormap_stops(n=16):
    """Sample the colormap as `n` hex strings, negative end first.

    Used to build the preview's polarity scale bar from the same source as the
    textures rather than from a hand-picked approximation.
    """
    rgba = _cmap()(np.linspace(0.0, 1.0, n))
    return ["#%02x%02x%02x" % tuple(int(round(c * 255)) for c in row[:3])
            for row in rgba]


def to_png(grid, path, vmax=None):
    """Write an (nlat, nlon) B_r raster as an RGB equirectangular PNG.

    `grid` rows must run north -> south and columns longitude 0 -> 360, which
    is what an equirectangular texture sampler assumes.  Returns the symmetric
    limit actually used, in gauss, so the caller can report it.
    """
    vmax = symmetric_limit(grid) if vmax is None else float(vmax)
    if vmax <= 0:
        raise ValueError("map is identically zero - nothing to scale")

    # Normalise to 0..1 with 0.5 pinned at B_r = 0, then apply the colormap.
    normed = np.clip((grid + vmax) / (2.0 * vmax), 0.0, 1.0)
    rgb = (_cmap()(normed)[:, :, :3] * 255).astype(np.uint8)

    path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(rgb).save(path)
    return vmax
