"""Content-addressed artifact store under .archzero/artifacts/."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


class ArtifactStore:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def put_bytes(self, data: bytes, suffix: str = "") -> str:
        h = hashlib.sha256(data).hexdigest()
        name = f"{h}{suffix}"
        path = self.root / name
        if not path.exists():
            path.write_bytes(data)
        return h

    def put_text(self, text: str, suffix: str = ".md") -> str:
        return self.put_bytes(text.encode("utf-8"), suffix=suffix)

    def put_json(self, obj: Any) -> str:
        data = json.dumps(obj, indent=2, default=str).encode("utf-8")
        return self.put_bytes(data, suffix=".json")

    def put_file(self, src: Path) -> str:
        return self.put_bytes(src.read_bytes(), suffix=src.suffix)

    def path_for(self, digest: str, suffix: str = "") -> Path | None:
        if suffix:
            p = self.root / f"{digest}{suffix}"
            return p if p.exists() else None
        matches = list(self.root.glob(f"{digest}*"))
        return matches[0] if matches else None

    def get_text(self, digest: str) -> str | None:
        p = self.path_for(digest)
        if p is None:
            return None
        return p.read_text(encoding="utf-8")
