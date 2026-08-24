from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONTENT_DIR = ROOT / "content"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    total = 0
    for content_path in sorted(CONTENT_DIR.glob("season*.json")):
        content = json.loads(content_path.read_text(encoding="utf-8"))
        asset_paths = sorted(content["assets"])
        audio_paths = [path for path in asset_paths if path.endswith(".mp3")]
        image_paths = [path for path in asset_paths if path.endswith(".png")]
        expected_audio = content["meta"]["audio_files"]
        expected_images = content["meta"]["image_files"]
        if len(audio_paths) != expected_audio:
            raise SystemExit(
                f"{content_path.name}: ожидалось {expected_audio} аудиофайлов, найдено {len(audio_paths)}"
            )
        if len(image_paths) != expected_images:
            raise SystemExit(
                f"{content_path.name}: ожидалось {expected_images} изображений, найдено {len(image_paths)}"
            )
        for relative in asset_paths:
            path = ROOT / relative
            if not path.is_file():
                raise FileNotFoundError(relative)
            content["assets"][relative] = sha256(path)
        content_path.write_text(
            json.dumps(content, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        total += len(asset_paths)
    print(f"Обновлены SHA-256 для {total} медиафайлов.")


if __name__ == "__main__":
    main()
