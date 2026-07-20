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


def download_images(urls):
    downloaded = []
    temp_dir = tempfile.TemporaryDirectory()

    for index, url in enumerate(urls[:10]):
        try:
            response = requests.get(url, headers=DOWNLOAD_HEADERS, timeout=25)
            response.raise_for_status()
            content_type = response.headers.get("Content-Type", "image/jpeg").split(";", 1)[0]
            if not content_type.startswith("image/"):
                continue
            extension = mimetypes.guess_extension(content_type) or ".jpg"
            path = Path(temp_dir.name) / f"photo_{index}{extension}"
            path.write_bytes(response.content)
            if path.stat().st_size > 0:
                downloaded.append((path, content_type))
        except Exception as error:
            print(f"Could not download photo {index + 1}: {error}")

    return temp_dir, downloaded


def send_album(api, chat_id, downloaded, text):
    media = []
    files = {}

    for index, (path, content_type) in enumerate(downloaded[:10]):
        attachment = f"photo{index}"
        entry = {"type": "photo", "media": f"attach://{attachment}"}
        if index == 0:
            entry["caption"] = text[:1024]
            entry["parse_mode"] = "HTML"
        media.append(entry)
        files[attachment] = (path.name, path.open("rb"), content_type)

    try:
        response = requests.post(
            api + "/sendMediaGroup",
            data={"chat_id": chat_id, "media": json.dumps(media, ensure_ascii=False)},
            files=files,
            timeout=90,
        )
        check_response(response)
    finally:
        for _, file_tuple in files.items():
            file_tuple[1].close()


def send_photo(api, chat_id, downloaded, text):
    path, content_type = downloaded[0]
    with path.open("rb") as image_file:
        response = requests.post(
            api + "/sendPhoto",
            data={"chat_id": chat_id, "caption": text[:1024], "parse_mode": "HTML"},
            files={"photo": (path.name, image_file, content_type)},
            timeout=60,
        )
    check_response(response)


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

    temp_dir, downloaded = download_images(images)
    try:
        if len(downloaded) >= 2 and len(card_text) <= 1024:
            try:
                send_album(api, chat_id, downloaded, card_text)
                return
            except Exception as error:
                print(f"Album upload failed: {error}")

        if downloaded and len(card_text) <= 1024:
            try:
                send_photo(api, chat_id, downloaded, card_text)
                return
            except Exception as error:
                print(f"Photo upload failed: {error}")

        # A text notification must still be delivered even when every image fails.
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
