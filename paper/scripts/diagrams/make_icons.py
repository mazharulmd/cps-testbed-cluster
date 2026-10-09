"""Convert Lucide icons (ISC license, see icons/LICENSE-lucide) to coloured PDFs for the TikZ diagrams.

Usage: python make_icons.py PATH_TO/lucide-static/icons
(npm pack lucide-static@0.460.0 and unpack it to get the icons directory)
"""
import os
import sys

import cairosvg

SRC = sys.argv[1]
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "icons")
ICONS = {  # icon name: stroke colour
    "zap": "#1f5fa8", "cpu": "#1f5fa8", "activity": "#0f7b6c", "radio-tower": "#0f7b6c",
    "database": "#0f7b6c", "gauge": "#b3541e", "shield-check": "#b3541e", "bug": "#c0392b",
    "eye": "#555555", "server": "#444444", "layout-dashboard": "#6a3d9a", "users": "#6a3d9a",
    "list-ordered": "#444444", "hard-drive": "#444444",
}
os.makedirs(OUT, exist_ok=True)
for name, colour in ICONS.items():
    svg = open(os.path.join(SRC, name + ".svg")).read().replace("currentColor", colour)
    cairosvg.svg2pdf(bytestring=svg.encode(), write_to=os.path.join(OUT, name + ".pdf"),
                     output_width=96, output_height=96)
print(len(ICONS), "icons ->", OUT)
