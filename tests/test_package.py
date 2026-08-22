from __future__ import annotations

import hashlib
import html
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from publisher import due_events, validate_content  # noqa: E402


CONTENT = ROOT / "content" / "season1.json"
NO_PRACTICE_AUDIO = {9, 12, 18, 19, 22, 23, 25, 26, 29}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def plain_length(value: str) -> int:
    return len(html.unescape(re.sub(r"<[^>]+>", "", value)))


def main() -> None:
    content = json.loads(CONTENT.read_text(encoding="utf-8"))
    validate_content(content)
    meta = content["meta"]
    events = content["events"]

    assert meta["timezone"] == "Europe/Moscow"
    assert meta["channel"] == "@english_story_a1a2"
    assert meta["start_date"] == "2026-09-01"
    assert meta["end_date"] == "2026-09-30"
    assert len(events) == 62

    counts = {
        kind: sum(1 for event in events for step in event["steps"] if step["type"] == kind)
        for kind in ("message", "audio", "photo", "poll")
    }
    assert counts == {"message": 61, "audio": 52, "photo": 5, "poll": 37}, counts
    assert sum(counts.values()) == 155

    for relative, expected_hash in content["assets"].items():
        path = ROOT / relative
        assert path.is_file(), relative
        assert sha256(path) == expected_hash, relative
        assert path.stat().st_size > 10_000, relative

    source = ROOT / "source" / "Английский через истории — Сезон 1 — Все публикации — ФИНАЛ.docx"
    assert sha256(source) == meta["source_sha256"]

    for day in range(1, 31):
        morning = next(event for event in events if event["id"] == f"day{day:02d}_morning")
        practice = next(event for event in events if event["id"] == f"day{day:02d}_practice")
        assert sum(step["type"] == "audio" for step in morning["steps"]) == 1
        morning_audio = next(step for step in morning["steps"] if step["type"] == "audio")
        assert morning_audio["title"] == f"Сезон 1 · День {day} · Утро"
        assert morning_audio["performer"] == "Английский через истории"
        assert "caption" not in morning_audio
        practice_has_audio = any(step["type"] == "audio" for step in practice["steps"])
        assert practice_has_audio == (day not in NO_PRACTICE_AUDIO), day
        if practice_has_audio:
            practice_audio = next(step for step in practice["steps"] if step["type"] == "audio")
            assert practice_audio["title"] == f"Сезон 1 · День {day} · Практика"
            assert practice_audio["performer"] == "Английский через истории"
            assert "caption" not in practice_audio
        assert sum(step["type"] == "poll" for step in practice["steps"]) == 1

    for day in range(1, 31):
        morning = next(event for event in events if event["id"] == f"day{day:02d}_morning")
        expected_order = ["photo", "message", "audio"] if day in {7, 14, 21, 28} else ["message", "audio"]
        assert [step["type"] for step in morning["steps"]] == expected_order, (day, morning["steps"])

        practice = next(event for event in events if event["id"] == f"day{day:02d}_practice")
        expected_order = ["message", "audio", "poll"] if day not in NO_PRACTICE_AUDIO else ["message", "poll"]
        assert [step["type"] for step in practice["steps"]] == expected_order, (day, practice["steps"])

    congratulations = next(event for event in events if event["id"] == "season1_congratulations")
    assert [step["type"] for step in congratulations["steps"]] == ["photo", "message"]

    messages = [step["text"] for event in events for step in event["steps"] if step["type"] == "message"]
    assert sum("<tg-spoiler>Hi! I’m Alex. I’m from Boston.</tg-spoiler>" in text for text in messages) == 1
    assert all("||" not in text for text in messages)
    assert all(plain_length(text) <= 4096 for text in messages)
    assert all("Telegram Quiz Poll" not in text for text in messages)
    assert all("📸 ФОТО" not in text for text in messages)
    assert all("🎧 Аудио:" not in text for text in messages)

    for day in (7, 14, 21, 28, 30):
        event = next(event for event in events if event["id"] == f"day{day:02d}_morning")
        message = next(step["text"] for step in event["steps"] if step["type"] == "message")
        assert "<b>Диалог целиком.</b>" in message, day

    day30_message = next(
        step["text"]
        for event in events
        if event["id"] == "day30_morning"
        for step in event["steps"]
        if step["type"] == "message"
    )
    assert "Эмма и Адам уже понемногу освоились" not in day30_message

    congratulations_text = next(
        step["text"]
        for event in events
        if event["id"] == "season1_congratulations"
        for step in event["steps"]
        if step["type"] == "message"
    )
    assert "Месяц назад всё началось" not in congratulations_text
    assert "Вы прошли весь первый сезон курса." in congratulations_text
    assert congratulations_text.count("✅ ") == 10
    assert "<b>🏆 Вы молодец!</b>" in congratulations_text
    assert congratulations_text.endswith("До встречи во втором сезоне!")

    morning_messages = {
        event["id"]: next(step["text"] for step in event["steps"] if step["type"] == "message")
        for event in events
        if event["id"].endswith("_morning")
    }
    for message in morning_messages.values():
        lines = message.splitlines()
        assert lines[0].startswith("🌱 ")
        assert lines[1] and not lines[1].isspace()
        assert not lines[2].strip()
        assert "<b>🎬 История</b>" not in message
        assert "<u>🎬 История</u>\n" in message
        assert "\n\n<u>🗣 " in message or "\n\n<u>⭐ Главная задача</u>" in message
        for line in lines:
            if line.startswith("👩 ") or line.startswith("👨 "):
                continue
            if "Emma:" not in line and "Adam:" not in line and line.startswith("&#160;"):
                assert line.startswith("&#160;" * 5)

    all_audio = [step for event in events for step in event["steps"] if step["type"] == "audio"]
    assert all(step.get("performer") == "Английский через истории" for step in all_audio)
    assert all(step.get("title") for step in all_audio)
    assert all("caption" not in step for step in all_audio)

    polls = [step for event in events for step in event["steps"] if step["type"] == "poll"]
    for poll in polls:
        assert 1 <= len(poll["question"]) <= 300
        assert 2 <= len(poll["options"]) <= 12
        assert len(poll["correct_option_ids"]) == 1
        assert 0 <= poll["correct_option_ids"][0] < len(poll["options"])
        assert all(1 <= len(option) <= 100 for option in poll["options"])

    timezone = ZoneInfo("Europe/Moscow")
    assert [e["id"] for e in due_events(content, datetime(2026, 9, 1, 7, 0, tzinfo=timezone))] == ["day01_morning"]
    assert [e["id"] for e in due_events(content, datetime(2026, 9, 1, 12, 0, tzinfo=timezone))] == ["day01_practice"]
    assert [e["id"] for e in due_events(content, datetime(2026, 9, 30, 14, 0, tzinfo=timezone))] == [
        "day30_practice",
        "season1_final_polls",
    ]
    assert [e["id"] for e in due_events(content, datetime(2026, 9, 30, 16, 0, tzinfo=timezone))] == [
        "season1_final_polls",
        "season1_congratulations",
    ]
    assert not due_events(content, datetime(2026, 10, 1, 7, 0, tzinfo=timezone))

    print("Package QA passed: 62 events, 155 Telegram steps, 52 audio, 5 images, 37 polls")


if __name__ == "__main__":
    main()
