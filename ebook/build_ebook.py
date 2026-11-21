#!/usr/bin/env python3
"""Build the Paddock Party photo book (PDF + flip-through pages).

Reads the live keepsake images in /img (numbered display order) and
writes:

  ebook/Paddock-Party-18th.pdf
  book/index.html
  book/pages/*.jpg

Re-run:

    ebook/.venv/bin/python ebook/build_ebook.py
"""
from __future__ import annotations

import math
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import qrcode
from fpdf import FPDF
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
IMG = ROOT / "img"
EBOOK = ROOT / "ebook"
FONTS = EBOOK / "fonts"
PDF_PATH = EBOOK / "Paddock-Party-18th.pdf"
PREVIEWS = EBOOK / "previews"
BOOK = ROOT / "book"
PAGES = BOOK / "pages"
QR_PATH = EBOOK / "qr-website.png"

SITE_URL = "https://robmac10.github.io/paddock-party/"

# 12 x 9 inch landscape, in points.
PAGE_W = 12 * 72
PAGE_H = 9 * 72

# Don't display a photo larger than this many pixels per inch.
MIN_DPI = 150
# The 360x480 '18 together' portrait may go a little larger so it
# reads as a print, but not so far that it softens.
TOGETHER_DPI = 120

MARGIN = 0.55 * 72
GAP = 0.32 * 72
MAT = 9.0
GOLD_MAT = 12.0
LABEL_H = 22.0

NAVY = (14, 23, 38)
SKY = (21, 34, 56)
SKY2 = (28, 46, 74)
GOLD = (212, 164, 74)
GOLD_SOFT = (232, 200, 122)
CREAM = (247, 241, 228)
PAPER = (255, 250, 241)
INK = (42, 33, 24)
MUTED = (92, 74, 50)
LEDE = (230, 216, 180)
RULE = (217, 201, 164)
SHADOW = (200, 186, 160)

STARS = ["01-18-together.jpg", "02-the-stars.jpg", "03-kate.jpg", "04-declan.jpg"]
HIGHLIGHTS = ["79-family-under-the-marquee.jpg", "80-family-under-the-marquee-alt.jpg"]


@dataclass
class Photo:
    path: Path
    name: str
    w: int
    h: int

    @property
    def portrait(self) -> bool:
        return self.h > self.w * 1.05

    @property
    def std_land(self) -> bool:
        """4:3-ish landscape, comfortable as a pair."""
        ratio = self.w / self.h
        return ratio > 1.05 and ratio < 1.5


def load_photos() -> list[Photo]:
    photos = []
    for path in sorted(IMG.glob("*.jpg")):
        if path.name == "video-poster.jpg":
            continue
        with Image.open(path) as im:
            w, h = im.size
        photos.append(Photo(path=path, name=path.name, w=w, h=h))
    return photos


def can_pair(a: Photo, b: Photo) -> bool:
    return (a.portrait and b.portrait) or (a.std_land and b.std_land)


def max_place(photo: Photo, dpi: float) -> tuple[float, float]:
    return photo.w / dpi * 72, photo.h / dpi * 72


def fit(photo: Photo, box_w: float, box_h: float, dpi: float = MIN_DPI) -> tuple[float, float]:
    max_w, max_h = max_place(photo, dpi)
    avail_w = min(box_w, max_w)
    avail_h = min(box_h, max_h)
    aspect = photo.w / photo.h
    if avail_w / avail_h > aspect:
        h = avail_h
        w = h * aspect
    else:
        w = avail_w
        h = w / aspect
    return w, h


def draw_star(pdf: FPDF, cx: float, cy: float, r: float, color=GOLD_SOFT) -> None:
    pts: list[tuple[float, float]] = []
    for i in range(8):
        ang = math.radians(-90 + i * 45)
        rad = r if i % 2 == 0 else r * 0.38
        pts.append((cx + rad * math.cos(ang), cy + rad * math.sin(ang)))
    pdf.set_fill_color(*color)
    pdf.polygon(pts, style="F")


