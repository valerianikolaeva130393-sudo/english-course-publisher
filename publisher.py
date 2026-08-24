from __future__ import annotations

import argparse
import json
import mimetypes
import os
import sys
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parent
CONTENT_DIR = ROOT / "content"
STATE_PATH = ROOT / "state" / "published.json"


class TelegramError(RuntimeError):
    def __init__(self, description: str, error_code: int | None = None, retry_after: int | None = None):
        super().__init__(description)
        self.error_code = error_code
        self.retry_after = retry_after

    @property
    def retryable(self) -> bool:
        return self.retry_after is not None or self.error_code in {429, 500, 502, 503, 504} or self.error_code is None


class TelegramClient:
    def __init__(self, token: str, chat_id: str):
        if not token or ":" not in token:
            raise ValueError("TELEGRAM_BOT_TOKEN отсутствует или имеет неверный формат")
        if not chat_id:
            raise ValueError("TELEGRAM_CHAT_ID отсутствует")
        self.base = f"https://api.telegram.org/bot{token}"
        self.chat_id = chat_id

    def _decode(self, response_bytes: bytes) -> dict:
        data = json.loads(response_bytes.decode("utf-8"))
        if not data.get("ok"):
            parameters = data.get("parameters") or {}
            raise TelegramError(
                data.get("description", "Telegram API вернул ошибку"),
                data.get("error_code"),
                parameters.get("retry_after"),
            )
        return data["result"]

    def _request(self, method: str, data: bytes, content_type: str) -> dict:
        request = urllib.request.Request(
            f"{self.base}/{method}",
            data=data,
            headers={"Content-Type": content_type, "User-Agent": "EnglishCoursePublisher/1.0"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=90) as response:
                return self._decode(response.read())
        except urllib.error.HTTPError as error:
            body = error.read()
            try:
                return self._decode(body)
            except TelegramError:
                raise
            except Exception:
                raise TelegramError(f"HTTP {error.code}: {body[:300]!r}", error.code) from error
        except (urllib.error.URLError, TimeoutError) as error:
            raise TelegramError(f"Сетевая ошибка: {error}") from error

    def json_call(self, method: str, payload: dict) -> dict:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        return self._request(method, data, "application/json; charset=utf-8")

    def multipart_call(self, method: str, fields: dict[str, str], file_field: str, path: Path) -> dict:
        boundary = f"----EnglishCourse{uuid.uuid4().hex}"
        chunks: list[bytes] = []
        for name, value in fields.items():
            chunks.extend(
                [
                    f"--{boundary}\r\n".encode(),
                    f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode(),
                    str(value).encode("utf-8"),
                    b"\r\n",
                ]
            )
        mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        chunks.extend(
            [
                f"--{boundary}\r\n".encode(),
                f'Content-Disposition: form-data; name="{file_field}"; filename="{path.name}"\r\n'.encode(),
                f"Content-Type: {mime}\r\n\r\n".encode(),
                path.read_bytes(),
                b"\r\n",
                f"--{boundary}--\r\n".encode(),
            ]
        )
        return self._request(method, b"".join(chunks), f"multipart/form-data; boundary={boundary}")

    def validate(self) -> tuple[dict, dict, dict]:
        bot = self.json_call("getMe", {})
        chat = self.json_call("getChat", {"chat_id": self.chat_id})
        member = self.json_call("getChatMember", {"chat_id": self.chat_id, "user_id": bot["id"]})
        if member.get("status") not in {"administrator", "creator"}:
            raise TelegramError("Бот не является администратором канала", 403)
        if member.get("status") == "administrator" and member.get("can_post_messages") is False:
            raise TelegramError("У бота нет права публиковать сообщения", 403)
        return bot, chat, member

    def send_message(self, text: str) -> dict:
        return self.json_call(
            "sendMessage",
            {
                "chat_id": self.chat_id,
                "text": text,
                "parse_mode": "HTML",
                "link_preview_options": {"is_disabled": True},
            },
        )

    def send_audio(
        self,
        path: Path,
        caption: str = "",
        title: str = "",
        performer: str = "",
    ) -> dict:
        fields = {"chat_id": self.chat_id, "parse_mode": "HTML"}
        if caption:
            fields["caption"] = caption
        if title:
            fields["title"] = title
        if performer:
            fields["performer"] = performer
        return self.multipart_call(
            "sendAudio",
            fields,
            "audio",
            path,
        )

    def send_photo(self, path: Path, caption: str = "") -> dict:
        return self.multipart_call(
            "sendPhoto",
            {"chat_id": self.chat_id, "caption": caption, "parse_mode": "HTML"},
            "photo",
            path,
        )

    def send_poll(self, step: dict) -> dict:
        return self.json_call(
            "sendPoll",
            {
                "chat_id": self.chat_id,
                "question": step["question"],
                "options": [{"text": option} for option in step["options"]],
                "type": "quiz",
                "correct_option_ids": step["correct_option_ids"],
                "is_anonymous": True,
                "allows_multiple_answers": False,
                "shuffle_options": False,
            },
        )


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def load_all_content() -> dict:
    paths = sorted(CONTENT_DIR.glob("season*.json"))
    if not paths:
        raise FileNotFoundError("В content нет файлов season*.json")

    seasons = [load_json(path) for path in paths]
    for season in seasons:
        validate_content(season)

    timezones = {season["meta"]["timezone"] for season in seasons}
    channels = {season["meta"]["channel"] for season in seasons}
    if len(timezones) != 1:
        raise ValueError(f"У сезонов разные часовые пояса: {sorted(timezones)}")
    if len(channels) != 1:
        raise ValueError(f"У сезонов разные каналы: {sorted(channels)}")

    events = [event for season in seasons for event in season["events"]]
    event_ids = [event["id"] for event in events]
    if len(event_ids) != len(set(event_ids)):
        raise ValueError("Повторяющиеся event id между сезонами")

    return {
        "meta": {
            "timezone": next(iter(timezones)),
            "channel": next(iter(channels)),
            "seasons": [season["meta"]["season"] for season in seasons],
        },
        "events": sorted(events, key=lambda event: (event["date"], event["time"], event["id"])),
    }


def load_state() -> dict:
    if not STATE_PATH.exists():
        return {"version": 1, "sent": {}}
    state = load_json(STATE_PATH)
    state.setdefault("version", 1)
    state.setdefault("sent", {})
    return state


def save_state(state: dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary = STATE_PATH.with_suffix(".tmp")
    temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(STATE_PATH)


def step_key(event: dict, step: dict) -> str:
    return f'{event["id"]}:{step["id"]}'


def send_step(client: TelegramClient, step: dict) -> dict:
    kind = step["type"]
    if kind == "message":
        return client.send_message(step["text"])
    if kind == "audio":
        return client.send_audio(
            ROOT / step["path"],
            step.get("caption", ""),
            step.get("title", ""),
            step.get("performer", ""),
        )
    if kind == "photo":
        return client.send_photo(ROOT / step["path"], step.get("caption", ""))
    if kind == "poll":
        return client.send_poll(step)
    raise ValueError(f"Неизвестный тип шага: {kind}")


def due_events(content: dict, now: datetime) -> list[dict]:
    current_date = now.date().isoformat()
    current_time = now.strftime("%H:%M")
    return [
        event
        for event in content["events"]
        if event["date"] == current_date and event["time"] <= current_time <= event["retry_until"]
    ]


def remaining_steps(event: dict, state: dict) -> list[dict]:
    sent = state["sent"]
    return [step for step in event["steps"] if step_key(event, step) not in sent]


def publish_event(client: TelegramClient, event: dict, state: dict, timezone: ZoneInfo, retry: bool) -> None:
    while True:
        pending = remaining_steps(event, state)
        if not pending:
            print(f'{event["id"]}: уже опубликовано')
            return
        step = pending[0]
        key = step_key(event, step)
        try:
            print(f"Отправка {key} ({step['type']})")
            result = send_step(client, step)
            state["sent"][key] = {
                "message_id": result.get("message_id"),
                "sent_at": datetime.now(timezone).isoformat(timespec="seconds"),
            }
            save_state(state)
            time.sleep(1)
        except TelegramError as error:
            print(f"Ошибка Telegram для {key}: {error}", file=sys.stderr)
            now = datetime.now(timezone)
            deadline = datetime.fromisoformat(f'{event["date"]}T{event["retry_until"]}:00').replace(tzinfo=timezone)
            if not retry or not error.retryable or now >= deadline:
                raise
            wait_seconds = max(5, error.retry_after or 300)
            if now.timestamp() + wait_seconds > deadline.timestamp():
                raise
            print(f"Повтор через {wait_seconds} секунд")
            time.sleep(wait_seconds)


def validate_content(content: dict) -> None:
    event_ids = [event["id"] for event in content["events"]]
    if len(event_ids) != len(set(event_ids)):
        raise ValueError("Повторяющиеся event id")
    for event in content["events"]:
        step_ids = [step["id"] for step in event["steps"]]
        if len(step_ids) != len(set(step_ids)):
            raise ValueError(f"Повторяющиеся step id в {event['id']}")
        for step in event["steps"]:
            if "path" in step and not (ROOT / step["path"]).is_file():
                raise FileNotFoundError(step["path"])


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["scheduled", "validate", "test", "preview", "event"], default="scheduled")
    parser.add_argument("--event-id", default="")
    parser.add_argument("--confirm", default="")
    parser.add_argument("--now", default="", help="Тестовая дата/время ISO, например 2026-09-01T07:00")
    parser.add_argument("--retry", action="store_true")
    args = parser.parse_args()

    content = load_all_content()
    timezone = ZoneInfo(content["meta"]["timezone"])
    now = datetime.fromisoformat(args.now).replace(tzinfo=timezone) if args.now else datetime.now(timezone)

    if args.mode == "preview":
        events = due_events(content, now)
        print(json.dumps({"now": now.isoformat(), "events": [event["id"] for event in events]}, ensure_ascii=False, indent=2))
        return

    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    client = TelegramClient(token, chat_id)

    if args.mode == "validate":
        bot, chat, member = client.validate()
        print(f"Бот: @{bot.get('username', '')}")
        print(f"Канал: {chat.get('title', '')} ({chat.get('id', '')})")
        print(f"Права: {member.get('status', '')}; публикация разрешена")
        return

    if args.mode == "test":
        result = client.send_message(
            "✅ <b>Тест публикации пройден</b>\n\n"
            "Бот подключён к каналу «Английский через истории».\n"
            "Это сообщение можно удалить после проверки."
        )
        print(f"Тестовое сообщение отправлено: message_id={result.get('message_id')}")
        return

    state = load_state()
    if args.mode == "event":
        if args.confirm != "PUBLISH":
            raise SystemExit("Для ручной публикации укажите --confirm PUBLISH")
        events = [event for event in content["events"] if event["id"] == args.event_id]
        if len(events) != 1:
            raise SystemExit(f"Событие не найдено: {args.event_id}")
    else:
        events = due_events(content, now)
        if not events:
            print(f"Нет публикаций на {now.isoformat(timespec='minutes')}")
            return

    for event in events:
        publish_event(client, event, state, timezone, args.retry)


if __name__ == "__main__":
    main()
