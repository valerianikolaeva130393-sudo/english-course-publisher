from __future__ import annotations

import hashlib
import html
import json
import re
from datetime import date, timedelta
from pathlib import Path

from docx import Document


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "source" / "Английский через истории — Сезон 1 — Все публикации — ФИНАЛ.docx"
OUTPUT = ROOT / "content" / "season1.json"

START_DATE = date(2026, 9, 1)
TIMEZONE = "Europe/Moscow"
CHANNEL = "@english_story_a1a2"
COURSE_NAME = "Английский через истории"
WEEK_IMAGES = {7: "images/week01.png", 14: "images/week02.png", 21: "images/week03.png", 28: "images/week04.png"}
NO_PRACTICE_AUDIO = {9, 12, 18, 19, 22, 23, 25, 26, 29}
SUBSECTION_PREFIXES = ("🎬", "🗣", "⭐", "🎧")
DIALOGUE_PREFIXES = ("👩 ", "👨 ")
DIALOGUE_INDENT = "&#160;" * 5


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def paragraph_html(paragraph) -> str:
    parts: list[str] = []
    for run in paragraph.runs:
        text = html.escape(run.text, quote=False)
        if not text:
            continue
        if run.bold:
            text = f"<b>{text}</b>"
        if run.italic:
            text = f"<i>{text}</i>"
        if run.underline:
            text = f"<u>{text}</u>"
        parts.append(text)
    value = "".join(parts).strip()
    for tag in ("b", "i", "u"):
        value = value.replace(f"</{tag}><{tag}>", "")
    value = re.sub(r"\|\|(.+?)\|\|", r"<tg-spoiler>\1</tg-spoiler>", value, flags=re.S)
    return value


def is_subsection_heading(value: str) -> bool:
    return value.startswith(SUBSECTION_PREFIXES)


def is_dialogue_paragraph(value: str) -> bool:
    return value.startswith(DIALOGUE_PREFIXES)


def format_subsection_heading(value: str) -> str:
    value = re.sub(r"</?b>", "", value)
    return f"<u>{value}</u>"


def format_dialogue_paragraph(value: str) -> str:
    lines = value.splitlines()
    if len(lines) < 2:
        return value
    return "\n".join([lines[0], *(DIALOGUE_INDENT + line for line in lines[1:])])


def join_paragraphs(paragraphs) -> str:
    items: list[tuple[str, str]] = []
    for paragraph in paragraphs:
        raw = paragraph.text.strip()
        value = paragraph_html(paragraph)
        if not raw or not value:
            continue
        if is_subsection_heading(raw):
            value = format_subsection_heading(value)
        if is_dialogue_paragraph(raw):
            value = format_dialogue_paragraph(value)
        items.append((raw, value))

    output: list[str] = []
    for index, (raw, value) in enumerate(items):
        if index:
            previous_raw = items[index - 1][0]
            dialogue_boundary = is_dialogue_paragraph(raw) != is_dialogue_paragraph(previous_raw)
            section_boundary = is_subsection_heading(raw) or raw.startswith("👇")
            separator = "\n\n" if dialogue_boundary or section_boundary else "\n"
            output.append(separator)
        output.append(value)
    return "".join(output)


def join_congratulations(paragraphs) -> str:
    return "\n\n".join(filter(None, (paragraph_html(paragraph) for paragraph in paragraphs)))


