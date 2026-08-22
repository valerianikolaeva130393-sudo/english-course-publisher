from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONTENT_PATH = ROOT / "content" / "season1.json"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    content = json.loads(CONTENT_PATH.read_text(encoding="utf-8"))
    audio_paths = sorted(path for path in content["assets"] if path.startswith("audio/"))
    if len(audio_paths) != 52:
        raise SystemExit(f"Ожидалось 52 аудиофайла, найдено {len(audio_paths)}")
    for relative in audio_paths:
        path = ROOT / relative
        if not path.is_file():
            raise FileNotFoundError(relative)
        content["assets"][relative] = sha256(path)
    CONTENT_PATH.write_text(
        json.dumps(content, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print("Обновлены SHA-256 для 52 MP3.")


if __name__ == "__main__":
    main()