def paint_gradient(pdf: FPDF) -> None:
    steps = 80
    for i in range(steps):
        t = i / (steps - 1)
        if t < 0.55:
            u = t / 0.55
            r = NAVY[0] + (SKY[0] - NAVY[0]) * u
            g = NAVY[1] + (SKY[1] - NAVY[1]) * u
            b = NAVY[2] + (SKY[2] - NAVY[2]) * u
        else:
            u = (t - 0.55) / 0.45
            r = SKY[0] + (SKY2[0] - SKY[0]) * u
            g = SKY[1] + (SKY2[1] - SKY[1]) * u
            b = SKY[2] + (SKY2[2] - SKY[2]) * u
        pdf.set_fill_color(int(r), int(g), int(b))
        y = PAGE_H * i / steps
        pdf.rect(0, y, PAGE_W, PAGE_H / steps + 0.6, style="F")


def draw_moon(pdf: FPDF, cx: float, cy: float, r: float) -> None:
    pdf.set_fill_color(255, 249, 223)
    pdf.ellipse(cx - r, cy - r, r * 2, r * 2, style="F")
    # Soft inner glow as a slightly smaller warm disc.
    pdf.set_fill_color(232, 217, 160)
    inner = r * 0.62
    pdf.ellipse(cx - inner + r * 0.12, cy - inner + r * 0.1, inner * 2, inner * 2, style="F")
    pdf.set_fill_color(255, 249, 223)
    core = r * 0.42
    pdf.ellipse(cx - core - r * 0.08, cy - core - r * 0.06, core * 2, core * 2, style="F")


def draw_festoon(pdf: FPDF, y: float) -> None:
    left, right = PAGE_W * 0.14, PAGE_W * 0.86
    # Shallow gold cord.
    pdf.set_draw_color(196, 163, 90)
    pdf.set_line_width(1.15)
    steps = 40
    pts = []
    for i in range(steps + 1):
        t = i / steps
        x = left + (right - left) * t
        dip = 10 * math.sin(math.pi * t)
        pts.append((x, y + dip))
    for a, b in zip(pts, pts[1:]):
        pdf.line(a[0], a[1], b[0], b[1])

    positions = [0.06, 0.15, 0.24, 0.33, 0.42, 0.51, 0.60, 0.69, 0.78, 0.87, 0.95]
    # Map 6%–95% of the festoon span, matching the live header.
    for i, p in enumerate(positions):
        x = left + (right - left) * ((p - 0.06) / (0.95 - 0.06))
        t = (p - 0.06) / (0.95 - 0.06)
        dip = 10 * math.sin(math.pi * t)
        if i % 2:
            dip += 6
        elif i % 3 == 0:
            dip -= 2
        bx, by = x, y + dip
        # Teardrop bulb.
        pdf.set_fill_color(240, 193, 75)
        pdf.ellipse(bx - 5.2, by - 2, 10.4, 15.2, style="F")
        pdf.set_fill_color(255, 248, 216)
        pdf.ellipse(bx - 2.6, by + 0.4, 5.2, 6.2, style="F")


def cream_page(pdf: FPDF) -> None:
    pdf.set_fill_color(*CREAM)
    pdf.rect(0, 0, PAGE_W, PAGE_H, style="F")


def frame_rect(pdf: FPDF, x: float, y: float, w: float, h: float, gold: bool = False) -> None:
    pad = GOLD_MAT if gold else MAT
    fx, fy, fw, fh = x - pad, y - pad, w + 2 * pad, h + 2 * pad
    # Quiet shadow.
    pdf.set_fill_color(*SHADOW)
    pdf.rect(fx + 3, fy + 4, fw, fh, style="F")
    pdf.set_fill_color(*PAPER)
    pdf.rect(fx, fy, fw, fh, style="F")
    if gold:
        pdf.set_draw_color(*GOLD)
        pdf.set_line_width(1.4)
        pdf.rect(fx, fy, fw, fh, style="D")
        pdf.set_draw_color(*GOLD_SOFT)
        pdf.set_line_width(0.6)
        inset = 2.6
        pdf.rect(fx + inset, fy + inset, fw - 2 * inset, fh - 2 * inset, style="D")


