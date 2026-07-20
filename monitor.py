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


def read_meta(session, url, expected_host):
    response = get(session, url, expected_host)
    soup = BeautifulSoup(response.text, "html.parser")

    def value(name):
        tag = soup.find("meta", attrs={"property": name})
        return tag.get("content", "") if tag else ""

    return {
        "url": response.url,
        "title": value("og:title") or "Новое wakeboard-объявление",
        "description": value("og:description"),
        "image": value("og:image"),
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
                "Проверь цену, размер, состояние и комплектность."
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
