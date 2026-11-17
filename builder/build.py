#!/usr/bin/env python3
"""
Loop deck builder (v2: category deck).

Normally run by GitHub Actions (.github/workflows/build.yml). It reads the
"Categories" tab of the Loop Google Sheet (via the Apps Script URL in the
LOOP_SHEET_URL setting) and writes index.html + img/ into the site folder.
Without LOOP_SHEET_URL it falls back to categories.csv next to this file.

One row per category: name, order, color, icon, sqft, intake_only, and three
"hero" versions (name + photo link). Anything in "hide" drops the row.
Cards with "options" (like Outgrown toys) can have "option_photos": one group of
photo links per option, groups split by |, links split by spaces. Each group
becomes a 3-photo collage on a white square. A card_photo with several links
becomes a collage too.

Hero photos are downloaded, shrunk and saved into img/, so the game never
depends on a retailer's server while friends are playing. If a download fails,
the photo from the last good build is kept; if there never was one, that tile
shows the product name on a colored square instead. Problems go to
build_report.txt and the Actions run summary.
"""
import csv, hashlib, io, json, os, re, sys
from pathlib import Path

import requests
from PIL import Image

HERE = Path(__file__).parent
CSV_PATH = HERE / "categories.csv"
TEMPLATE = HERE / "template.html"
SHEET_URL = os.environ.get("LOOP_SHEET_URL", "").strip()
DIST = Path(os.environ.get("LOOP_OUT") or HERE / "dist")
IMG_DIR = DIST / "img"
REPORT = HERE / "build_report.txt"

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/128.0 Safari/537.36")
HEADERS = {"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9", "Accept": "image/*"}
IMG_MAX = 480                        # px, longest side (tiles are small)
PALETTE = ["#FF6B4A", "#FFD23F", "#7EC8F2", "#7BC74D"]


def why(e):
    resp = getattr(e, "response", None)
    if resp is not None:
        return {403: "site blocked the request (403)", 404: "photo not found (404)",
                429: "rate-limited, try again later (429)"}.get(resp.status_code, f"HTTP {resp.status_code}")
    if isinstance(e, requests.exceptions.Timeout):
        return "timed out"
    if isinstance(e, requests.exceptions.ConnectionError):
        return "couldn't connect"
    return type(e).__name__


def fetch_image(src):
    r = requests.get(src, headers=HEADERS, timeout=25)
    r.raise_for_status()
    im = Image.open(io.BytesIO(r.content))
    im.load()
    if im.mode in ("RGBA", "LA", "P"):
        im = im.convert("RGBA")
        bg = Image.new("RGB", im.size, (255, 255, 255))
        bg.paste(im, mask=im.split()[-1])
        return bg
    return im.convert("RGB")


def write_jpg(im, item_id):
    out = IMG_DIR / f"{item_id}.jpg"
    im.thumbnail((IMG_MAX, IMG_MAX))
    im.save(out, "JPEG", quality=82, optimize=True, progressive=True)
    return f"img/{out.name}"


def save_image(src, item_id):
    return write_jpg(fetch_image(src), item_id)


def trim_white(im, tol=18):
    """Crop the near-white margin around a product shot so it fills its spot."""
    grey = im.convert("L").point(lambda v: 255 if v < 255 - tol else 0)
    box = grey.getbbox()
    return im.crop(box) if box else im


COLLAGE = 600
SPOTS = {  # where 1, 2 or 3 photos sit on the square (x, y, w, h)
    1: [(40, 40, 520, 520)],
    2: [(20, 130, 275, 340), (305, 130, 275, 340)],
    3: [(18, 22, 278, 270), (304, 22, 278, 270), (161, 306, 278, 274)],
}


