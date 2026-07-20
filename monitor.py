import json
import re
import sys
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

SITES = {
    "Vinted.sk": {
        "url": "https://www.vinted.sk/catalog?search_text=wakeboard&order=newest_first",
        "language": "sk-SK,sk;q=0.9,en;q=0.7",
        "host": "www.vinted.sk",
    },
    "Vinted.at": {
        "url": "https://www.vinted.at/catalog?search_text=wakeboard&order=newest_first",
        "language": "de-AT,de;q=0.9,en;q=0.7",
        "host": "www.vinted.at",
    },
}
STATE = Path("seen.json")
OUTPUT = Path("new_items.json")
BASE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Cache-Control": "no-cache",
}


def load_seen():
    if not STATE.exists():
        return set()
    return set(json.loads(STATE.read_text(encoding="utf-8")).get("seen", []))


def new_session(language):
    session = requests.Session()
    session.headers.update({**BASE_HEADERS, "Accept-Language": language})
    return session


def get(session, url, expected_host):
    response = session.get(url, timeout=25, allow_redirects=True)
    final_host = urlparse(response.url).netloc
    print(
        f"GET {url} -> {response.status_code} "
        f"final={response.url} ({len(response.content)} bytes)"
    )
    response.raise_for_status()
    if final_host != expected_host:
        raise RuntimeError(
            f"Unexpected marketplace redirect: expected {expected_host}, got {final_host}"
        )
    return response


def find_items(session, search_url, expected_host):
    response = get(session, search_url, expected_host)
    soup = BeautifulSoup(response.text, "html.parser")
    result = []

    for link in soup.select('a[href*="/items/"]'):
        item_url = urljoin(search_url, link.get("href", "")).split("?")[0]
        match = re.search(r"/items/(\d+)", item_url)
        if match:
            result.append((match.group(1), item_url))

    unique = list(dict.fromkeys(result))[:40]
    print(f"Parsed {len(unique)} item links from {expected_host}")
    return unique


def meta_value(soup, name):
    tag = soup.find("meta", attrs={"property": name})
    if not tag:
        tag = soup.find("meta", attrs={"name": name})
    return tag.get("content", "").strip() if tag else ""


def flatten_json(value):
    if isinstance(value, dict):
        for key, child in value.items():
            yield str(key), child
            yield from flatten_json(child)
    elif isinstance(value, list):
        for child in value:
            yield from flatten_json(child)


def embedded_json(soup):
    values = []
    for script in soup.find_all("script"):
        raw = script.string or script.get_text("", strip=True)
        if not raw or len(raw) < 2:
            continue
        if script.get("type") == "application/ld+json" or raw.startswith(("{", "[")):
            try:
                values.append(json.loads(raw))
            except json.JSONDecodeError:
                continue
    return values


def first_json_value(documents, keys):
    wanted = {key.casefold() for key in keys}
    for document in documents:
        for key, value in flatten_json(document):
            if key.casefold() in wanted and value not in (None, "", [], {}):
                return value
    return None


def regex_value(text, patterns):
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
        if match:
            return match.group(1).strip()
    return ""


def json_string_from_source(source, keys):
    for key in keys:
        patterns = [
            rf'"{re.escape(key)}"\s*:\s*"([^"\\]*(?:\\.[^"\\]*)*)"',
            rf'\\"{re.escape(key)}\\"\s*:\s*\\"([^"\\]*(?:\\.[^"\\]*)*)\\"',
        ]
        for pattern in patterns:
            match = re.search(pattern, source, re.IGNORECASE)
            if match:
                raw = match.group(1)
                try:
                    return json.loads(f'"{raw}"')
                except json.JSONDecodeError:
                    return raw.replace("\\/", "/").replace('\\"', '"')
    return ""


