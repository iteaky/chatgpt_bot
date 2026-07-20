import json
import re
import sys
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

SITES = {
    "Vinted.sk": "https://www.vinted.sk/catalog?search_text=wakeboard&order=newest_first",
    "Vinted.at": "https://www.vinted.at/catalog?search_text=wakeboard&order=newest_first",
}
STATE = Path("seen.json")
OUTPUT = Path("new_items.json")
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "sk-SK,sk;q=0.9,de-AT;q=0.8,en;q=0.7",
    "Cache-Control": "no-cache",
}


def load_seen():
    if not STATE.exists():
        return set()
    return set(json.loads(STATE.read_text(encoding="utf-8")).get("seen", []))


def get(session, url):
    response = session.get(url, headers=HEADERS, timeout=25, allow_redirects=True)
    print(f"GET {url} -> {response.status_code} ({len(response.content)} bytes)")
    response.raise_for_status()
    return response


def find_items(session, search_url):
    response = get(session, search_url)
    soup = BeautifulSoup(response.text, "html.parser")
    result = []

    for link in soup.select('a[href*="/items/"]'):
        item_url = urljoin(search_url, link.get("href", "")).split("?")[0]
        match = re.search(r"/items/(\d+)", item_url)
        if match:
            result.append((match.group(1), item_url))

    unique = list(dict.fromkeys(result))[:40]
    print(f"Parsed {len(unique)} item links from {search_url}")
    return unique


def read_meta(session, url):
    response = get(session, url)
    soup = BeautifulSoup(response.text, "html.parser")

    def value(name):
        tag = soup.find("meta", attrs={"property": name})
        return tag.get("content", "") if tag else ""

    return {
        "url": url,
        "title": value("og:title") or "Новое wakeboard-объявление",
        "description": value("og:description"),
        "image": value("og:image"),
    }


def main():
    seen = load_seen()
    first_run = not seen
    fresh = []
    successful_sites = 0
    session = requests.Session()

    for site, search_url in SITES.items():
        try:
            items = find_items(session, search_url)
            successful_sites += 1
        except Exception as error:
            print(f"ERROR while loading {site}: {type(error).__name__}: {error}", file=sys.stderr)
            continue

        for item_id, item_url in items:
            key = f"{site}:{item_id}"
            if key in seen:
                continue

            try:
                item = read_meta(session, item_url)
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