def place_image(pdf: FPDF, photo: Photo, x: float, y: float, w: float, h: float) -> None:
    pdf.image(str(photo.path), x=x, y=y, w=w, h=h)


def caption_label(pdf: FPDF, text: str, cx: float, y: float) -> None:
    pdf.set_font("Fraunces", "I", 11)
    pdf.set_text_color(*MUTED)
    pdf.set_xy(cx - 140, y)
    pdf.cell(280, LABEL_H, text, align="C")


def place_one(
    pdf: FPDF,
    photo: Photo,
    *,
    gold: bool = False,
    label: str | None = None,
    dpi: float = MIN_DPI,
    heading: str | None = None,
) -> None:
    pdf.add_page()
    cream_page(pdf)
    top = MARGIN
    if heading:
        draw_heading(pdf, heading, y=36)
        top = 70
    reserve = (LABEL_H + 4) if label else 0
    box_w = PAGE_W - 2 * MARGIN
    box_h = PAGE_H - top - MARGIN - reserve
    # Leave room for the mat.
    pad = GOLD_MAT if gold else MAT
    w, h = fit(photo, box_w - 2 * pad, box_h - 2 * pad, dpi)
    x = (PAGE_W - w) / 2
    y = top + (box_h - h - reserve) / 2
    frame_rect(pdf, x, y, w, h, gold=gold)
    place_image(pdf, photo, x, y, w, h)
    if label:
        caption_label(pdf, label, PAGE_W / 2, y + h + pad + 2)


def place_pair(
    pdf: FPDF,
    left: Photo,
    right: Photo,
    *,
    labels: tuple[str, str] | None = None,
    gold: bool = False,
    heading: str | None = None,
    dpi_left: float = MIN_DPI,
    dpi_right: float = MIN_DPI,
) -> None:
    pdf.add_page()
    cream_page(pdf)
    top = MARGIN
    if heading:
        draw_heading(pdf, heading, y=36)
        top = 70
    reserve = (LABEL_H + 6) if labels else 0
    pad = GOLD_MAT if gold else MAT
    box_w = PAGE_W - 2 * MARGIN
    box_h = PAGE_H - top - MARGIN - reserve
    cell_w = (box_w - GAP) / 2
    inner_w = cell_w - 2 * pad
    inner_h = box_h - 2 * pad

    w1, h1 = fit(left, inner_w, inner_h, dpi_left)
    w2, h2 = fit(right, inner_w, inner_h, dpi_right)
    # Shared height so a pair sits on one baseline.
    h = min(h1, h2)
    w1 = h * left.w / left.h
    w2 = h * right.w / right.h
    # If equalising height overflowed a cell, scale both down together.
    scale = min(1.0, inner_w / w1, inner_w / w2)
    w1, w2, h = w1 * scale, w2 * scale, h * scale

    group_w = w1 + w2 + GAP
    x0 = (PAGE_W - group_w) / 2
    y = top + (box_h - h) / 2
    x1 = x0
    x2 = x0 + w1 + GAP
    frame_rect(pdf, x1, y, w1, h, gold=gold)
    place_image(pdf, left, x1, y, w1, h)
    frame_rect(pdf, x2, y, w2, h, gold=gold)
    place_image(pdf, right, x2, y, w2, h)
    if labels:
        caption_label(pdf, labels[0], x1 + w1 / 2, y + h + pad + 2)
        caption_label(pdf, labels[1], x2 + w2 / 2, y + h + pad + 2)


def draw_heading(pdf: FPDF, text: str, y: float) -> None:
    pdf.set_font("Fraunces", "I", 20)
    pdf.set_text_color(*SKY)
    tw = pdf.get_string_width(text)
    cx = PAGE_W / 2
    pdf.set_xy(cx - tw / 2, y)
    pdf.cell(tw, 20, text, align="C")
    draw_star(pdf, cx - tw / 2 - 18, y + 11, 5.5, GOLD)
    draw_star(pdf, cx + tw / 2 + 18, y + 11, 5.5, GOLD)


