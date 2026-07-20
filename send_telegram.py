import html
import json
import os
from pathlib import Path

import requests

ITEMS = Path("new_items.json")


def send(item):
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "@from78kg")
    api = "https://api.telegram.org/bot" + token

    title = html.escape(item.get("title") or "Новое wakeboard-объявление")
    description = html.escape((item.get("description") or "Описание отсутствует")[:600])
    summary = html.escape(item.get("summary") or "")
    site = html.escape(item.get("site") or "Vinted")
    url = html.escape(item["url"], quote=True)

    text = (
        f"🏄 <b>{title}</b>\n\n"
        f"🌍 {site}\n"
        f"🤖 {summary}\n\n"
        f"📝 {description}\n\n"
        f'<a href="{url}">Открыть объявление</a>'
    )

    image = item.get("image")
    if image and len(text) <= 1024:
        endpoint = api + "/sendPhoto"
        payload = {
            "chat_id": chat_id,
            "photo": image,
            "caption": text,
            "parse_mode": "HTML",
        }
    else:
        endpoint = api + "/sendMessage"
        payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}

    response = requests.post(endpoint, data=payload, timeout=25)
    response.raise_for_status()


def main():
    if not ITEMS.exists():
        return

    for item in json.loads(ITEMS.read_text(encoding="utf-8")):
        send(item)


if __name__ == "__main__":
    main()
