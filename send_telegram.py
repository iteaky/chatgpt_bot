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
TELEGRAM_CAPTION_LIMIT = 1024


def escaped(item, key, fallback="Нет данных"):
    return html.escape(str(item.get(key) or fallback))


def check_response(response):
    response.raise_for_status()
    data = response.json()
    if not data.get("ok"):
        raise RuntimeError(data)
    return data


def trim_text(text, max_length):
    text = (text or "").strip()
    if len(text) <= max_length:
        return text
    if max_length <= 1:
        return "…"[:max_length]
    return text[: max_length - 1].rstrip() + "…"


def build_card(item, caption_limit=None):
    title = escaped(item, "title", "Новое wakeboard-объявление")
    price = escaped(item, "price")
    site = escaped(item, "site", "Vinted")
    size = escaped(item, "size")
    condition = escaped(item, "condition")
    url = html.escape(item["url"], quote=True)
    raw_description = (
        item.get("description_ru")
        or item.get("description")
        or "Описание отсутствует"
    )

    prefix = (
        f"<b>{title}</b> — <b>{price}</b>\n\n"
        f"🌍 Площадка: {site}\n"
        f"📏 Размер: {size}\n"
        f"✨ Состояние: {condition}\n\n"
        f"📝 <b>Описание на русском:</b>\n"
    )
    suffix = f'\n\n<a href="{url}">Открыть объявление</a>'

    if caption_limit is None:
        description = html.escape(str(raw_description)[:700])
        return prefix + description + suffix

    # Telegram counts the final rendered caption, while HTML tags also occupy
    # space in the API payload. Keep a small safety margin to avoid rejections.
    available = max(0, caption_limit - len(prefix) - len(suffix) - 16)
    description = html.escape(trim_text(str(raw_description), available))
    card = prefix + description + suffix

    if len(card) <= caption_limit:
        return card

    # Escaping can increase the payload length (for example, '&' -> '&amp;').
    # Reduce the source text until the complete HTML caption fits.
    overflow = len(card) - caption_limit
    available = max(0, available - overflow - 8)
    description = html.escape(trim_text(str(raw_description), available))
    return (prefix + description + suffix)[:caption_limit]


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
            data={"chat_id": chat_id, "caption": text, "parse_mode": "HTML"},
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

    temp_dir, downloaded = download_image(main_image(item))
    try:
        if downloaded:
            caption = build_card(item, TELEGRAM_CAPTION_LIMIT)
            try:
                send_photo(api, chat_id, downloaded, caption)
                return
            except Exception as error:
                print(f"Photo upload failed: {error}")

        # If no valid photo is available, send one complete text message.
        send_text(api, chat_id, build_card(item))
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
