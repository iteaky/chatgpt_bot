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
    description = html.escape((item.get("description") or "Описание отсутствует")[:500])
    summary = escaped(item, "summary", "")
    site = escaped(item, "site", "Vinted")
    url = html.escape(item["url"], quote=True)

    seller = escaped(item, "seller_name")
    rating = escaped(item, "seller_rating")
    reviews = escaped(item, "review_count")

    text = (
        f"🏄 <b>{title}</b>\n\n"
        f"🌍 Площадка: {site}\n"
        f"💶 Цена: <b>{escaped(item, 'price')}</b>\n"
        f"🛡 Комиссия Vinted: {escaped(item, 'buyer_fee')}\n"
        f"📦 Доставка: {escaped(item, 'shipping')}\n"
        f"📏 Размер: {escaped(item, 'size')}\n"
        f"✨ Состояние: {escaped(item, 'condition')}\n\n"
        f"👤 Продавец: {seller}\n"
        f"⭐ Рейтинг: {rating}\n"
        f"💬 Отзывов: {reviews}\n\n"
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
        payload = {
            "chat_id": chat_id,
            "text": text[:4096],
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
