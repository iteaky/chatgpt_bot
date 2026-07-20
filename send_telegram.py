import html
import json
import os
from pathlib import Path

import requests

ITEMS = Path("new_items.json")


def escaped(item, key, fallback="Нет данных"):
    return html.escape(str(item.get(key) or fallback))


def post_telegram(endpoint, payload):
    response = requests.post(endpoint, data=payload, timeout=25)
    response.raise_for_status()


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

    # This is the only message that triggers a push notification.
    push_text = f"<b>{title}</b>\n💶 {price}"
    post_telegram(
        api + "/sendMessage",
        {
            "chat_id": chat_id,
            "text": push_text,
            "parse_mode": "HTML",
            "disable_web_page_preview": "true",
        },
    )

    # The full card is sent silently, so the push preview contains only title and price.
    card_text = (
        f"🏄 <b>{title}</b>\n\n"
        f"🌍 Площадка: {site}\n"
        f"💶 Цена: <b>{price}</b>\n"
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
            "disable_notification": "true",
        }
    else:
        endpoint = api + "/sendMessage"
        payload = {
            "chat_id": chat_id,
            "text": card_text[:4096],
            "parse_mode": "HTML",
            "disable_web_page_preview": "false",
            "disable_notification": "true",
        }

    post_telegram(endpoint, payload)


def main():
    if not ITEMS.exists():
        return

    for item in json.loads(ITEMS.read_text(encoding="utf-8")):
        send(item)


if __name__ == "__main__":
    main()