def plain_text(value: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", value)).strip()


def parse_options(text: str) -> tuple[list[str], int]:
    options: list[str] = []
    correct = -1
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith("✅"):
            correct = len(options)
            options.append(line[1:].strip())
        elif line.startswith("❌"):
            options.append(line[1:].strip())
        else:
            raise AssertionError(f"Строка варианта без ✅/❌: {line!r}")
    if len(options) < 2 or correct < 0:
        raise AssertionError(f"Некорректные варианты опроса: {text!r}")
    return options, correct


def practice_question(section, practice_start: int, label: int, options_index: int) -> str:
    after_label = [p.text.strip() for p in section[label + 1 : options_index] if p.text.strip()]
    if after_label:
        return "\n".join(after_label)

    body = [p.text.strip() for p in section[practice_start + 1 : label] if p.text.strip()]
    arrow = next((index for index, value in enumerate(body) if value.startswith("👇")), None)
    if arrow is not None:
        selected = body[arrow:]
        selected[0] = selected[0].removeprefix("👇").strip()
        return "\n".join(selected)

    selected = [value for value in body if not value.startswith("🎧 Послушайте")]
    return "\n".join(selected)


def make_poll(step_id: str, question: str, option_text: str) -> dict:
    options, correct = parse_options(option_text)
    return {
        "id": step_id,
        "type": "poll",
        "question": question,
        "options": options,
        "correct_option_ids": [correct],
    }


def build() -> None:
    document = Document(SOURCE)
    paragraphs = document.paragraphs
    texts = [p.text.strip() for p in paragraphs]

    day_starts: dict[int, int] = {}
    for index, text in enumerate(texts):
        match = re.match(r"^ДЕНЬ (\d+) —", text)
        if match:
            day_starts[int(match.group(1))] = index
    assert sorted(day_starts) == list(range(1, 31))

    final_polls_start = texts.index("30 СЕНТЯБРЯ • 14:00")
    congrats_start = texts.index("30 СЕНТЯБРЯ • 16:00")
    events: list[dict] = []

    for day in range(1, 31):
        start = day_starts[day]
        end = day_starts.get(day + 1, final_polls_start)
        section = paragraphs[start:end]
        section_texts = [p.text.strip() for p in section]
        event_date = (START_DATE + timedelta(days=day - 1)).isoformat()

        morning_start = next(i for i, value in enumerate(section_texts) if value.startswith("🌱 Сезон 1"))
        morning_audio_marker = next(i for i, value in enumerate(section_texts) if value.startswith("🎧 Аудио:"))
        morning_text = join_paragraphs(section[morning_start:morning_audio_marker])
        morning_steps = [
            {"id": "text", "type": "message", "text": morning_text},
            {
                "id": "audio",
                "type": "audio",
                "path": f"audio/morning/day{day:02d}.mp3",
                "title": f"Сезон 1 · День {day} · Утро",
                "performer": COURSE_NAME,
            },
        ]
        if day in WEEK_IMAGES:
            morning_steps.insert(0, {"id": "image", "type": "photo", "path": WEEK_IMAGES[day]})
        events.append(
            {
                "id": f"day{day:02d}_morning",
                "date": event_date,
                "time": "07:00",
                "retry_until": "09:00",
                "steps": morning_steps,
            }
        )

        practice_start = next(i for i, value in enumerate(section_texts) if value.startswith("☀️ Практика"))
        poll_label = next(i for i in range(practice_start, len(section_texts)) if section_texts[i].startswith("Telegram Quiz Poll"))
        options_index = next(
            i
            for i in range(poll_label + 1, len(section_texts))
            if "✅" in section_texts[i] and "❌" in section_texts[i]
        )
        practice_text = join_paragraphs(section[practice_start:poll_label])
        question = practice_question(section, practice_start, poll_label, options_index)
        practice_steps = [{"id": "text", "type": "message", "text": practice_text}]
        practice_audio = ROOT / f"audio/practice/day{day:02d}.mp3"
        if practice_audio.exists():
            practice_steps.append(
                {
                    "id": "audio",
                    "type": "audio",
                    "path": f"audio/practice/day{day:02d}.mp3",
                    "title": f"Сезон 1 · День {day} · Практика",
                    "performer": COURSE_NAME,
                }
            )
        practice_steps.append(make_poll("poll", question, section_texts[options_index]))
        events.append(
            {
                "id": f"day{day:02d}_practice",
                "date": event_date,
                "time": "12:00",
                "retry_until": "14:00",
                "steps": practice_steps,
            }
        )

    final_section = paragraphs[final_polls_start:congrats_start]
    final_texts = [p.text.strip() for p in final_section]
    poll_heads = [i for i, value in enumerate(final_texts) if value.startswith("FINAL POLL")]
    final_steps: list[dict] = []
    for number, head in enumerate(poll_heads, start=1):
        end = poll_heads[number] if number < len(poll_heads) else len(final_section)
        options_index = next(
            i
            for i in range(head + 1, end)
            if "✅" in final_texts[i] and "❌" in final_texts[i]
        )
        if number == 7:
            final_steps.append(
                {
                    "id": "poll07_audio",
                    "type": "audio",
                    "path": "audio/final/final_poll_07.mp3",
                    "title": "Сезон 1 · Итоговый опрос · Задание 7",
                    "performer": COURSE_NAME,
                }
            )
            question_parts = [
                value
                for value in final_texts[head + 1 : options_index]
                if value.endswith("?")
            ]
        else:
            question_parts = [value for value in final_texts[head + 1 : options_index] if value]
        question = "\n".join(question_parts)
        final_steps.append(make_poll(f"poll{number:02d}", question, final_texts[options_index]))

    events.append(
        {
            "id": "season1_final_polls",
            "date": "2026-09-30",
            "time": "14:00",
            "retry_until": "16:00",
            "steps": final_steps,
        }
    )

    congrats_section = paragraphs[congrats_start:]
    congrats_texts = [p.text.strip() for p in congrats_section]
    congrats_body_start = next(i for i, value in enumerate(congrats_texts) if value.startswith("🎉 SEASON 1 COMPLETE"))
    photo_marker = next(i for i, value in enumerate(congrats_texts) if value.startswith("📸 ФИНАЛЬНОЕ ФОТО"))
    congrats_text = join_congratulations(congrats_section[congrats_body_start:photo_marker])
    events.append(
        {
            "id": "season1_congratulations",
            "date": "2026-09-30",
            "time": "16:00",
            "retry_until": "18:00",
            "steps": [
                {"id": "image", "type": "photo", "path": "images/final.png"},
                {"id": "text", "type": "message", "text": congrats_text},
            ],
        }
    )

    practice_days = {
        int(event["id"][3:5])
        for event in events
        if event["id"].endswith("_practice")
        for step in event["steps"]
        if step["type"] == "audio"
    }
    assert practice_days == set(range(1, 31)) - NO_PRACTICE_AUDIO

    asset_paths = sorted(
        {
            step["path"]
            for event in events
            for step in event["steps"]
            if "path" in step
        }
    )
    for relative in asset_paths:
        assert (ROOT / relative).is_file(), relative

    payload = {
        "meta": {
            "course": COURSE_NAME,
            "season": 1,
            "start_date": "2026-09-01",
            "end_date": "2026-09-30",
            "timezone": TIMEZONE,
            "channel": CHANNEL,
            "source_sha256": sha256(SOURCE),
            "audio_files": 52,
            "image_files": 5,
        },
        "events": events,
        "assets": {relative: sha256(ROOT / relative) for relative in asset_paths},
    }

    OUTPUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(OUTPUT)


if __name__ == "__main__":
    build()