def add_cover(pdf: FPDF) -> None:
    pdf.add_page()
    paint_gradient(pdf)
    draw_moon(pdf, PAGE_W * 0.88, 58, 22)
    draw_festoon(pdf, 46)

    # A keepsake
    pdf.set_font("SourceSans", "B", 11)
    pdf.set_text_color(*GOLD_SOFT)
    pdf.set_char_spacing(3.4)
    pdf.set_xy(0, 150)
    pdf.cell(PAGE_W, 16, "A KEEPSAKE", align="C")
    pdf.set_char_spacing(0)

    # Declan & Kate's
    pdf.set_font("Fraunces", "", 54)
    pdf.set_text_color(248, 241, 226)
    pdf.set_xy(0, 200)
    pdf.cell(PAGE_W, 62, "Declan & Kate's", align="C")

    # 18th
    pdf.set_font("Fraunces", "I", 42)
    pdf.set_text_color(*GOLD_SOFT)
    pdf.set_xy(0, 268)
    pdf.cell(PAGE_W, 50, "18th", align="C")

    # Paddock Party
    pdf.set_font("Fraunces", "I", 28)
    pdf.set_text_color(*GOLD)
    pdf.set_xy(0, 340)
    pdf.cell(PAGE_W, 36, "Paddock Party", align="C")

    # Lede
    pdf.set_font("SourceSans", "", 15)
    pdf.set_text_color(*LEDE)
    pdf.set_xy(0, 400)
    pdf.cell(PAGE_W, 22, "A night in the paddock, kept here.", align="C")

    # ✦ ✦ ✦
    mid = PAGE_W / 2
    star_y = 452
    for dx in (-28, 0, 28):
        draw_star(pdf, mid + dx, star_y, 6.2, GOLD_SOFT)


def add_video_page(pdf: FPDF) -> None:
    pdf.add_page()
    paint_gradient(pdf)
    draw_moon(pdf, PAGE_W * 0.88, 58, 18)
    draw_festoon(pdf, 46)

    pdf.set_font("Fraunces", "I", 28)
    pdf.set_text_color(*GOLD_SOFT)
    pdf.set_xy(0, 160)
    pdf.cell(PAGE_W, 36, "The video is on the website", align="C")

    # QR on a cream square with a gold edge.
    qr_size = 180
    qx = (PAGE_W - qr_size) / 2
    qy = 230
    pad = 16
    pdf.set_fill_color(*SHADOW)
    pdf.rect(qx - pad + 3, qy - pad + 4, qr_size + 2 * pad, qr_size + 2 * pad, style="F")
    pdf.set_fill_color(*PAPER)
    pdf.rect(qx - pad, qy - pad, qr_size + 2 * pad, qr_size + 2 * pad, style="F")
    pdf.set_draw_color(*GOLD)
    pdf.set_line_width(1.3)
    pdf.rect(qx - pad, qy - pad, qr_size + 2 * pad, qr_size + 2 * pad, style="D")
    pdf.image(str(QR_PATH), x=qx, y=qy, w=qr_size, h=qr_size)

    pdf.set_font("SourceSans", "", 11)
    pdf.set_text_color(*LEDE)
    pdf.set_xy(0, qy + qr_size + pad + 18)
    pdf.cell(PAGE_W, 16, SITE_URL, align="C")

    mid = PAGE_W / 2
    for dx in (-28, 0, 28):
        draw_star(pdf, mid + dx, 600, 5.5, GOLD_SOFT)


def make_qr() -> None:
    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=12,
        border=2,
    )
    qr.add_data(SITE_URL)
    qr.make(fit=True)
    img = qr.make_image(fill_color="#0e1726", back_color="#fffaf1").convert("RGB")
    img.save(QR_PATH, "PNG")


