#!/usr/bin/env python3
"""
Loop deck builder.

Normally run by GitHub Actions (.github/workflows/build.yml). It reads the
"Products" tab of the Loop Google Sheet (via the Apps Script URL in the
LOOP_SHEET_URL setting) and writes index.html + img/ into the site folder.
Without LOOP_SHEET_URL it falls back to products.csv next to this file.

For each row it fills in whatever you left blank: name, photo, price, blurb.
It reads the page's structured product data (schema.org JSON-LD) first, then
Open Graph tags. Anything you typed yourself in the CSV always wins.

Photos are downloaded, shrunk, and saved into img/, so the game never
depends on a retailer's server while friends are playing.

Rows it couldn't fill go into build_report.txt so you know which to fix by hand.
Amazon and some big-box sites block automated requests; use the brand's own
product page instead (it usually has the cleanest photo anyway).
"""
import csv, hashlib, html, io, json, os, re, sys, time
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from PIL import Image

HERE = Path(__file__).parent
CSV_PATH = HERE / "products.csv"
TEMPLATE = HERE / "template.html"
SHEET_URL = os.environ.get("LOOP_SHEET_URL", "").strip()
DIST = Path(os.environ.get("LOOP_OUT") or HERE / "dist")
IMG_DIR = DIST / "img"
CACHE = HERE / ".cache"          # fetched page metadata, so re-runs are fast
REPORT = HERE / "build_report.txt"

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/128.0 Safari/537.36")
HEADERS = {"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9"}
IMG_MAX = 640                    # px, longest side
BLURB_MAX = 110                  # characters

# category keyword -> fallback icon when no photo
ICON_RULES = [("bath", "bath"), ("swing", "seat"), ("gym", "mat"), ("mat", "mat"),
              ("walker", "mobility"), ("ride", "mobility"), ("climb", "mobility"),
              ("jump", "mobility"), ("table", "sound"), ("toy", "sound")]


def icon_for(category):
    c = (category or "").lower()
    for kw, icon in ICON_RULES:
        if kw in c:
            return icon
    return "seat"


def clean(text):
    text = html.unescape(re.sub(r"<[^>]+>", " ", text or ""))
    return re.sub(r"\s+", " ", text).strip()


def shorten(text, n=BLURB_MAX):
    text = clean(text)
    first_sentence = re.split(r"(?<=[.!?])\s", text, maxsplit=1)[0]
    if 25 <= len(first_sentence) <= n:
        return first_sentence
    if len(text) <= n:
        return text
    cut = text[:n].rsplit(" ", 1)[0].rstrip(",;:-")
    return cut + "…"


# ---------------- page metadata ----------------
def find_product_ld(data):
    """Walk JSON-LD (dicts, lists, @graph) and return the first Product node."""
    if isinstance(data, list):
        for d in data:
            hit = find_product_ld(d)
            if hit:
                return hit
    elif isinstance(data, dict):
        t = data.get("@type")
        types = t if isinstance(t, list) else [t]
        if any(str(x).lower() in ("product", "productgroup") for x in types):
            return data
        for key in ("@graph", "mainEntity", "itemListElement"):
            if key in data:
                hit = find_product_ld(data[key])
                if hit:
                    return hit
    return None


def first(v):
    if isinstance(v, list):
        return first(v[0]) if v else None
    if isinstance(v, dict):
        return v.get("url") or v.get("contentUrl") or v.get("@id")
    return v


def ld_price(offers):
    if isinstance(offers, list):
        for o in offers:
            p = ld_price(o)
            if p:
                return p
        return None
    if isinstance(offers, dict):
        for k in ("price", "lowPrice", "highPrice"):
            if offers.get(k) not in (None, ""):
                return offers[k]
        if "priceSpecification" in offers:
            return ld_price(offers["priceSpecification"])
    return None


def scrape(url):
    key = hashlib.sha1(url.encode()).hexdigest()[:16]
    cached = CACHE / f"{key}.json"
    if cached.exists():
        return json.loads(cached.read_text())

    r = requests.get(url, headers=HEADERS, timeout=20)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    meta = {}

    for tag in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(tag.string or "")
        except Exception:
            continue
        prod = find_product_ld(data)
        if prod:
            if prod.get("hasVariant") and not prod.get("offers"):
                prod = {**first_variant(prod), **{k: v for k, v in prod.items() if v}}
            brand = prod.get("brand")
            brand = brand.get("name") if isinstance(brand, dict) else brand
            meta.update({
                "name": clean(prod.get("name")),
                "brand": clean(brand) if brand else "",
                "photo": first(prod.get("image")),
                "description": clean(prod.get("description")),
                "price": ld_price(prod.get("offers")),
            })
            break

    def og(prop):
        t = soup.find("meta", attrs={"property": prop}) or soup.find("meta", attrs={"name": prop})
        return t.get("content") if t and t.get("content") else None

    meta.setdefault("name", None)
    meta["name"] = meta.get("name") or clean(og("og:title") or (soup.title.string if soup.title else ""))
    meta["photo"] = meta.get("photo") or og("og:image") or og("twitter:image")
    meta["description"] = meta.get("description") or clean(og("og:description") or og("description"))
    meta["price"] = meta.get("price") or og("product:price:amount") or og("og:price:amount")
    if meta.get("photo"):
        meta["photo"] = urljoin(url, meta["photo"])

    CACHE.mkdir(exist_ok=True)
    cached.write_text(json.dumps(meta))
    return meta


def first_variant(prod):
    v = prod.get("hasVariant")
    return v[0] if isinstance(v, list) and v and isinstance(v[0], dict) else {}


