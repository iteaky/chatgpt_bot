import html
import json
import mimetypes
import os
import tempfile
from pathlib import Path

import requests

ITEMS = Path("new_items.json")
DOWNLOAD_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
}


def escaped(item, key, fallback="Нет данных"):
    return html.escape(str(item.get(key) or fallback))


def check_response(response):
    response.raise_for_status()
    data = response.json()
    if not data.get("ok"):
        raise RuntimeError(data)
    return data


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


def build_photo_caption(item):
    title = escaped(item, "title", "Новое wakeboard-объявление")
    price = escaped(item, "price")
    url = html.escape(item["url"], quote=True)
    return f"<b>{title}</b> — <b>{price}</b>\n<a href=\"{url}\">Открыть объявление</a>"


def send_text(api, chat_id, text):
    response = requests.post(
        api + "/sendMessage",
        data={
            "chat_id": chat_id,
            "text": text[:4096],
            "parse_mode": "HTML",
            "disable_web_page_preview": "false",
        },
        timeout=30,
    )
    check_response(response)


def download_image(url):
    temp_dir = tempfile.TemporaryDirectory()
    if not url:
        return temp_dir, None

    try:
        response = requests.get(url, headers=DOWNLOAD_HEADERS, timeout=25)
        response.raise_for_status()
        content_type = response.headers.get("Content-Type", "image/jpeg").split(";", 1)[0]
        if not content_type.startswith("image/"):
            return temp_dir, None

        extension = mimetypes.guess_extension(content_type) or ".jpg"
        path = Path(temp_dir.name) / f"photo{extension}"
        path.write_bytes(response.content)
        if path.stat().st_size > 0:
            return temp_dir, (path, content_type)
    except Exception as error:
        print(f"Could not download main photo: {error}")

    return temp_dir, None


def send_photo(api, chat_id, downloaded, text):
    path, content_type = downloaded
    with path.open("rb") as image_file:
        response = requests.post(
            api + "/sendPhoto",
            data={"chat_id": chat_id, "caption": text[:1024], "parse_mode": "HTML"},
            files={"photo": (path.name, image_file, content_type)},
            timeout=60,
        )
    check_response(response)


def main_image(item):
    if item.get("image"):
        return item["image"]
    images = item.get("images") or []
    return images[0] if images else ""


def send(item):
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "@from78kg")
    api = "https://api.telegram.org/bot" + token
    card_text = build_card(item)
    photo_caption = card_text if len(card_text) <= 1024 else build_photo_caption(item)

    temp_dir, downloaded = download_image(main_image(item))
    try:
        if downloaded:
            try:
                send_photo(api, chat_id, downloaded, photo_caption)
                if photo_caption != card_text:
                    send_text(api, chat_id, card_text)
                return
            except Exception as error:
                print(f"Photo upload failed: {error}")

        send_text(api, chat_id, card_text)
    finally:
        temp_dir.cleanup()


def main():
    if not ITEMS.exists():
        return

    items = json.loads(ITEMS.read_text(encoding="utf-8"))
    print(f"Telegram: sending {len(items)} new listings")
    for item in items:
        send(item)


if __name__ == "__main__":
    main()
