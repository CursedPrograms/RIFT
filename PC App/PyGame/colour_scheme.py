"""
RIFT colour scheme for the Python UIs in this folder.

Reads colour_scheme.xml from the repo root (two levels up), so the PyGame
scanner and the test dashboards match the fleet dashboard. Edit the XML and
restart the program. A missing or unreadable file/role falls back to the
built-in default for that colour.
"""

import os
import re

DEFAULTS = {
    "background": "#0A0B07",
    "panel": "#14160F",
    "border": "#2A2E1F",
    "divider": "#1E2117",
    "text": "#F1F5E6",
    "text_sec": "#9DA38C",
    "text_dim": "#5E6352",
    "accent": "#A3E635",
    "accent_hover": "#BEF264",
    "accent2": "#84CC16",
    "accent3": "#D9F99D",
    "button_hover_bg": "#1C2112",
    "danger_bg": "#210F0D",
    "online": "#A3E635",
    "offline": "#E24B4A",
}

XML_PATH = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "colour_scheme.xml"))


def load():
    """Returns {role: "#RRGGBB"} for every role, file values over defaults."""
    colours = dict(DEFAULTS)
    try:
        with open(XML_PATH, encoding="utf-8") as f:
            colours.update(re.findall(r'name="(\w+)"\s+value="(#[0-9A-Fa-f]{6})"', f.read()))
    except OSError:
        pass
    return colours


def rgb(hex_colour):
    """"#A3E635" -> (163, 230, 53), for pygame."""
    h = hex_colour.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def css_root(colours=None):
    """The scheme as a CSS :root block, "_" in role names written as "-"."""
    colours = colours or load()
    return ":root {" + " ".join(f"--{k.replace('_', '-')}: {v};" for k, v in colours.items()) + "}"
