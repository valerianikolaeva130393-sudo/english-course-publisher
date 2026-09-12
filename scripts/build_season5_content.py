from __future__ import annotations

import hashlib
import html
import json
import re
from datetime import date, timedelta
from pathlib import Path

from docx import Document


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "source" / "Сезон 5_Все публикации_Английский через истории_ФИНАЛ.docx"
OUTPUT = ROOT / "content" / "season5.json"
START_DATE = date(2027, 1, 1)
TIMEZONE = "Europe/Moscow"
CHANNEL = "@english_story_a1a2"
COURSE_NAME = "Английский через истории"
WEEK_IMAGES = {day: f"images/season5/week{week:02d}.png" for week, day in enumerate((7, 14, 21, 28), 1)}
NO_PRACTICE_AUDIO = {4, 9, 12, 18, 19, 23, 25, 26, 29}
SUBSECTION_PREFIXES = ("🎬", "🗣", "⭐", "🎧")
DIALOGUE_PREFIXES = ("👩 ", "👨 ", "🧑 ")
DIALOGUE_INDENT = "&#160;" * 5


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def paragraph_html(paragraph) -> str:
    parts = []
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
    return re.sub(r"\|\|(.+?)\|\|", r"<tg-spoiler>\1</tg-spoiler>", value, flags=re.S)


def is_subsection_heading(value: str) -> bool:
    return value.startswith(SUBSECTION_PREFIXES)


def is_dialogue_paragraph(value: str) -> bool:
    return value.startswith(DIALOGUE_PREFIXES)


def format_dialogue_paragraph(value: str) -> str:
    lines = value.splitlines()
    if len(lines) < 2:
        return value
    speaker_line = re.sub(r"</?b>", "", lines[0])
    match = re.fullmatch(r"(👩|👨|🧑)\s+([^:\n]+):", speaker_line)
    if match:
        speaker_line = f"{match.group(1)} <b>{match.group(2)}:</b>"
    spoken_lines = [re.sub(r"</?b>", "", line) for line in lines[1:]]
    return "\n".join([speaker_line, *(DIALOGUE_INDENT + line for line in spoken_lines)])


def join_paragraphs(paragraphs) -> str:
    items = []
    for paragraph in paragraphs:
        raw = paragraph.text.strip()
        value = paragraph_html(paragraph)
        if not raw or not value:
            continue
        if is_subsection_heading(raw):
            value = f"<u>{re.sub(r'</?b>', '', value)}</u>"
        if is_dialogue_paragraph(raw):
            value = format_dialogue_paragraph(value)
        items.append((raw, value))
    output = []
    for index, (raw, value) in enumerate(items):
        if index:
            previous = items[index - 1][0]
            boundary = is_dialogue_paragraph(raw) != is_dialogue_paragraph(previous)
            output.append("\n\n" if boundary or is_subsection_heading(raw) or raw.startswith("👇") else "\n")
        output.append(value)
    return "".join(output)


def join_congratulations(paragraphs) -> str:
    return "\n\n".join(filter(None, (paragraph_html(p) for p in paragraphs)))


def parse_options(text: str) -> tuple[list[str], int]:
    options, correct = [], -1
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("✅"):
            correct = len(options)
            options.append(line[1:].strip())
        elif line.startswith("❌"):
            options.append(line[1:].strip())
        elif line:
            raise AssertionError(f"Строка варианта без ✅/❌: {line!r}")
    assert len(options) >= 2 and correct >= 0
    return options, correct


def make_poll(step_id: str, question: str, option_text: str) -> dict:
    options, correct = parse_options(option_text)
    return {"id": step_id, "type": "poll", "question": question, "options": options, "correct_option_ids": [correct]}


def option_block(texts: list[str], start: int) -> str:
    lines = []
    for value in texts[start:]:
        if value.startswith(("✅", "❌")):
            lines.append(value)
        else:
            break
    return "\n".join(lines)


def practice_question(section, practice_start: int, label: int, options_index: int) -> str:
    after = [p.text.strip() for p in section[label + 1:options_index] if p.text.strip()]
    if after:
        return "\n".join(after)
    body = [p.text.strip() for p in section[practice_start + 1:label] if p.text.strip()]
    arrow = next((i for i, value in enumerate(body) if value.startswith("👇")), None)
    if arrow is not None:
        selected = body[arrow:]
        selected[0] = selected[0].removeprefix("👇").strip()
        return "\n".join(selected)
    return "\n".join(value for value in body if not value.startswith("🎧 Послушайте"))


def bonus_body(section, start: int):
    end = next((i for i in range(start + 1, len(section)) if section[i].text.strip().startswith("📸 ФОТО")), len(section))
    return [p for p in section[start + 1:end] if not p.text.strip().startswith(("🎧 Голосовое:", "Служебно:"))]


