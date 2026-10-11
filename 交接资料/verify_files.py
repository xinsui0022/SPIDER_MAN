"""Verify the complete handoff bytes, including downloaded Git LFS objects."""
from pathlib import Path
import hashlib
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "交接资料" / "FILES_MANIFEST.json"


def digest(path):
    result = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            result.update(chunk)
    return result.hexdigest()


def main():
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    errors = []
    for entry in manifest["files"]:
        path = (ROOT / entry["path"]).resolve()
        if ROOT not in path.parents:
            errors.append({"path": entry["path"], "reason": "path_outside_repository"})
        elif not path.is_file():
            errors.append({"path": entry["path"], "reason": "missing"})
        elif path.stat().st_size != entry["bytes"] or digest(path) != entry["sha256"]:
            errors.append({"path": entry["path"], "reason": "size_or_sha256_differs"})
    print(json.dumps({"status": "verified" if not errors else "mismatch",
                      "checked_files": len(manifest["files"]),
                      "errors": errors, "hint": "Run git lfs pull if an LFS file differs."}, ensure_ascii=False))
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