def build_pdf(photos: list[Photo]) -> int:
    by_name = {p.name: p for p in photos}
    missing = [n for n in STARS + HIGHLIGHTS if n not in by_name]
    if missing:
        raise SystemExit(f"Missing expected photographs: {missing}")

    make_qr()

    pdf = FPDF(unit="pt", format=(PAGE_W, PAGE_H))
    pdf.set_auto_page_break(auto=False, margin=0)
    pdf.set_title("Declan & Kate's 18th — Paddock Party")
    pdf.set_creator("Paddock Party photo book")
    pdf.set_lang("en-AU")
    pdf.add_font("Fraunces", "", str(FONTS / "Fraunces-500.ttf"))
    pdf.add_font("Fraunces", "I", str(FONTS / "Fraunces-Italic-500.ttf"))
    pdf.add_font("SourceSans", "", str(FONTS / "SourceSans3-400.ttf"))
    pdf.add_font("SourceSans", "B", str(FONTS / "SourceSans3-600.ttf"))

    add_cover(pdf)

    # Stars section.
    together = by_name["01-18-together.jpg"]
    place_one(pdf, together, gold=True, label="18 together", dpi=TOGETHER_DPI)
    place_one(pdf, by_name["02-the-stars.jpg"])
    place_pair(
        pdf,
        by_name["03-kate.jpg"],
        by_name["04-declan.jpg"],
        labels=("Kate", "Declan"),
    )

    body = [p for p in photos if p.name not in STARS and p.name not in HIGHLIGHTS]
    i = 0
    while i < len(body):
        cur = body[i]
        nxt = body[i + 1] if i + 1 < len(body) else None
        if nxt is not None and can_pair(cur, nxt):
            place_pair(pdf, cur, nxt)
            i += 2
        else:
            place_one(pdf, cur)
            i += 1

    place_pair(
        pdf,
        by_name["79-family-under-the-marquee.jpg"],
        by_name["80-family-under-the-marquee-alt.jpg"],
        gold=True,
        heading="Highlights",
    )
    add_video_page(pdf)

    PDF_PATH.parent.mkdir(parents=True, exist_ok=True)
    pdf.output(str(PDF_PATH))
    return pdf.pages_count if hasattr(pdf, "pages_count") else len(pdf.pages)


def render_pages(page_count: int) -> None:
    """Rasterise PDF pages for the flip-through book and for previews."""
    if PAGES.exists():
        shutil.rmtree(PAGES)
    PAGES.mkdir(parents=True)
    PREVIEWS.mkdir(parents=True, exist_ok=True)

    # Flip-through images: 140 dpi JPEGs, big enough on a phone and a laptop.
    subprocess.run(
        [
            "pdftoppm",
            "-jpeg",
            "-jpegopt",
            "quality=86",
            "-r",
            "140",
            str(PDF_PATH),
            str(PAGES / "page"),
        ],
        check=True,
    )
    # pdftoppm names files page-1.jpg or page-01.jpg depending on count.
    produced = sorted(PAGES.glob("page*.jpg"))
    if len(produced) != page_count:
        # Still rename whatever we got.
        pass
    width = max(3, len(str(len(produced))))
    for i, src in enumerate(produced, start=1):
        dest = PAGES / f"{i:0{width}d}.jpg"
        if dest.exists():
            dest.unlink()
        src.rename(dest)

    # Higher-res previews of the first few characteristic pages.
    subprocess.run(
        [
            "pdftoppm",
            "-png",
            "-r",
            "120",
            "-f",
            "1",
            "-l",
            "5",
            str(PDF_PATH),
            str(PREVIEWS / "pdf-page"),
        ],
        check=True,
    )
    # Also the highlights and closing pages (last two).
    subprocess.run(
        [
            "pdftoppm",
            "-png",
            "-r",
            "120",
            "-f",
            str(max(1, page_count - 1)),
            "-l",
            str(page_count),
            str(PDF_PATH),
            str(PREVIEWS / "pdf-page"),
        ],
        check=True,
    )


