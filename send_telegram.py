import html
import json
import os
from pathlib import Path

import requests

ITEMS = Path("new_items.json")


def escaped(item, key, fallback="Нет данных"):
    return html.escape(str(item.get(key) or fallback))


def send(item):
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "@from78kg")
    api = "https://api.telegram.org/bot" + token

    title = escaped(item, "title", "Новое wakeboard-объявление")
    price = escaped(item, "price")
    description = html.escape(
        (item.get("description_ru") or item.get("description") or "Описание отсутствует")[:700]
    )
    site = escaped(item, "site", "Vinted")
    url = html.escape(item["url"], quote=True)

    card_text = (
        f"<b>{title}</b> — <b>{price}</b>\n\n"
        f"🌍 Площадка: {site}\n"
        f"📏 Размер: {escaped(item, 'size')}\n"
        f"✨ Состояние: {escaped(item, 'condition')}\n\n"
        f"📝 <b>Описание на русском:</b>\n{description}\n\n"
        f'<a href="{url}">Открыть объявление</a>'
    )

    image = item.get("image")
    if image and len(card_text) <= 1024:
        endpoint = api + "/sendPhoto"
        payload = {
            "chat_id": chat_id,
            "photo": image,
            "caption": card_text,
            "parse_mode": "HTML",
        }
    else:
        endpoint = api + "/sendMessage"
        payload = {
            "chat_id": chat_id,
            "text": card_text[:4096],
            "parse_mode": "HTML",
            "disable_web_page_preview": "false",
        }

    response = requests.post(endpoint, data=payload, timeout=25)
    response.raise_for_status()


def main():
    if not ITEMS.exists():
        return

    for item in json.loads(ITEMS.read_text(encoding="utf-8")):
        send(item)


if __name__ == "__main__":
    main()
