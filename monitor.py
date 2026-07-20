import json
import re
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


def load_seen():
    if not STATE.exists():
        return set()
    return set(json.loads(STATE.read_text(encoding="utf-8")).get("seen", []))


def find_items(search_url):
    response = requests.get(search_url, timeout=25)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    result = []

    for link in soup.select('a[href*="/items/"]'):
        item_url = urljoin(search_url, link.get("href", "")).split("?")[0]
        match = re.search(r"/items/(\d+)", item_url)
        if match:
            result.append((match.group(1), item_url))

    return list(dict.fromkeys(result))[:40]


def read_meta(url):
    response = requests.get(url, timeout=25)
    response.raise_for_status()
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

    for site, search_url in SITES.items():
        for item_id, item_url in find_items(search_url):
            key = f"{site}:{item_id}"
            if key in seen:
                continue

            item = read_meta(item_url)
            item["site"] = site
            item["summary"] = (
                "Новое объявление по запросу wakeboard. "
                "Проверь цену, размер, состояние и комплектность."
            )
            fresh.append(item)
            seen.add(key)

    STATE.write_text(
        json.dumps({"seen": sorted(seen)[-3000:]}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    OUTPUT.write_text(
        json.dumps([] if first_run else fresh[:15], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"Found {len(fresh)} new items; baseline={first_run}")


if __name__ == "__main__":
    main()
