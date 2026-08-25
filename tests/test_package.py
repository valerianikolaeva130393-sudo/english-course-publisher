from __future__ import annotations

import hashlib
import html
import json
import re
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from publisher import due_events, load_all_content, validate_content  # noqa: E402


SEASON1_PATH = ROOT / "content" / "season1.json"
SEASON2_PATH = ROOT / "content" / "season2.json"
SEASON3_PATH = ROOT / "content" / "season3.json"
SEASON1_SOURCE = ROOT / "source" / "Английский через истории — Сезон 1 — Все публикации — ФИНАЛ.docx"
SEASON2_SOURCE = ROOT / "source" / "Сезон 2_Все публикации_Английский через истории_ФИНАЛ.docx"
SEASON3_SOURCE = ROOT / "source" / "Сезон 3_Все публикации_Английский через истории_ФИНАЛ.docx"
SEASON1_NO_PRACTICE_AUDIO = {9, 12, 18, 19, 22, 23, 25, 26, 29}
SEASON2_NO_PRACTICE_AUDIO = {4, 9, 12, 18, 19, 22, 23, 25, 26, 29}
SEASON3_NO_PRACTICE_AUDIO = {9, 12, 18, 19, 22, 23, 25, 26, 29}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def plain_length(value: str) -> int:
    return len(html.unescape(re.sub(r"<[^>]+>", "", value)))


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def event_map(content: dict) -> dict[str, dict]:
    return {event["id"]: event for event in content["events"]}


def verify_common(content: dict, expected_counts: dict[str, int]) -> None:
    validate_content(content)
    events = content["events"]
    counts = Counter(step["type"] for event in events for step in event["steps"])
    assert counts == expected_counts, counts

    for relative, expected_hash in content["assets"].items():
        path = ROOT / relative
        assert path.is_file(), relative
        assert path.stat().st_size > 10_000, relative
        assert sha256(path) == expected_hash, relative

    messages = [
        step["text"]
        for event in events
        for step in event["steps"]
        if step["type"] == "message"
    ]
    assert all(plain_length(text) <= 4096 for text in messages)
    assert all("Telegram Quiz Poll" not in text for text in messages)
    assert all("📸 ФОТО" not in text for text in messages)
    assert all("🎧 Аудио:" not in text for text in messages)
    assert all("||" not in text for text in messages)

    audio_steps = [
        step
        for event in events
        for step in event["steps"]
        if step["type"] == "audio"
    ]
    assert all(step.get("performer") == "Английский через истории" for step in audio_steps)
    assert all(step.get("title") for step in audio_steps)
    assert all("caption" not in step for step in audio_steps)

    polls = [
        step
        for event in events
        for step in event["steps"]
        if step["type"] == "poll"
    ]
    for poll in polls:
        assert 1 <= len(poll["question"]) <= 300, poll["question"]
        assert 2 <= len(poll["options"]) <= 12
        assert len(poll["correct_option_ids"]) == 1
        assert 0 <= poll["correct_option_ids"][0] < len(poll["options"])
        assert all(1 <= len(option) <= 100 for option in poll["options"])


def verify_daily_events(
    content: dict,
    *,
    season: int,
    days: int,
    event_prefix: str,
    no_practice_audio: set[int],
) -> None:
    events = event_map(content)
    for day in range(1, days + 1):
        morning = events[f"{event_prefix}day{day:02d}_morning"]
        practice = events[f"{event_prefix}day{day:02d}_practice"]

        expected_morning_order = (
            ["photo", "message", "audio"]
            if day in {7, 14, 21, 28}
            else ["message", "audio"]
        )
        assert [step["type"] for step in morning["steps"]] == expected_morning_order

        morning_audio = next(step for step in morning["steps"] if step["type"] == "audio")
        assert morning_audio["title"] == f"Сезон {season} · День {day} · Утро"

        has_practice_audio = any(step["type"] == "audio" for step in practice["steps"])
        assert has_practice_audio == (day not in no_practice_audio), day
        expected_practice_order = (
            ["message", "audio", "poll"]
            if has_practice_audio
            else ["message", "poll"]
        )
        assert [step["type"] for step in practice["steps"]] == expected_practice_order
        if has_practice_audio:
            practice_audio = next(step for step in practice["steps"] if step["type"] == "audio")
            assert practice_audio["title"] == f"Сезон {season} · День {day} · Практика"

        morning_message = next(step["text"] for step in morning["steps"] if step["type"] == "message")
        lines = morning_message.splitlines()
        plain_header = html.unescape(re.sub(r"<[^>]+>", "", lines[0]))
        assert plain_header == f"🌱 Сезон {season} • День {day}"
        assert lines[1] and not lines[1].isspace()
        assert not lines[2].strip()
        assert "<u>🎬 История</u>\n" in morning_message
        assert "\n\n<u>🗣 " in morning_message or "\n\n<u>⭐ Главная задача</u>" in morning_message