def normalize_size(value):
    if value is None:
        return ""
    if isinstance(value, dict):
        for key in ("title", "name", "label", "value"):
            if value.get(key):
                return str(value[key]).strip()
    text = str(value).strip()
    match = re.search(
        r"\b(XXXS|XXS|XS|S/M|S|M/L|M|L/XL|L|XL|XXL|XXXL|\d{2,3})\b",
        text,
        re.IGNORECASE,
    )
    return match.group(1).upper() if match else text


def normalize_condition(value):
    if value is None:
        return ""
    if isinstance(value, dict):
        for key in ("title", "name", "label", "value"):
            if value.get(key):
                return str(value[key]).strip()
    return str(value).strip()


def translate_to_russian(text):
    text = (text or "").strip()
    if not text:
        return ""
    try:
        response = requests.get(
            "https://translate.googleapis.com/translate_a/single",
            params={
                "client": "gtx",
                "sl": "auto",
                "tl": "ru",
                "dt": "t",
                "q": text[:1500],
            },
            headers=BASE_HEADERS,
            timeout=20,
        )
        response.raise_for_status()
        data = response.json()
        translated = "".join(part[0] for part in data[0] if part and part[0])
        return translated.strip() or text
    except Exception as error:
        print(f"Translation failed: {type(error).__name__}: {error}", file=sys.stderr)
        return text


def clean_title(title):
    title = (title or "").strip()
    title = re.sub(
        r"\s*[|–—-]\s*Vinted(?:\.[a-z]{2})?.*$",
        "",
        title,
        flags=re.IGNORECASE,
    )
    title = re.sub(r"\s*\|\s*Vinted.*$", "", title, flags=re.IGNORECASE)
    title = re.sub(r"\bVinted\b", "", title, flags=re.IGNORECASE)
    title = re.sub(r"\s{2,}", " ", title).strip(" -–—|")
    return title or "Новое объявление"


def normalize_price(value, documents, source, fallback_text):
    currency = first_json_value(
        documents,
        ["currency_code", "currency", "price_currency", "currencyCode"],
    )
    currency = str(currency or "EUR").upper()
    amount = None

    if isinstance(value, dict):
        amount = value.get("amount") or value.get("value") or value.get("price")
        currency = str(
            value.get("currency_code")
            or value.get("currency")
            or value.get("currencyCode")
            or currency
        ).upper()
    elif value not in (None, ""):
        match = re.search(
            r"(\d+(?:[.,]\d{1,2})?)\s*(EUR|USD|GBP|CZK|PLN|HUF|CHF|€|\$|£)?",
            str(value),
            re.IGNORECASE,
        )
        if match:
            amount = match.group(1)
            symbol = (match.group(2) or "").upper()
            currency = {"€": "EUR", "$": "USD", "£": "GBP"}.get(
                symbol,
                symbol or currency,
            )

    if amount is None:
        amount = regex_value(
            fallback_text,
            [
                r"(?:€|EUR)\s*(\d+(?:[.,]\d{1,2})?)",
                r"(\d+(?:[.,]\d{1,2})?)\s*(?:€|EUR)",
            ],
        )
        if amount:
            currency = "EUR"

    if amount is None:
        source_amount = json_string_from_source(source, ["amount", "price_amount"])
        if source_amount and re.fullmatch(r"\d+(?:[.,]\d{1,2})?", source_amount):
            amount = source_amount

    return f"{amount} {currency}" if amount is not None else "Не удалось определить"


def is_listing_photo(url):
    if not isinstance(url, str):
        return False
    clean = url.replace("\\/", "/").strip()
    if not clean.startswith("http"):
        return False
    host = urlparse(clean).netloc.casefold()
    if "vinted.net" not in host:
        return False
    lowered = clean.casefold()
    return not any(word in lowered for word in ("avatar", "profile", "icon", "logo", "badge"))