# ---------------- images ----------------
def save_image(src, item_id):
    out = IMG_DIR / f"{item_id}.jpg"
    r = requests.get(src, headers={**HEADERS, "Accept": "image/*"}, timeout=25)
    r.raise_for_status()
    im = Image.open(io.BytesIO(r.content))
    im.load()
    if im.mode in ("RGBA", "LA", "P"):
        im = im.convert("RGBA")
        bg = Image.new("RGB", im.size, (255, 255, 255))
        bg.paste(im, mask=im.split()[-1])
        im = bg
    else:
        im = im.convert("RGB")
    im.thumbnail((IMG_MAX, IMG_MAX))
    im.save(out, "JPEG", quality=82, optimize=True, progressive=True)
    return f"img/{out.name}"


# ---------------- main ----------------
def why(e):
    """Short, human reason for a failure."""
    resp = getattr(e, "response", None)
    if resp is not None:
        code = resp.status_code
        return {403: "site blocked the request (403)", 404: "page not found (404)",
                429: "rate-limited, try again later (429)"}.get(code, f"HTTP {code}")
    if isinstance(e, requests.exceptions.Timeout):
        return "timed out"
    if isinstance(e, requests.exceptions.ConnectionError):
        return "couldn't connect"
    return type(e).__name__


def to_price(v):
    if v in (None, ""):
        return None
    m = re.search(r"\d+(?:\.\d+)?", str(v).replace(",", ""))
    return round(float(m.group())) if m else None


def load_rows():
    if SHEET_URL:
        r = requests.get(SHEET_URL, params={"action": "products"}, timeout=30)
        r.raise_for_status()
        rows = r.json()
        print(f"Read {len(rows)} products from the Google Sheet")
        return rows
    print("LOOP_SHEET_URL not set, reading products.csv")
    return list(csv.DictReader(CSV_PATH.open(newline="", encoding="utf-8-sig")))


def stable_id(row):
    key = (row.get("url") or row.get("name") or "").lower()
    return "p" + hashlib.sha1(key.encode()).hexdigest()[:8]


def main():
    rows = load_rows()
    IMG_DIR.mkdir(parents=True, exist_ok=True)

    items, problems, left_out = [], [], []
    for n, row in enumerate(rows, 1):
        row = {k: (v or "").strip() for k, v in row.items()}
        if not (row.get("url") or row.get("name")):
            continue
        item_id = stable_id(row)
        label = row.get("name") or row.get("url")
        meta, page_error = {}, ""

        # Rows from the "Add to Loop" button already have a name and photo: no need to visit the page.
        if row.get("url") and not (row.get("photo") and row.get("name")):
            try:
                meta = scrape(row["url"])
                time.sleep(0.5)
            except Exception as e:
                page_error = f"couldn't read the page, {why(e)}"

        name = row.get("name") or meta.get("name") or ""
        # trim retailer suffixes like " | Target" or " - Amazon.com"
        name = re.split(r"\s+[|–—]\s+|\s+-\s+(?=[A-Z][\w.]+$)", name)[0].strip()
        brand = meta.get("brand") or ""
        if name and brand and not row.get("name") and brand.lower() not in name.lower():
            name = f"{brand} {name}"
        category = row.get("category") or ""
        price = to_price(row.get("price")) or to_price(meta.get("price"))
        blurb = shorten(row.get("blurb") or meta.get("description") or "")
        photo_src = row.get("photo") or meta.get("photo")

        photo, reason = None, ""
        kept = IMG_DIR / f"{item_id}.jpg"
        if photo_src:
            try:
                photo = save_image(photo_src, item_id)
            except Exception as e:
                if kept.exists():   # keep the photo from a previous successful build
                    photo = f"img/{kept.name}"
                else:
                    reason = f"photo wouldn't download, {why(e)}"
        elif kept.exists():
            photo = f"img/{kept.name}"
        else:
            reason = page_error or "no photo on the page"

        if not name:
            problems.append(f"Row {n}: no name found")
            continue
        if not photo:
            left_out.append(f"{name}: {reason}")
            print(f"  ✗ {name} (left out: {reason})")
            continue
        if not category:
            problems.append(f"{name}: no category (type one in the Sheet)")

        items.append({"id": item_id, "name": name, "category": category or "Baby gear",
                      "price": price, "icon": icon_for(category), "blurb": blurb, "photo": photo})
        print(f"  ✓ {name}")

    tpl = TEMPLATE.read_text()
    marker = "/*__ITEMS__*/[]"
    assert marker in tpl, "template.html is missing the ITEMS marker"
    payload = json.dumps(items, ensure_ascii=False, indent=1).replace("</", "<\\/")
    page = tpl.replace(marker, payload).replace("__SHEET_URL__", SHEET_URL)
    (DIST / "index.html").write_text(page)

    used = {i["photo"].split("/")[-1] for i in items if "photo" in i}
    for old in IMG_DIR.glob("*.jpg"):      # drop photos of removed products
        if old.name not in used:
            old.unlink()

    lines = [f"{len(items)} cards in the game."]
    if left_out:
        lines += ["", f"Left out because there's no photo ({len(left_out)}). Delete the row, or click "
                  "+ Add to Loop on the product's page, or paste a photo link into its photo cell:"]
        lines += [f"- {x}" for x in left_out]
    if problems:
        lines += ["", "Other things to check:"] + [f"- {x}" for x in problems]
    report = "\n".join(lines) + "\n"
    REPORT.write_text(report)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a") as f:
            f.write("### " + report.replace("\n\nLeft out", "\n\n**Left out").replace("photo cell:", "photo cell:**", 1))
    print("\n" + report)


if __name__ == "__main__":
    sys.exit(main())
