from __future__ import annotations

from pathlib import Path


def main() -> int:
    root = Path(__file__).resolve().parents[1]

    replacements = [
        ("ah_recommendation_system", "ah_recommendation_system"),
        ("D:/Code/AH_analyse/ah_recommendation_system", "D:/Code/AH_analyse/ah_recommendation_system"),
        ("D:\\Code\\test\\tools\\ah_recommendation_system", "D:\\Code\\AH_analyse\\ah_recommendation_system"),
    ]

    changed = 0
    scanned = 0

    for p in root.rglob("*.py"):
        # Skip caches
        if "__pycache__" in p.parts:
            continue
        scanned += 1
        try:
            text = p.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            # Best effort: skip non-utf8
            continue

        new_text = text
        for old, new in replacements:
            new_text = new_text.replace(old, new)

        if new_text != text:
            p.write_text(new_text, encoding="utf-8")
            changed += 1

    print(f"scanned={scanned} changed={changed} root={root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
