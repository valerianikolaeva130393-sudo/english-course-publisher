#!/usr/bin/env bash
set -euo pipefail

expected_count="$(python - <<'PY'
import json
from pathlib import Path

print(sum(
    json.loads(path.read_text(encoding="utf-8"))["meta"]["audio_files"]
    for path in Path("content").glob("season*.json")
))
PY
)"
repaired_count=0
reencoded_count=0
staging_dir="$(mktemp -d)"
trap 'rm -rf "$staging_dir"' EXIT

while IFS= read -r -d '' source_file; do
  relative_file="${source_file#./}"
  target_file="$staging_dir/$relative_file"
  mkdir -p "$(dirname "$target_file")"

  encoder="$(ffprobe -v error -show_entries format_tags=encoder -of default=noprint_wrappers=1:nokey=1 "$source_file")"
  if [[ "$encoder" == Lavf* ]]; then
    cp "$source_file" "$target_file"
    repaired_count=$((repaired_count + 1))
    continue
  fi

  before_duration="$(ffprobe -v error -show_entries format=duration -of default=noprint_wrappers=1:nokey=1 "$source_file")"

  ffmpeg -nostdin -hide_banner -loglevel error -y \
    -i "$source_file" \
    -map 0:a:0 \
    -map_metadata -1 \
    -vn \
    -c:a libmp3lame \
    -b:a 128k \
    -ar 44100 \
    -ac 1 \
    -id3v2_version 3 \
    -write_id3v1 1 \
    -write_xing 1 \
    "$target_file"

  after_duration="$(ffprobe -v error -show_entries format=duration -of default=noprint_wrappers=1:nokey=1 "$target_file")"
  python -c 'import sys; before=float(sys.argv[1]); after=float(sys.argv[2]); assert before > 0 and after > 0 and abs(before-after) <= 0.15, (sys.argv[3], before, after)' "$before_duration" "$after_duration" "$relative_file"
  repaired_count=$((repaired_count + 1))
  reencoded_count=$((reencoded_count + 1))
done < <(find audio -type f -name '*.mp3' -print0 | sort -z)

if [ "$repaired_count" -ne "$expected_count" ]; then
  echo "ОШИБКА: найдено $repaired_count MP3 вместо $expected_count" >&2
  exit 1
fi

while IFS= read -r -d '' repaired_file; do
  relative_file="${repaired_file#"$staging_dir/"}"
  mv "$repaired_file" "$relative_file"
done < <(find "$staging_dir/audio" -type f -name '*.mp3' -print0 | sort -z)

if [ "$reencoded_count" -eq 0 ]; then
  echo "УСПЕХ: все $repaired_count MP3 уже совместимы."
else
  echo "УСПЕХ: исправлены все $reencoded_count MP3."
fi
