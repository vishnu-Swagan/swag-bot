"""Build a Chrome Web Store zip from ``extension/dist``.

The unpacked build keeps the ``key`` field so the extension id stays stable
for native messaging. The store rejects that field and assigns its own id,
so this script strips it. After publishing, register the store id:

    swag extension install --extension-id <id from chrome://extensions>

Usage, from ``extension/``:

    npm run package
"""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"
OUT_DIR = Path(__file__).resolve().parent / "dist"


def main() -> None:
    if not (DIST / "manifest.json").is_file():
        raise SystemExit("extension/dist is missing. Run npm run build first.")
    manifest = json.loads((DIST / "manifest.json").read_text(encoding="utf-8"))
    manifest.pop("key", None)
    version = str(manifest.get("version", "0.0.0"))
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    destination = OUT_DIR / f"swag-bot-{version}.zip"
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(DIST.rglob("*")):
            if not path.is_file() or path.suffix == ".map":
                continue
            relative = path.relative_to(DIST).as_posix()
            if relative == "manifest.json":
                archive.writestr(
                    "manifest.json",
                    json.dumps(manifest, indent=2) + "\n",
                )
                continue
            archive.write(path, relative)
    with zipfile.ZipFile(destination) as archive:
        packed = json.loads(archive.read("manifest.json"))
    if "key" in packed:
        raise SystemExit("store zip still contains manifest.key")
    print(destination)


if __name__ == "__main__":
    main()