def write_flipbook(page_count: int) -> None:
    pages = sorted(p.name for p in PAGES.glob("*.jpg") if p.stem.isdigit())
    if len(pages) != page_count:
        raise SystemExit(f"Expected {page_count} flipbook pages, found {len(pages)}")
    # JSON list of page filenames for the script.
    page_js = ", ".join(f'"{name}"' for name in pages)
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="robots" content="noindex, nofollow">
  <title>Declan &amp; Kate's 18th — Paddock Party</title>
  <style>
    @font-face {{
      font-family: 'Fraunces';
      font-style: italic;
      font-weight: 500;
      font-display: swap;
      src: url('../fonts/fraunces-italic-500-latin.woff2') format('woff2');
    }}
    @font-face {{
      font-family: 'Source Sans 3';
      font-style: normal;
      font-weight: 400;
      font-display: swap;
      src: url('../fonts/sourcesans3-normal-400-latin.woff2') format('woff2');
    }}
    :root {{
      --navy: #0e1726;
      --sky: #152238;
      --gold: #d4a44a;
      --gold-soft: #e8c87a;
      --cream: #f7f1e4;
      --muted: #c9b894;
    }}
    * {{ box-sizing: border-box; }}
    html, body {{
      margin: 0;
      min-height: 100%;
      background: var(--navy);
      color: var(--cream);
      font-family: "Source Sans 3", "Segoe UI", "Helvetica Neue", sans-serif;
    }}
    body {{
      min-height: 100dvh;
      display: flex;
      flex-direction: column;
    }}
    header {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 0.75rem;
      padding: 0.7rem 1rem;
      background: linear-gradient(180deg, #0c121c, var(--sky));
      border-bottom: 1px solid rgba(232, 200, 122, 0.22);
    }}
    header a {{
      color: var(--gold-soft);
      text-decoration: none;
      font-size: 0.88rem;
      letter-spacing: 0.04em;
      white-space: nowrap;
    }}
    header a:hover, header a:focus-visible {{
      color: #fff;
      text-decoration: underline;
      text-underline-offset: 3px;
    }}
    header .title {{
      font-family: Fraunces, Georgia, "Palatino Linotype", Palatino, "Times New Roman", serif;
      font-style: italic;
      font-weight: 500;
      font-size: 0.98rem;
      color: var(--cream);
      text-align: center;
      flex: 1 1 auto;
      min-width: 0;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }}
    .stage {{
      flex: 1 1 auto;
      display: flex;
      align-items: center;
      justify-content: center;
      padding: 0.6rem 0.4rem 0.2rem;
      position: relative;
      min-height: 0;
    }}
    .page-wrap {{
      width: min(100%, 1200px);
      height: 100%;
      display: flex;
      align-items: center;
      justify-content: center;
      touch-action: pan-y;
    }}
    .page-wrap img {{
      display: block;
      width: auto;
      height: auto;
      max-width: 100%;
      max-height: calc(100dvh - 7.2rem);
      background: #1c2e4a;
      box-shadow: 0 10px 28px rgba(0, 0, 0, 0.35);
      user-select: none;
      -webkit-user-drag: none;
    }}
    .nav {{
      display: flex;
      align-items: center;
      justify-content: center;
      gap: 1.1rem;
      padding: 0.55rem 1rem 1.15rem;
    }}
    .nav button {{
      appearance: none;
      border: 1px solid rgba(232, 200, 122, 0.35);
      background: rgba(255, 255, 255, 0.06);
      color: var(--cream);
      width: 46px;
      height: 46px;
      border-radius: 50%;
      font-size: 1.55rem;
      line-height: 1;
      cursor: pointer;
    }}
    .nav button:hover, .nav button:focus-visible {{
      border-color: var(--gold);
      background: rgba(212, 164, 74, 0.22);
      outline: none;
    }}
    .nav button:disabled {{
      opacity: 0.3;
      cursor: default;
    }}
    .counter {{
      min-width: 5.5rem;
      text-align: center;
      color: var(--muted);
      font-variant-numeric: tabular-nums;
      letter-spacing: 0.06em;
      font-size: 0.9rem;
    }}
    @media (prefers-reduced-motion: reduce) {{
      .page-wrap img {{ transition: none; }}
    }}
  </style>