def best_photo_url(photo):
    if isinstance(photo, str):
        return photo
    if not isinstance(photo, dict):
        return ""

    for key in (
        "full_size_url",
        "high_resolution_url",
        "original_url",
        "large_url",
        "image_url",
        "url",
    ):
        value = photo.get(key)
        if is_listing_photo(value):
            return value

    thumbnails = photo.get("thumbnails") or []
    if isinstance(thumbnails, list):
        ranked = sorted(
            (item for item in thumbnails if isinstance(item, dict)),
            key=lambda item: int(item.get("width") or 0) * int(item.get("height") or 0),
            reverse=True,
        )
        for thumbnail in ranked:
            value = thumbnail.get("url")
            if is_listing_photo(value):
                return value
    return ""


def extract_photo_lists(value):
    result = []
    if isinstance(value, dict):
        for key, child in value.items():
            if key.casefold() in {"photos", "images", "pictures"} and isinstance(child, list):
                photos = [best_photo_url(item) for item in child]
                photos = [photo for photo in photos if photo]
                if photos:
                    result.extend(photos)
            result.extend(extract_photo_lists(child))
    elif isinstance(value, list):
        for child in value:
            result.extend(extract_photo_lists(child))
    return result


def fetch_item_api(session, expected_host, item_id, referer):
    api_url = f"https://{expected_host}/api/v2/items/{item_id}"
    try:
        response = session.get(
            api_url,
            headers={
                "Accept": "application/json, text/plain, */*",
                "Referer": referer,
                "X-Requested-With": "XMLHttpRequest",
            },
            timeout=25,
        )
        print(f"GET {api_url} -> {response.status_code} ({len(response.content)} bytes)")
        if response.status_code != 200:
            return None
        return response.json()
    except Exception as error:
        print(f"Item API failed for {item_id}: {type(error).__name__}: {error}", file=sys.stderr)
        return None


def photo_identity(url):
    match = re.search(r"/t/([^/?]+)", url)
    if match:
        return match.group(1)
    return url.split("?", 1)[0]


def image_is_reachable(session, url, referer):
    try:
        response = session.get(
            url,
            headers={"Referer": referer, "Range": "bytes=0-2047"},
            stream=True,
            timeout=15,
        )
        content_type = response.headers.get("Content-Type", "").casefold()
        ok = response.status_code in {200, 206} and content_type.startswith("image/")
        response.close()
        return ok
    except requests.RequestException:
        return False


def collect_images(session, soup, documents, source, primary, api_data, referer):
    candidates = []

    if api_data:
        candidates.extend(extract_photo_lists(api_data))

    for document in documents:
        candidates.extend(extract_photo_lists(document))

    if primary:
        candidates.append(primary)

    for tag in soup.find_all("meta"):
        if tag.get("property") in {"og:image", "og:image:url", "og:image:secure_url"}:
            candidates.append(tag.get("content", ""))

    # Vinted may serialize the gallery as escaped JSON inside a script.
    for match in re.findall(
        r'https?:\\?/\\?/[^"\s<>]+?vinted\.net[^"\s<>]+',
        source,
        re.IGNORECASE,
    ):
        candidates.append(match.replace("\\/", "/"))

    unique = []
    identities = set()
    for candidate in candidates:
        if not isinstance(candidate, str):
            continue
        clean = candidate.replace("\\/", "/").replace("&amp;", "&").strip()
        if not is_listing_photo(clean):
            continue
        identity = photo_identity(clean)
        if identity in identities:
            continue
        identities.add(identity)
        unique.append(clean)

    working = []
    for image in unique:
        if image_is_reachable(session, image, referer):
            working.append(image)
        else:
            print(f"Skipping unreachable photo: {image[:120]}")
        if len(working) == 10:
            break

    print(
        f"Collected {len(unique)} unique photo candidates; "
        f"validated {len(working)} photos"
    )
    return working


