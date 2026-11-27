"""Chart style from the Stephany Alves Design System (tokens.json v1.1.0).

Colours are the design system's data-viz tokens; fonts are its three families. Use
`brand.style()` as a matplotlib context so charts match the portfolio, slides and dashboards:

    with brand.style():
        fig, ax = plt.subplots()

Rules carried over from the system: rows-only gridlines, labelled axes with a zero baseline,
one highlighted series with the others in the context grey, and colour by business meaning
(favourable / unfavourable), never by sign alone.
"""

from contextlib import contextmanager

import matplotlib as mpl
from cycler import cycler

# Neutrals and ink
IVORY = "#F5F4EC"  # surface-page
WHITE = "#FFFFFF"  # surface-card
NEAR_BLACK = "#101714"  # text-primary
GRAY_700 = "#454C48"  # text-secondary
FOREST_900 = "#0B302B"  # text-brand

# Data-viz tokens (dv-*)
CAT = {
    1: "#1E5246",  # forest
    2: "#8FA99D",  # sage
    3: "#4F6D8A",  # slate blue
    4: "#C49A45",  # ochre
    5: "#B4694A",  # clay
    6: "#35D58A",  # Signal, reserved for the highlighted series
    7: "#7A6A85",  # muted plum
    8: "#5E6561",  # gray
}
CATEGORICAL = [CAT[i] for i in (1, 2, 3, 4, 5, 7, 8)]  # cycle order; Signal kept for highlights
FAVORABLE = "#1F7A4F"
UNFAVORABLE = "#A63A2A"
NEUTRAL = "#858B86"
TARGET = "#101714"
BASELINE = "#BDC1BB"
GRIDLINE = "#E8E9E5"
AXIS = "#5E6561"
HIGHLIGHT = "#35D58A"
CONTEXT = "#D6D8D2"

SERIF = ["Newsreader", "Georgia", "Times New Roman", "serif"]
SANS = ["IBM Plex Sans", "Segoe UI", "Helvetica Neue", "Arial", "sans-serif"]
MONO = ["IBM Plex Mono", "Consolas", "DejaVu Sans Mono", "monospace"]

RC = {
    "figure.facecolor": IVORY,
    "axes.facecolor": IVORY,
    "savefig.facecolor": IVORY,
    "font.family": "sans-serif",
    "font.sans-serif": SANS,
    "font.monospace": MONO,
    "font.size": 10,
    "text.color": NEAR_BLACK,
    "axes.titlesize": 12,
    "axes.titleweight": "medium",
    "axes.titlelocation": "left",
    "axes.titlepad": 12,
    "axes.labelsize": 9,
    "axes.labelcolor": GRAY_700,
    "axes.edgecolor": AXIS,
    "axes.linewidth": 0.8,
    "axes.spines.top": False,
    "axes.spines.right": False,
    "axes.grid": True,
    "axes.grid.axis": "y",
    "axes.axisbelow": True,
    "axes.prop_cycle": cycler(color=CATEGORICAL),
    "grid.color": GRIDLINE,
    "grid.linewidth": 0.8,
    "xtick.color": AXIS,
    "ytick.color": AXIS,
    "xtick.labelsize": 8,
    "ytick.labelsize": 8,
    "xtick.labelcolor": AXIS,
    "ytick.labelcolor": AXIS,
    "legend.frameon": False,
    "legend.fontsize": 8,
    "lines.linewidth": 1.5,
    "patch.linewidth": 0,
}


def mono_ticks(ax) -> None:
    """Axis tick labels in the mono face, as the system sets them for axis labels."""
    for label in ax.get_xticklabels() + ax.get_yticklabels():
        label.set_fontfamily(MONO)


@contextmanager
def style():
    with mpl.rc_context(RC):
        yield