def verify_bold_dialogue_speakers(content: dict) -> None:
    speaker_line = re.compile(r"^(👩|👨|🧑) <b>[^:\n]+:</b>$")
    dialogue_labels: list[str] = []
    for event in content["events"]:
        for step in event["steps"]:
            if step["type"] != "message":
                continue
            for line in step["text"].splitlines():
                plain_line = re.sub(r"<[^>]+>", "", line)
                if plain_line.startswith(("👩 ", "👨 ", "🧑 ")):
                    dialogue_labels.append(line)
    assert dialogue_labels
    assert all(speaker_line.fullmatch(line) for line in dialogue_labels), dialogue_labels[:5]


def verify_season1(content: dict) -> None:
    meta = content["meta"]
    assert meta["season"] == 1
    assert meta["timezone"] == "Europe/Moscow"
    assert meta["channel"] == "@english_story_a1a2"
    assert meta["start_date"] == "2026-09-01"
    assert meta["end_date"] == "2026-09-30"
    assert len(content["events"]) == 62
    verify_common(content, {"message": 61, "audio": 52, "photo": 5, "poll": 37})
    assert sha256(SEASON1_SOURCE) == meta["source_sha256"]
    verify_daily_events(
        content,
        season=1,
        days=30,
        event_prefix="",
        no_practice_audio=SEASON1_NO_PRACTICE_AUDIO,
    )

    events = event_map(content)
    assert [step["type"] for step in events["season1_congratulations"]["steps"]] == ["photo", "message"]
    for day in (7, 14, 21, 28, 30):
        message = next(
            step["text"]
            for step in events[f"day{day:02d}_morning"]["steps"]
            if step["type"] == "message"
        )
        assert "<b>Диалог целиком.</b>" in message

    messages = [
        step["text"]
        for event in content["events"]
        for step in event["steps"]
        if step["type"] == "message"
    ]
    assert sum("<tg-spoiler>Hi! I’m Alex. I’m from Boston.</tg-spoiler>" in text for text in messages) == 1


def verify_season2(content: dict) -> None:
    meta = content["meta"]
    assert meta["season"] == 2
    assert meta["timezone"] == "Europe/Moscow"
    assert meta["channel"] == "@english_story_a1a2"
    assert meta["start_date"] == "2026-10-01"
    assert meta["end_date"] == "2026-10-31"
    assert meta["audio_files"] == 53
    assert meta["image_files"] == 5
    assert len(content["events"]) == 64
    verify_common(content, {"message": 63, "audio": 53, "photo": 5, "poll": 38})
    assert sha256(SEASON2_SOURCE) == meta["source_sha256"]
    verify_daily_events(
        content,
        season=2,
        days=31,
        event_prefix="s2_",
        no_practice_audio=SEASON2_NO_PRACTICE_AUDIO,
    )
    verify_bold_dialogue_speakers(content)

    events = event_map(content)
    assert [step["type"] for step in events["season2_congratulations"]["steps"]] == ["photo", "message"]
    assert [step["type"] for step in events["season2_final_polls"]["steps"]] == [
        "poll", "poll", "poll", "poll", "poll", "poll", "audio", "poll"
    ]

    for day in (7, 14, 21, 28, 31):
        message = next(
            step["text"]
            for step in events[f"s2_day{day:02d}_morning"]["steps"]
            if step["type"] == "message"
        )
        assert "<b>Диалог целиком.</b>" in message

    congratulations = next(
        step["text"]
        for step in events["season2_congratulations"]["steps"]
        if step["type"] == "message"
    )
    assert "Вы прошли второй сезон курса." in congratulations
    assert congratulations.count("✅ ") == 5
    assert "<b>🏆 Вы молодец!</b>" in congratulations
    assert congratulations.endswith("До встречи в третьем сезоне!")