def read_meta(session, url, expected_host, item_id):
    response = get(session, url, expected_host)
    soup = BeautifulSoup(response.text, "html.parser")
    documents = embedded_json(soup)
    page_text = " ".join(soup.stripped_strings)
    source = response.text
    api_data = fetch_item_api(session, expected_host, item_id, response.url)
    if api_data:
        documents.append(api_data)

    original_title = clean_title(meta_value(soup, "og:title") or "Новое объявление")
    translated_title = clean_title(translate_to_russian(original_title))
    description = meta_value(soup, "og:description") or meta_value(soup, "description")
    primary_image = meta_value(soup, "og:image")
    images = collect_images(
        session,
        soup,
        documents,
        source,
        primary_image,
        api_data,
        response.url,
    )

    raw_price = first_json_value(documents, ["price", "item_price", "base_price"])
    price = normalize_price(
        raw_price,
        documents,
        source,
        f"{original_title} {description} {page_text}",
    )

    size = normalize_size(
        first_json_value(
            documents,
            ["size_title", "size", "item_size", "size_name", "size_label"],
        )
    )
    if not size:
        size = normalize_size(
            json_string_from_source(
                source,
                ["size_title", "size_name", "size_label", "item_size"],
            )
        )
    if not size:
        size = normalize_size(
            regex_value(
                page_text,
                [
                    r"(?:Size|Veľkosť|Größe)\s*[:\-]?\s*(XXXS|XXS|XS|S/M|S|M/L|M|L/XL|L|XL|XXL|XXXL|\d{2,3})\b",
                    r"\b(?:Größe|Veľkosť)\s+(XXXS|XXS|XS|S/M|S|M/L|M|L/XL|L|XL|XXL|XXXL)\b",
                ],
            )
        )
    if not size:
        size = normalize_size(f"{original_title} {description}")

    condition = normalize_condition(
        first_json_value(
            documents,
            ["status_title", "condition_title", "item_condition", "condition", "status"],
        )
    )
    if not condition:
        condition = normalize_condition(
            json_string_from_source(
                source,
                ["status_title", "condition_title", "item_condition"],
            )
        )
    if not condition:
        condition = regex_value(
            page_text,
            [
                r"(?:Condition|Stav|Zustand)\s*[:\-]?\s*([^|•]{2,50})",
                r"\b(Neu mit Etikett|Neu ohne Etikett|Sehr gut|Gut|Zufriedenstellend|Nové s visačkou|Nové bez visačky|Veľmi dobré|Dobré|Uspokojivé)\b",
            ],
        )

    translated_description = translate_to_russian(description)
    translated_condition = translate_to_russian(condition) if condition else ""

    print(
        "Parsed details:",
        {
            "title": translated_title,
            "price": price,
            "size": size,
            "condition": condition,
            "photos": len(images),
            "translated": translated_description[:80],
        },
    )

    return {
        "url": response.url,
        "title": translated_title,
        "original_title": original_title,
        "description": description,
        "description_ru": translated_description,
        "image": images[0] if images else primary_image,
        "images": images,
        "price": price,
        "size": size or "Не указан",
        "condition": translated_condition or condition or "Не указано",
    }


def main():
    seen = load_seen()
    first_run = not seen
    fresh = []
    successful_sites = 0

    for site, config in SITES.items():
        search_url = config["url"]
        expected_host = config["host"]
        session = new_session(config["language"])

        try:
            items = find_items(session, search_url, expected_host)
            successful_sites += 1
        except Exception as error:
            print(f"ERROR while loading {site}: {type(error).__name__}: {error}", file=sys.stderr)
            continue

        for item_id, item_url in items:
            key = f"{site}:{item_id}"
            if key in seen:
                continue

            try:
                item = read_meta(session, item_url, expected_host, item_id)
            except Exception as error:
                print(
                    f"ERROR while loading item {item_url}: "
                    f"{type(error).__name__}: {error}",
                    file=sys.stderr,
                )
                continue

            item["site"] = site
            fresh.append(item)
            seen.add(key)

    if successful_sites == 0:
        print("Both Vinted marketplaces failed", file=sys.stderr)
        return 1

    STATE.write_text(
        json.dumps({"seen": sorted(seen)[-3000:]}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    OUTPUT.write_text(
        json.dumps([] if first_run else fresh[:15], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"Found {len(fresh)} new items; baseline={first_run}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
