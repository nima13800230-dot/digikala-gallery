import re
import time
from urllib.parse import urlparse

import requests
from flask import Flask, request, jsonify, send_from_directory

app = Flask(__name__, static_folder="static")
BASE = "https://api.digikala.com"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 Chrome/120.0 Mobile Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "fa-IR,fa;q=0.9,en;q=0.8",
    "Referer": "https://www.digikala.com/",
}
session = requests.Session()
session.headers.update(HEADERS)


def get_json(url):
    response = session.get(url, timeout=25)
    response.raise_for_status()
    return response.json()


def extract_slug(link):
    parsed = urlparse(link)
    if parsed.hostname not in ("digikala.com", "www.digikala.com"):
        raise ValueError("لینک باید از دامنه digikala.com باشد.")
    match = re.search(r"/search/category-([^/?#]+)/?", parsed.path)
    if not match:
        raise ValueError("لینک باید از نوع صفحه دسته‌بندی دیجی‌کالا باشد.")
    return match.group(1)


def image_urls(obj):
    found, seen = set(), set()

    def walk(value):
        if isinstance(value, (dict, list)):
            if id(value) in seen:
                return
            seen.add(id(value))
        if isinstance(value, dict):
            for key, item in value.items():
                if isinstance(item, str) and re.search(r"(url|src|image|photo|picture)", key, re.I):
                    if item.startswith("https://") and re.search(r"(dkstatics|digikala)", item, re.I):
                        found.add(item.replace(" ", "%20"))
                elif isinstance(item, (dict, list)):
                    walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)

    walk(obj)
    return sorted(found)


@app.get("/")
def index():
    return send_from_directory("static", "index.html")


@app.get("/health")
def health():
    return jsonify(ok=True, service="digikala-gallery")


@app.post("/api/extract")
def extract():
    body = request.get_json(silent=True) or {}
    link = (body.get("url") or "").strip()
    try:
        slug = extract_slug(link)
        first = get_json(f"{BASE}/v1/categories/{slug}/search/?page=1")
        data = first.get("data") or {}
        pager = data.get("pager") or {}
        pages = max(1, min(int(pager.get("total_pages") or 1), 100))

        products = {}

        def add(items):
            for item in items or []:
                product_id = item.get("id") or (item.get("product") or {}).get("id")
                if product_id:
                    products[str(product_id)] = item

        add(data.get("products"))
        for page in range(2, pages + 1):
            payload = get_json(f"{BASE}/v1/categories/{slug}/search/?page={page}")
            add((payload.get("data") or {}).get("products"))
            time.sleep(0.12)

        output, errors = [], 0
        for index, product_id in enumerate(products, 1):
            try:
                detail = get_json(f"{BASE}/v2/product/{product_id}/")
                product = ((detail.get("data") or {}).get("product")) or {}
                urls = image_urls(product.get("images") or product)
                if not urls:
                    urls = image_urls(products[product_id])
                output.extend({"id": product_id, "image": url} for url in urls)
            except Exception:
                errors += 1
            if index % 8 == 0:
                time.sleep(0.15)

        unique, seen = [], set()
        for item in output:
            if item["image"] not in seen:
                seen.add(item["image"])
                unique.append(item)

        return jsonify(ok=True, category=slug, pages=pages, products=len(products),
                       images=unique, failed_products=errors)
    except requests.HTTPError as error:
        status = error.response.status_code if error.response is not None else 502
        return jsonify(ok=False, error=f"دیجی‌کالا پاسخ خطای HTTP {status} داد؛ ممکن است API محدود یا تغییر کرده باشد."), 502
    except Exception as error:
        return jsonify(ok=False, error=str(error)), 400


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
