"""Download candidate photos (id url per line) and make a labeled contact sheet."""
import io, sys, requests
from PIL import Image, ImageDraw
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/128.0 Safari/537.36", "Accept": "image/*"}
rows = [l.split() for l in open(sys.argv[1]) if l.strip()]
T = 260; cols = 6; tiles = []
for pid, url in rows:
    try:
        r = requests.get(url, headers=UA, timeout=25); r.raise_for_status()
        im = Image.open(io.BytesIO(r.content)); im.load()
        if im.mode in ("RGBA", "LA", "P"):
            im = im.convert("RGBA"); bg = Image.new("RGB", im.size, "white"); bg.paste(im, mask=im.split()[-1]); im = bg
        im = im.convert("RGB"); note = f"{pid} {im.size[0]}x{im.size[1]}"
    except Exception as e:
        im = Image.new("RGB", (T, T), (255, 220, 220)); note = f"{pid} FAIL {type(e).__name__} {getattr(getattr(e,'response',None),'status_code','')}"
    im.thumbnail((T, T - 20)); c = Image.new("RGB", (T, T), (235, 235, 235)); c.paste(im, ((T - im.width) // 2, 0))
    ImageDraw.Draw(c).text((4, T - 16), note, fill="black"); tiles.append(c); print(note)
sheet = Image.new("RGB", (cols * T, -(-len(tiles) // cols) * T), "white")
for i, t in enumerate(tiles): sheet.paste(t, ((i % cols) * T, (i // cols) * T))
sheet.save(sys.argv[2], quality=85)