def verify_season3(content: dict) -> None:
    meta = content["meta"]
    assert meta["season"] == 3
    assert meta["timezone"] == "Europe/Moscow"
    assert meta["channel"] == "@english_story_a1a2"
    assert meta["start_date"] == "2026-11-01"
    assert meta["end_date"] == "2026-11-30"
    assert meta["audio_files"] == 52
    assert meta["image_files"] == 5
    assert len(content["events"]) == 62
    verify_common(content, {"message": 61, "audio": 52, "photo": 5, "poll": 37})
    assert sha256(SEASON3_SOURCE) == meta["source_sha256"]
    verify_daily_events(
        content,
        season=3,
        days=30,
        event_prefix="s3_",
        no_practice_audio=SEASON3_NO_PRACTICE_AUDIO,
    )
    verify_bold_dialogue_speakers(content)

    events = event_map(content)
    assert [step["type"] for step in events["season3_congratulations"]["steps"]] == ["photo", "message"]
    assert [step["type"] for step in events["season3_final_polls"]["steps"]] == [
        "poll", "poll", "poll", "poll", "poll", "poll", "audio", "poll"
    ]

    for day in (7, 14, 21, 28, 30):
        message = next(
            step["text"]
            for step in events[f"s3_day{day:02d}_morning"]["steps"]
            if step["type"] == "message"
        )
        assert "<b>Диалог целиком.</b>" in message

    messages = [
        step["text"]
        for event in content["events"]
        for step in event["steps"]
        if step["type"] == "message"
    ]
    assert sum("<tg-spoiler>" in text for text in messages) == 2

    congratulations = next(
        step["text"]
        for step in events["season3_congratulations"]["steps"]
        if step["type"] == "message"
    )
    assert "Вы прошли третий сезон курса." in congratulations
    assert congratulations.count("✅ ") == 6
    assert "<b>🏆 Вы молодец!</b>" in congratulations
    assert congratulations.endswith("До встречи в четвёртом сезоне!")


def verify_schedule(season1: dict, season2: dict, season3: dict) -> None:
    timezone = ZoneInfo("Europe/Moscow")
    assert [e["id"] for e in due_events(season1, datetime(2026, 9, 1, 7, 0, tzinfo=timezone))] == [
        "day01_morning"
    ]
    assert [e["id"] for e in due_events(season1, datetime(2026, 9, 30, 16, 0, tzinfo=timezone))] == [
        "season1_final_polls", "season1_congratulations"
    ]
    assert [e["id"] for e in due_events(season2, datetime(2026, 10, 1, 7, 0, tzinfo=timezone))] == [
        "s2_day01_morning"
    ]
    assert [e["id"] for e in due_events(season2, datetime(2026, 10, 31, 14, 0, tzinfo=timezone))] == [
        "s2_day31_practice", "season2_final_polls"
    ]
    assert [e["id"] for e in due_events(season2, datetime(2026, 10, 31, 16, 0, tzinfo=timezone))] == [
        "season2_final_polls", "season2_congratulations"
    ]
    assert not due_events(season2, datetime(2026, 11, 1, 7, 0, tzinfo=timezone))
    assert [e["id"] for e in due_events(season3, datetime(2026, 11, 1, 7, 0, tzinfo=timezone))] == [
        "s3_day01_morning"
    ]
    assert [e["id"] for e in due_events(season3, datetime(2026, 11, 30, 14, 0, tzinfo=timezone))] == [
        "s3_day30_practice", "season3_final_polls"
    ]
    assert [e["id"] for e in due_events(season3, datetime(2026, 11, 30, 16, 0, tzinfo=timezone))] == [
        "season3_final_polls", "season3_congratulations"
    ]
    assert not due_events(season3, datetime(2026, 12, 1, 7, 0, tzinfo=timezone))


def main() -> None:
    season1 = load(SEASON1_PATH)
    season2 = load(SEASON2_PATH)
    season3 = load(SEASON3_PATH)
    verify_season1(season1)
    verify_season2(season2)
    verify_season3(season3)
    verify_schedule(season1, season2, season3)

    combined = load_all_content()
    assert combined["meta"]["seasons"] == [1, 2, 3]
    assert len(combined["events"]) == 188
    assert len({event["id"] for event in combined["events"]}) == 188
    assert combined["events"][0]["date"] == "2026-09-01"
    assert combined["events"][-1]["date"] == "2026-11-30"

    print(
        "Package QA passed: 3 seasons, 188 events, 469 Telegram steps, "
        "157 audio, 15 images, 112 polls"
    )


if __name__ == "__main__":
    main()
