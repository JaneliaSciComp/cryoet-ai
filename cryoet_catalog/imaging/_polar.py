"""Semicircular polar plot of tilt angles.

Originally vendored from ``_render_tilt_angle_plot`` in
``aicryoet-tools/src/aicryoet_tools/dashboard/pages/cryoet.py`` at commit
``083ccec``, rewritten on the matplotlib OO API (``Figure() +
FigureCanvasAgg``) — never ``pyplot`` — so concurrent threadpool renders
don't share global state (plan §7.5).

``POLAR_RENDER_VERSION`` is bumped manually whenever the renderer changes
so the cache invalidates without per-file changes (plan §11.7).
"""
from __future__ import annotations

from io import BytesIO

import numpy as np
from matplotlib import cm
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.colors import Normalize
from matplotlib.figure import Figure

POLAR_RENDER_VERSION = 1


def render_polar_png(angles: list[float]) -> bytes:
    """Render a semicircular polar plot of tilt angles as PNG bytes.

    :param angles: Tilt angles in acquisition order, degrees.
    :return: PNG image bytes.
    """
    n = len(angles)
    if n == 0:
        raise ValueError("no tilt angles to plot")

    fig = Figure(figsize=(5, 3), dpi=200)
    canvas = FigureCanvasAgg(fig)
    ax = fig.add_subplot(111, projection="polar")

    # 0° tilt → π/2 in polar (pointing up).
    thetas = [np.radians(90 - a) for a in angles]

    cmap = cm.viridis
    colors = [cmap(i / max(n - 1, 1)) for i in range(n)]

    for theta, color in zip(thetas, colors):
        ax.plot([theta, theta], [0, 1], color=color, linewidth=2, solid_capstyle="round")

    # Semicircle: 0° to 180° polar = +90° to -90° tilt.
    ax.set_thetamin(0)
    ax.set_thetamax(180)
    ax.set_theta_direction(-1)
    ax.set_theta_offset(np.pi / 2)

    tick_positions = np.radians(np.arange(0, 181, 15))
    tick_labels = [f"{90 - int(np.degrees(t))}°" for t in tick_positions]
    ax.set_xticks(tick_positions)
    ax.set_xticklabels(tick_labels, fontsize=7)
    ax.set_ylim(0, 1.05)
    ax.set_yticks([])
    ax.set_title(f"Tilt Angles ({n} images)", fontsize=10, pad=10)

    sm = cm.ScalarMappable(cmap=cmap, norm=Normalize(1, n))
    cbar = fig.colorbar(sm, ax=ax, shrink=0.6, pad=0.08, aspect=15)
    cbar.set_label("Image #", fontsize=8)
    cbar.ax.tick_params(labelsize=7)

    fig.tight_layout()

    buf = BytesIO()
    canvas.print_png(buf)
    return buf.getvalue()
