"""Superseded — the tracker PWA icons now come from the shared HoopTracks brand
mark in tools/make_brand.py (which writes BOTH the web favicon and the three
tracker icons from one source, so they can't drift). This shim stays so the old
`python tracker/make_icons.py` command keeps working.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools.make_brand import write_all

if __name__ == "__main__":
    write_all()
