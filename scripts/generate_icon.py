"""Generate assets/kotakow.ico using only Python's standard library (CI-safe)."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from kotakow.assets import generate_ico_file


def main() -> None:
    out = ROOT / "assets" / "kotakow.ico"
    generate_ico_file(out)
    print(f"Generated icon: {out}")


if __name__ == "__main__":
    main()
