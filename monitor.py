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


def money_from_value(value):
    if value is None:
        return ""
    if isinstance(value, dict):
        amount = value.get("amount") or value.get("value")
        currency = value.get("currency_code") or value.get("currency") or "EUR"
        if amount is not None:
            return f"{amount} {currency}"
    text = str(value).strip()
    if not text:
        return ""
    if re.fullmatch(r"\d+(?:[.,]\d{1,2})?", text):
        return f"{text} EUR"
    return text


def regex_value(text, patterns):
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return match.group(1).strip()
    return ""


def read_meta(session, url, expected_host):
    response = get(session, url, expected_host)
    soup = BeautifulSoup(response.text, "html.parser")
    documents = embedded_json(soup)
    page_text = " ".join(soup.stripped_strings)
    source = response.text

    title = meta_value(soup, "og:title") or "Новое wakeboard-объявление"
    description = meta_value(soup, "og:description") or meta_value(soup, "description")
    image = meta_value(soup, "og:image")

    price = money_from_value(first_json_value(documents, [
        "price", "item_price", "base_price", "discounted_price"
    ]))
    if not price:
        price = regex_value(
            f"{title} {description} {page_text}",
            [r"(?:€|EUR)\s*(\d+(?:[.,]\d{1,2})?)", r"(\d+(?:[.,]\d{1,2})?)\s*(?:€|EUR)"],
        )
        if price:
            price = f"{price} EUR"

    buyer_fee = money_from_value(first_json_value(documents, [
        "buyer_protection_fee", "buyer_fee", "service_fee", "protection_fee"
    ]))
    if not buyer_fee:
        buyer_fee = regex_value(
            page_text,
            [
                r"(?:buyer protection|käuferschutz|ochrana kupujúceho)[^€\d]{0,40}(\d+(?:[.,]\d{1,2})?\s*€)",
                r"(\d+(?:[.,]\d{1,2})?\s*€)[^\n]{0,40}(?:buyer protection|käuferschutz|ochrana kupujúceho)",
            ],
        )

    shipping = money_from_value(first_json_value(documents, [
        "shipping_price", "shipping_cost", "postage_price", "delivery_price"
    ]))
    if not shipping:
        shipping = regex_value(
            page_text,
            [
                r"(?:shipping|versand|doprava|poštovné)[^€\d]{0,40}(\d+(?:[.,]\d{1,2})?\s*€)",
                r"(\d+(?:[.,]\d{1,2})?\s*€)[^\n]{0,40}(?:shipping|versand|doprava|poštovné)",
            ],
        )

    seller_name = first_json_value(documents, [
        "seller_name", "username", "login", "user_name"
    ])
    seller_rating = first_json_value(documents, [
        "rating", "feedback_reputation", "seller_rating", "average_rating"
    ])
    review_count = first_json_value(documents, [
        "feedback_count", "reviews_count", "review_count", "ratings_count"
    ])

    if not seller_rating:
        seller_rating = regex_value(
            page_text,
            [
                r"(\d(?:[.,]\d{1,2})?)\s*(?:/\s*5|★)",
                r"(?:rating|bewertung|hodnotenie)\s*[:\-]?\s*(\d(?:[.,]\d{1,2})?)",
            ],
        )

    size = first_json_value(documents, ["size_title", "size", "item_size"])
    condition = first_json_value(documents, [
        "status", "condition", "item_condition", "status_title"
    ])

    # Keep a small diagnostic hint in Actions logs without exposing cookies.
    print(
        "Parsed details:",
        {
            "price": price,
            "buyer_fee": buyer_fee,
            "shipping": shipping,
            "seller": seller_name,
            "rating": seller_rating,
            "reviews": review_count,
        },
    )

    return {
        "url": response.url,
        "title": title,
        "description": description,
        "image": image,
        "price": price or "Не удалось определить",
        "buyer_fee": buyer_fee or "Не показана публично",
        "shipping": shipping or "Рассчитывается Vinted по адресу и способу доставки",
        "seller_name": str(seller_name) if seller_name else "Не удалось определить",
        "seller_rating": str(seller_rating) if seller_rating else "Нет данных",
        "review_count": str(review_count) if review_count else "Нет данных",
        "size": str(size) if size else "Не указан",
        "condition": str(condition) if condition else "Не указано",
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
                item = read_meta(session, item_url, expected_host)
            except Exception as error:
                print(f"ERROR while loading item {item_url}: {type(error).__name__}: {error}", file=sys.stderr)
                continue

            item["site"] = site
            item["summary"] = (
                "Новое объявление по запросу wakeboard. "
                "Проверь размер, состояние, комплектность и итоговую цену перед покупкой."
            )
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
