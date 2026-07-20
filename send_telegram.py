import html
import json
import os
from pathlib import Path

import requests

ITEMS = Path("new_items.json")


def escaped(item, key, fallback="Нет данных"):
    return html.escape(str(item.get(key) or fallback))


def post(endpoint, payload):
    response = requests.post(endpoint, data=payload, timeout=30)
    response.raise_for_status()
    data = response.json()
    if not data.get("ok"):
        raise RuntimeError(data)


def build_card(item):
    title = escaped(item, "title", "Новое wakeboard-объявление")
    price = escaped(item, "price")
    description = html.escape(
        (item.get("description_ru") or item.get("description") or "Описание отсутствует")[:700]
    )
    site = escaped(item, "site", "Vinted")
    url = html.escape(item["url"], quote=True)

    return (
        f"<b>{title}</b> — <b>{price}</b>\n\n"
        f"🌍 Площадка: {site}\n"
        f"📏 Размер: {escaped(item, 'size')}\n"
        f"✨ Состояние: {escaped(item, 'condition')}\n\n"
        f"📝 <b>Описание на русском:</b>\n{description}\n\n"
        f'<a href="{url}">Открыть объявление</a>'
    )


def send_single(api, chat_id, image, text):
    if image and len(text) <= 1024:
        post(
            api + "/sendPhoto",
            {
                "chat_id": chat_id,
                "photo": image,
                "caption": text,
                "parse_mode": "HTML",
            },
        )
    else:
        post(
            api + "/sendMessage",
            {
                "chat_id": chat_id,
                "text": text[:4096],
                "parse_mode": "HTML",
                "disable_web_page_preview": "false",
            },
        )


def send(item):
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "@from78kg")
    api = "https://api.telegram.org/bot" + token
    card_text = build_card(item)

    images = []
    for image in item.get("images") or []:
        if image and image not in images:
            images.append(image)
    if not images and item.get("image"):
        images.append(item["image"])
    images = images[:10]

    if len(images) < 2 or len(card_text) > 1024:
        send_single(api, chat_id, images[0] if images else "", card_text)
        return

    media = []
    for index, image in enumerate(images):
        entry = {"type": "photo", "media": image}
        if index == 0:
            entry["caption"] = card_text
            entry["parse_mode"] = "HTML"
        media.append(entry)

    try:
        post(
            api + "/sendMediaGroup",
            {
                "chat_id": chat_id,
                "media": json.dumps(media, ensure_ascii=False),
            },
        )
    except Exception as error:
        print(f"Album failed, falling back to main photo: {error}")
        send_single(api, chat_id, images[0], card_text)


def main():
    if not ITEMS.exists():
        return

    for item in json.loads(ITEMS.read_text(encoding="utf-8")):
        send(item)


if __name__ == "__main__":
    main()