def build() -> None:
    document = Document(SOURCE)
    paragraphs = document.paragraphs
    texts = [p.text.strip() for p in paragraphs]
    day_starts = {int(m.group(1)): i for i, text in enumerate(texts) if (m := re.match(r"^ДЕНЬ (\d+) —", text))}
    assert sorted(day_starts) == list(range(1, 32))
    final_polls_start = texts.index("31 ЯНВАРЯ • 14:00")
    congrats_start = texts.index("31 ЯНВАРЯ • 16:00")
    events = []

    for day in range(1, 32):
        start, end = day_starts[day], day_starts.get(day + 1, final_polls_start)
        section = paragraphs[start:end]
        section_texts = [p.text.strip() for p in section]
        event_date = (START_DATE + timedelta(days=day - 1)).isoformat()
        morning_start = next(i for i, value in enumerate(section_texts) if value.startswith("🌱 Сезон 5"))
        morning_audio = next(i for i, value in enumerate(section_texts) if value.startswith("🎧 Аудио:"))
        morning_steps = [
            {"id": "text", "type": "message", "text": join_paragraphs(section[morning_start:morning_audio])},
            {"id": "audio", "type": "audio", "path": f"audio/season5/morning/day{day:02d}.mp3", "title": f"Сезон 5 · День {day} · Утро", "performer": COURSE_NAME},
        ]
        if day in WEEK_IMAGES:
            morning_steps.insert(0, {"id": "image", "type": "photo", "path": WEEK_IMAGES[day]})
        events.append({"id": f"s5_day{day:02d}_morning", "date": event_date, "time": "07:00", "retry_until": "09:00", "steps": morning_steps})

        practice_start = next(i for i, value in enumerate(section_texts) if value.startswith("☀️ Практика"))
        poll_label = next(i for i in range(practice_start, len(section_texts)) if section_texts[i].startswith("Telegram Quiz Poll"))
        options_index = next(i for i in range(poll_label + 1, len(section_texts)) if section_texts[i].startswith(("✅", "❌")))
        practice_text = join_paragraphs([p for p in section[practice_start:poll_label] if not p.text.strip().startswith("🎧 Аудио:")])
        steps = [{"id": "text", "type": "message", "text": practice_text}]
        practice_path = ROOT / f"audio/season5/practice/day{day:02d}.mp3"
        if practice_path.exists():
            steps.append({"id": "audio", "type": "audio", "path": f"audio/season5/practice/day{day:02d}.mp3", "title": f"Сезон 5 · День {day} · Практика", "performer": COURSE_NAME})
        steps.append(make_poll("poll", practice_question(section, practice_start, poll_label, options_index), option_block(section_texts, options_index)))
        events.append({"id": f"s5_day{day:02d}_practice", "date": event_date, "time": "12:00", "retry_until": "14:00", "steps": steps})

        bonus_start = next((i for i, value in enumerate(section_texts) if value.startswith("ВЕЧЕРНИЙ БОНУС")), None)
        if bonus_start is not None:
            events.append({"id": f"s5_day{day:02d}_bonus", "date": event_date, "time": "18:00", "retry_until": "20:00", "steps": [{"id": "text", "type": "message", "text": join_paragraphs(bonus_body(section, bonus_start))}]})

    final_section = paragraphs[final_polls_start:congrats_start]
    final_texts = [p.text.strip() for p in final_section]
    poll_heads = [i for i, value in enumerate(final_texts) if value.startswith("FINAL POLL")]
    final_steps = []
    for number, head in enumerate(poll_heads, 1):
        end = poll_heads[number] if number < len(poll_heads) else len(final_section)
        options_index = next(i for i in range(head + 1, end) if final_texts[i].startswith(("✅", "❌")))
        if number == 7:
            final_steps.append({"id": "poll07_audio", "type": "audio", "path": "audio/season5/final/final_poll_07.mp3", "title": "Сезон 5 · Итоговый опрос · Задание 7", "performer": COURSE_NAME})
            question_parts = [value for value in final_texts[head + 1:options_index] if value.endswith("?")]
        else:
            question_parts = [value for value in final_texts[head + 1:options_index] if value]
        final_steps.append(make_poll(f"poll{number:02d}", "\n".join(question_parts), option_block(final_texts[:end], options_index)))
    events.append({"id": "season5_final_polls", "date": "2027-01-31", "time": "14:00", "retry_until": "16:00", "steps": final_steps})

    congrats_section = paragraphs[congrats_start:]
    congrats_texts = [p.text.strip() for p in congrats_section]
    body_start = next(i for i, value in enumerate(congrats_texts) if value.startswith("🎉 SEASON 5 COMPLETE"))
    photo_marker = next(i for i, value in enumerate(congrats_texts) if value.startswith("📸 ФИНАЛЬНОЕ ФОТО"))
    events.append({"id": "season5_congratulations", "date": "2027-01-31", "time": "16:00", "retry_until": "18:00", "steps": [
        {"id": "image", "type": "photo", "path": "images/season5/final.png"},
        {"id": "text", "type": "message", "text": join_congratulations(congrats_section[body_start:photo_marker])},
    ]})

    practice_days = {int(e["id"][6:8]) for e in events if e["id"].startswith("s5_day") and e["id"].endswith("_practice") for step in e["steps"] if step["type"] == "audio"}
    assert practice_days == set(range(1, 32)) - NO_PRACTICE_AUDIO
    asset_paths = sorted({step["path"] for event in events for step in event["steps"] if "path" in step})
    assert all((ROOT / relative).is_file() for relative in asset_paths)
    payload = {"meta": {"course": COURSE_NAME, "season": 5, "start_date": "2027-01-01", "end_date": "2027-01-31", "timezone": TIMEZONE, "channel": CHANNEL, "source_sha256": sha256(SOURCE), "audio_files": 54, "image_files": 5}, "events": events, "assets": {relative: sha256(ROOT / relative) for relative in asset_paths}}
    OUTPUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(OUTPUT)


if __name__ == "__main__":
    build()