def save_collage(srcs, item_id):
    """Download up to 3 photos and arrange them on one white square.
    Returns (path, list of failed links). Raises if none downloaded."""
    ims, failed = [], []
    for src in srcs[:3]:
        try:
            ims.append(trim_white(fetch_image(src)))
        except Exception as e:
            failed.append(f"{src[:60]}... ({why(e)})")
    if not ims:
        raise RuntimeError("; ".join(failed) or "no photos")
    canvas = Image.new("RGB", (COLLAGE, COLLAGE), (255, 255, 255))
    for im, (x, y, w, h) in zip(ims, SPOTS[len(ims)]):
        im = im.copy()
        im.thumbnail((w, h), Image.LANCZOS)
        canvas.paste(im, (x + (w - im.width) // 2, y + (h - im.height) // 2))
    return write_jpg(canvas, item_id), failed


def links(cell):
    return [u for u in str(cell or "").split() if u.startswith("http")]


def load_rows():
    if SHEET_URL:
        r = requests.get(SHEET_URL, params={"action": "categories"}, timeout=30)
        r.raise_for_status()
        rows = r.json()
        print(f"Read {len(rows)} categories from the Google Sheet")
        return rows
    print("LOOP_SHEET_URL not set, reading categories.csv")
    return list(csv.DictReader(CSV_PATH.open(newline="", encoding="utf-8-sig")))


def slug(text):
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "x"


def num(v, default=0):
    m = re.search(r"\d+(?:\.\d+)?", str(v or ""))
    return float(m.group()) if m else default


def main():
    rows = [{k.strip().lower(): (v or "").strip() for k, v in r.items() if k} for r in load_rows()]
    rows = [r for r in rows if r.get("category") and not r.get("hide")]
    rows.sort(key=lambda r: num(r.get("order"), 999))
    IMG_DIR.mkdir(parents=True, exist_ok=True)

    cats, problems, used = [], [], set()
    for n, row in enumerate(rows):
        name = row["category"]
        heroes = []
        for i in (1, 2, 3):
            hname, src = row.get(f"hero{i}_name", ""), row.get(f"hero{i}_photo", "")
            if not hname:
                continue
            hero = {"name": hname}
            pid = "h" + hashlib.sha1(f"{name}|{hname}".lower().encode()).hexdigest()[:8]
            kept = IMG_DIR / f"{pid}.jpg"
            if src:
                try:
                    hero["photo"] = save_image(src, pid)
                except Exception as e:
                    if kept.exists():
                        hero["photo"] = f"img/{kept.name}"
                        problems.append(f"{name} / {hname}: new photo failed ({why(e)}), kept the old one")
                    else:
                        problems.append(f"{name} / {hname}: photo failed ({why(e)}), tile shows the name instead")
            elif kept.exists():
                hero["photo"] = f"img/{kept.name}"
            else:
                problems.append(f"{name} / {hname}: no photo link, tile shows the name instead")
            if "photo" in hero:
                used.add(f"{pid}.jpg")
            heroes.append(hero)
        if not heroes and not row.get("options"):
            problems.append(f"{name}: no hero versions or options, 'Got one' goes straight to status")
        card = None
        csrc = row.get("card_photo", "")
        cid = "c" + hashlib.sha1(name.lower().encode()).hexdigest()[:8]
        ckept = IMG_DIR / f"{cid}.jpg"
        if csrc:
            try:
                if len(links(csrc)) > 1:
                    card, bad = save_collage(links(csrc), cid)
                    problems += [f"{name}: card collage photo failed, left it out: {b}" for b in bad]
                else:
                    card = save_image(csrc, cid)
            except Exception as e:
                if ckept.exists():
                    card = f"img/{ckept.name}"
                problems.append(f"{name}: card photo failed ({why(e) if not isinstance(e, RuntimeError) else e})")
        if card:
            used.add(f"{cid}.jpg")
        options = [o.strip() for o in row.get("options", "").split("|") if o.strip()]
        groups = [links(g) for g in row.get("option_photos", "").split("|")] if row.get("option_photos") else []
        option_photos = []
        for i, opt in enumerate(options):
            oid = "o" + hashlib.sha1(f"{name}|{opt}".lower().encode()).hexdigest()[:8]
            okept = IMG_DIR / f"{oid}.jpg"
            srcs = groups[i] if i < len(groups) else []
            photo = None
            if srcs:
                try:
                    photo, bad = save_collage(srcs, oid)
                    problems += [f"{name} / {opt}: one photo failed, collage has the rest: {b}" for b in bad]
                except Exception as e:
                    if okept.exists():
                        photo = f"img/{okept.name}"
                    problems.append(f"{name} / {opt}: collage failed ({e}){', kept the old one' if photo else ', tile shows the age instead'}")
            elif okept.exists():
                photo = f"img/{okept.name}"
            if photo:
                used.add(f"{oid}.jpg")
            option_photos.append(photo)
        color = row.get("color") if re.fullmatch(r"#[0-9a-fA-F]{6}", row.get("color", "")) else PALETTE[n % 4]
        cats.append({
            "id": slug(name), "name": name, "color": color,
            "icon": row.get("icon") or "ti-box", "sqft": num(row.get("sqft")),
            "intake_only": row.get("intake_only", "").lower() in ("yes", "y", "true", "1"),
            "heroes": heroes, "options": options, "option_photos": option_photos, "card": card,
        })
        print(f"  {name}: {sum('photo' in h for h in heroes)}/{len(heroes)} photos")

    tpl = TEMPLATE.read_text()
    marker = "/*__CATS__*/[]"
    assert marker in tpl, "template.html is missing the CATS marker"
    payload = json.dumps(cats, ensure_ascii=False, indent=1).replace("</", "<\\/")
    (DIST / "index.html").write_text(tpl.replace(marker, payload).replace("__SHEET_URL__", SHEET_URL))

    for old in IMG_DIR.glob("*.jpg"):      # drop photos nothing uses any more
        if old.name not in used:
            old.unlink()

    n_photos = sum("photo" in h for c in cats for h in c["heroes"])
    n_heroes = sum(len(c["heroes"]) for c in cats)
    REPORT.write_text("\n".join(problems) + "\n" if problems else "All good.\n")
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a") as f:
            f.write(f"### Built {len(cats)} category cards ({n_photos} of {n_heroes} hero photos)\n\n")
            f.write("".join(f"- {p}\n" for p in problems) or "All good.\n")
    print(f"\nBuilt {len(cats)} cards -> {DIST / 'index.html'}  ({n_photos} of {n_heroes} hero photos)")
    if problems:
        print(f"{len(problems)} things to check -> build_report.txt")
    if not cats:
        sys.exit("No categories found: check the Categories tab.")


if __name__ == "__main__":
    main()