</head>
<body>
  <header>
    <a href="../">Photographs</a>
    <span class="title">Declan &amp; Kate's 18th</span>
    <a href="../ebook/Paddock-Party-18th.pdf" download>Download PDF</a>
  </header>
  <div class="stage">
    <div class="page-wrap">
      <img id="page" alt="Photo book page 1" width="1200" height="900">
    </div>
  </div>
  <div class="nav">
    <button type="button" id="prev" aria-label="Previous page">&#8249;</button>
    <div class="counter" id="counter">1 / {page_count}</div>
    <button type="button" id="next" aria-label="Next page">&#8250;</button>
  </div>
  <script>
  (function () {{
    const PAGES = [{page_js}];
    const img = document.getElementById("page");
    const prev = document.getElementById("prev");
    const next = document.getElementById("next");
    const counter = document.getElementById("counter");
    let i = 0;
    let startX = null;

    function preload(n) {{
      if (n < 0 || n >= PAGES.length) return;
      const el = new Image();
      el.src = "pages/" + PAGES[n];
    }}
    function show(n) {{
      i = Math.max(0, Math.min(PAGES.length - 1, n));
      img.src = "pages/" + PAGES[i];
      img.alt = "Photo book page " + (i + 1);
      counter.textContent = (i + 1) + " / " + PAGES.length;
      prev.disabled = i === 0;
      next.disabled = i === PAGES.length - 1;
      preload(i + 1);
      preload(i - 1);
    }}
    prev.addEventListener("click", function () {{ show(i - 1); }});
    next.addEventListener("click", function () {{ show(i + 1); }});
    document.addEventListener("keydown", function (e) {{
      if (e.key === "ArrowLeft") show(i - 1);
      if (e.key === "ArrowRight") show(i + 1);
      if (e.key === "Home") show(0);
      if (e.key === "End") show(PAGES.length - 1);
    }});
    const wrap = img.parentElement;
    wrap.addEventListener("touchstart", function (e) {{
      if (e.changedTouches[0]) startX = e.changedTouches[0].clientX;
    }}, {{ passive: true }});
    wrap.addEventListener("touchend", function (e) {{
      if (startX == null || !e.changedTouches[0]) return;
      const dx = e.changedTouches[0].clientX - startX;
      startX = null;
      if (dx > 50) show(i - 1);
      if (dx < -50) show(i + 1);
    }}, {{ passive: true }});
    show(0);
  }})();
  </script>
</body>
</html>
"""
    (BOOK / "index.html").write_text(html, encoding="utf-8")
    # A robots file under /book/ is unnecessary; the site-wide robots.txt
    # already Disallows /, and the page itself is noindex.


def main() -> None:
    photos = load_photos()
    if len(photos) != 80:
        print(f"Warning: expected 80 photographs, found {len(photos)}", file=sys.stderr)
    page_count = build_pdf(photos)
    # fpdf2 2.9: pages_count includes the pages just written.
    if not isinstance(page_count, int) or page_count < 2:
        # Fallback: recount after writing.
        import subprocess as sp
        out = sp.check_output(["pdfinfo", str(PDF_PATH)], text=True)
        for line in out.splitlines():
            if line.startswith("Pages:"):
                page_count = int(line.split()[1])
    print(f"Wrote {PDF_PATH} ({page_count} pages, {PDF_PATH.stat().st_size} bytes)")
    render_pages(page_count)
    # Recount from rendered pages if needed.
    rendered = list(PAGES.glob("*.jpg"))
    write_flipbook(len(rendered))
    print(f"Flip-through: {BOOK / 'index.html'} ({len(rendered)} pages)")
    print(f"Previews: {PREVIEWS}")
    print(f"PDF size: {PDF_PATH.stat().st_size / (1024 * 1024):.1f} MB")


if __name__ == "__main__":
    main()
