"""BAVA subscription edit: anchored screens, selective focus and comparisons.

This is an offline edit. Actual UI pixels and already-verified financial facts
are used; no banking action is repeated. There is no camera motion or narration.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / "source"
REV = ROOT / "revisions/v3"
REV.mkdir(parents=True, exist_ok=True)
spec = importlib.util.spec_from_file_location("bava_opening", ROOT.parent / "opening/build_opening.py")
brand = importlib.util.module_from_spec(spec)
spec.loader.exec_module(brand)
W, H, FPS, DURATION = 1920, 1080, 30, 40
FFMPEG = brand.FFMPEG
OUTPUT_NAME = "BAVA-subscriptions-40s-stable-v3.mp4"
COMBINED_NAME = "BAVA-preview-95s-stable-v3.mp4"
PANEL = (14, 31, 44)
LINE = (45, 73, 87)
AMBER = (236, 189, 90)
VIEWPORT = (260, 150, 1440, 805)
FACTS = json.loads((ROOT / "evidence/verification.json").read_text())
assert all(FACTS["checks"].values())


def load(name):
    return Image.open(SOURCE / (name + ".png")).convert("RGB")


IMAGES = {name: load(name) for name in [
    "01-query", "02-read-consent", "05-managed-and-detected",
    "06-cost-and-renewal", "07-cancel-request", "08-review-full",
    "08-review", "09-approved", "11-cancel-receipt", "13-cancelled-contract",
]}


def smooth(value):
    value = max(0, min(1, value))
    return value * value * (3 - 2 * value)


def rounded_paste(base, patch, xy, radius=12, stroke=None):
    mask = Image.new("L", patch.size)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, patch.width - 1, patch.height - 1), radius=radius, fill=255)
    base.paste(patch, xy, mask)
    if stroke:
        x, y = xy
        ImageDraw.Draw(base).rounded_rectangle((x, y, x + patch.width - 1, y + patch.height - 1), radius=radius, outline=stroke, width=2)


def native_patch(name, crop, width):
    image = IMAGES[name]
    x1, y1, x2, y2 = crop
    assert 0 <= x1 < x2 <= image.width and 0 <= y1 < y2 <= image.height
    patch = image.crop(crop)
    return patch.resize((width, round(width * patch.height / patch.width)), Image.Resampling.LANCZOS)


def map_box(box):
    sx, sy = 1620 / (VIEWPORT[2] - VIEWPORT[0]), 900 / (VIEWPORT[3] - VIEWPORT[1])
    return tuple(round(v) for v in (
        150 + (box[0] - VIEWPORT[0]) * sx,
        112 + (box[1] - VIEWPORT[1]) * sy,
        150 + (box[2] - VIEWPORT[0]) * sx,
        112 + (box[3] - VIEWPORT[1]) * sy,
    ))


def viewport(name):
    # All conversation shots use the same fixed coordinates, without ImageOps
    # fitting offsets, zoom interpolation, scrolling or per-frame resampling.
    image = IMAGES[name].crop(VIEWPORT).resize((1620, 900), Image.Resampling.LANCZOS)
    result = brand.SHELL.copy()
    rounded_paste(result, image, (150, 112), 18, LINE)
    return result


def spotlight(image, boxes, dim=.22, outline=True):
    # The page stays still. Only a fixed opacity mask is added outside the focus.
    result = Image.blend(image, brand.SHELL, dim)
    mask = Image.new("L", (W, H))
    draw = ImageDraw.Draw(mask)
    for box in boxes:
        draw.rounded_rectangle(box, radius=10, fill=255)
    result.paste(image, (0, 0), mask)
    # Keep brand and environment labels at their normal brightness.
    result.paste(brand.SHELL.crop((0, 0, W, 100)), (0, 0))
    result.paste(brand.SHELL.crop((0, 1020, W, H)), (0, 1020))
    if outline:
        draw = ImageDraw.Draw(result)
        for box in boxes:
            draw.rounded_rectangle(box, radius=10, outline=brand.MINT, width=3)
    return result


@lru_cache(maxsize=20)
def conversation(which):
    if which == "query":
        return spotlight(viewport("01-query"), [map_box((272, 738, 1428, 799))], dim=.13)
    if which == "consent":
        return spotlight(viewport("02-read-consent"), [map_box((465, 239, 1266, 353))], dim=.22)
    if which == "contracts":
        im = viewport("05-managed-and-detected")
        # One calm row underline, rather than a box around the entire table.
        draw = ImageDraw.Draw(im)
        x1, y1, x2, y2 = map_box((473, 537, 1257, 573))
        draw.line((x1, y2, x2, y2), fill=brand.MINT, width=3)
        return im
    if which == "cost":
        im = viewport("06-cost-and-renewal")
        draw = ImageDraw.Draw(im)
        x1, y1, x2, y2 = map_box((471, 386, 1258, 711))
        draw.line((x1 - 10, y1, x1 - 10, y2), fill=brand.MINT, width=4)
        return im
    if which == "boundary":
        return spotlight(viewport("06-cost-and-renewal"), [map_box((466, 211, 1265, 372))], dim=.18)
    if which == "cancel":
        return spotlight(viewport("07-cancel-request"), [map_box((272, 738, 1428, 799))], dim=.13)
    raise ValueError(which)


def review_card():
    # Two overlapping screenshots show the same pending-review card, shifted by
    # 129.5 source pixels due to scrolling. Join within a blank timeline gutter
    # to reveal the full card once, instead of scrolling between its two halves.
    card = Image.new("RGB", (788, 650))
    top = IMAGES["08-review-full"].crop((472, 100, 1260, 450))
    bottom = IMAGES["08-review"].crop((472, 321, 1260, 621))
    card.paste(top, (0, 0)); card.paste(bottom, (0, 350))
    return card.resize((1064, 878), Image.Resampling.LANCZOS)


@lru_cache(maxsize=3)
def review(focus):
    im = brand.SHELL.copy()
    x, y = 428, 123
    card = review_card()
    rounded_paste(im, card, (x, y), 15, LINE)
    draw = ImageDraw.Draw(im)
    if focus == "risk":
        # Same static composition in both review beats.
        draw.rounded_rectangle((x + 14, y + 87, x + 1048, y + 201), radius=10, outline=AMBER, width=3)
    else:
        draw.rounded_rectangle((x + 14, y + 646, x + 1048, y + 866), radius=10, outline=brand.MINT, width=3)
    return im


def arrow(draw, a, b, color=brand.MINT, width=3, head=12):
    draw.line((a, b), fill=color, width=width)
    if b[0] == a[0]:
        draw.line(((b[0] - head, b[1] - head), b, (b[0] + head, b[1] - head)), fill=color, width=width)
    else:
        draw.line(((b[0] - head, b[1] - head), b, (b[0] - head, b[1] + head)), fill=color, width=width)


@lru_cache(maxsize=2)
def confirmation_and_result(success):
    im = brand.SHELL.copy()
    d = ImageDraw.Draw(im)
    left = (165, 150, 890, 970)
    right = (1030, 150, 1755, 970)
    d.rounded_rectangle(left, radius=20, fill=PANEL, outline=(105, 91, 57), width=2)
    d.rounded_rectangle(right, radius=20, fill=PANEL, outline=LINE, width=2)
    arrow(d, (917, 558), (1004, 558))
    # Three real UI excerpts with visible navy separation: consent status,
    # bound subscription details, then the native warning and commit button.
    for crop, y in [((497, 280, 851, 315), 238),
                    ((485, 365, 910, 478), 392),
                    ((485, 488, 915, 566), 660)]:
        rounded_paste(im, native_patch("09-approved", crop, 655), (200, y), 10)
    if not success:
        # A neutral editorial placeholder has no financial text or status claim.
        for cx in (1336, 1392, 1448):
            d.ellipse((cx - 5, 552, cx + 5, 562), fill=brand.SLATE)
        return im
    for crop, y in [((485, 183, 1040, 242), 238),
                    ((499, 448, 1000, 550), 392),
                    ((485, 558, 1120, 611), 660)]:
        rounded_paste(im, native_patch("11-cancel-receipt", crop, 655), (1065, y), 10)
    d.rounded_rectangle(right, radius=20, outline=brand.MINT, width=2)
    # A fixed underline directs attention to the real success/consumed row.
    d.line((1085, 529, 1698, 529), fill=brand.MINT, width=3)
    return im


@lru_cache(maxsize=1)
def result_comparison():
    # Clearly editorial chart on the navy brand canvas, alongside an actual
    # contract screenshot. Numbers come directly from the verified snapshots.
    im = brand.SHELL.copy()
    d = ImageDraw.Draw(im)
    before = float(FACTS["monthly_cost_before"])
    after = float(FACTS["monthly_cost_after"])
    assert before == 258 and after == 230
    d.rounded_rectangle((165, 165, 920, 950), radius=22, fill=PANEL, outline=LINE, width=2)
    d.text((215, 226), "月度成本", font=brand.font(35, chinese=True), fill=brand.WHITE)
    x, maximum = 215, 580
    for y, label, value, color in [(380, "取消前", before, brand.SLATE), (630, "取消后", after, brand.MINT)]:
        d.text((x, y - 66), label, font=brand.font(24, chinese=True), fill=color)
        d.text((x, y - 20), f"¥{value:.0f}", font=brand.font(58, 7), fill=brand.WHITE)
        bar_y = y + 70
        d.rounded_rectangle((x, bar_y, x + maximum, bar_y + 20), radius=10, fill=(28, 51, 65))
        d.rounded_rectangle((x, bar_y, x + round(maximum * value / before), bar_y + 20), radius=10, fill=color)
    # Exact same cancelled contract as the earlier review and execution receipt.
    header = native_patch("11-cancel-receipt", (485, 183, 1040, 242), 720)
    rounded_paste(im, header, (1005, 258), 12)
    card = native_patch("13-cancelled-contract", (189, 483, 714, 757), 720)
    rounded_paste(im, card, (1005, 420), 14, brand.MINT)
    return im


BEATS = [
    (0, 2.5, "query"),
    (2.5, 7, "consent"),
    (7, 11.5, "contracts"),
    (11.5, 14, "cost"),
    (14, 17.5, "boundary"),
    (17.5, 20, "cancel"),
    (20, 23.5, "risk"),
    (23.5, 27, "details"),
    (27, 30.5, "approved"),
    (30.5, 35, "success"),
    (35, 40, "comparison"),
]


def content(t):
    key = next(key for start, end, key in BEATS if start <= t < end)
    if key in {"risk", "details"}:
        return review(key)
    if key in {"approved", "success"}:
        return confirmation_and_result(key == "success")
    if key == "comparison":
        return result_comparison()
    return conversation(key)


# Crossfades affect opacity only. No crop or camera position changes across any
# frame. The marker change at 23.5s and success reveal at 30.5s keep their layout.
DISSOLVES = [2.5, 7, 11.5, 14, 17.5, 20, 23.5, 27, 30.5, 35]


def frame(t):
    for cut in DISSOLVES:
        if cut - .2 <= t < cut + .2:
            return Image.blend(content(cut - .201), content(cut + .201), smooth((t - cut + .2) / .4))
    return content(t)


SAMPLES = [1.2, 4.5, 9, 12.5, 15.5, 18.5, 21.5, 25, 28.5, 33, 36.5, 39]


def preview():
    sheet = Image.new("RGB", (1920, 1020), (7, 16, 29))
    d = ImageDraw.Draw(sheet)
    for i, t in enumerate(SAMPLES):
        im = frame(t)
        im.save(REV / f"preview-{t:g}.jpg", quality=95)
        x, y = i % 4 * 480, i // 4 * 340
        sheet.paste(im.resize((480, 270), Image.Resampling.LANCZOS), (x, y))
        absolute = t + 55
        d.text((x + 20, y + 286), f"{int(absolute // 60):02d}:{absolute % 60:05.2f}", font=brand.font(22, 2), fill=brand.SLATE)
    sheet.save(ROOT / "BAVA-subscriptions-stable-v3-storyboard.jpg", quality=95)
    frame(33).save(ROOT / "BAVA-subscriptions-stable-v3-cover.jpg", quality=95)


def main():
    preview()
    output = ROOT / OUTPUT_NAME
    cmd = [FFMPEG, "-hide_banner", "-loglevel", "warning", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "pipe:0", "-an", "-c:v", "libx264", "-preset", "medium", "-crf", "17", "-pix_fmt", "yuv420p", "-movflags", "+faststart", "-metadata", "title=BAVA | Subscription management | Stable composition v3", str(output)]
    with (REV / "render.log").open("w") as log:
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=log)
        for i in range(FPS * DURATION):
            proc.stdin.write(frame(i / FPS).tobytes())
            if i % (FPS * 5) == 0:
                print(f"Rendered {i // FPS:02d}/{DURATION}s", flush=True)
        proc.stdin.close()
        if proc.wait() != 0:
            raise RuntimeError((REV / "render.log").read_text())
    previous = ROOT.parent / "bills/BAVA-opening-and-bills-55s-silent.mp4"
    concat = REV / "concat.txt"
    concat.write_text(f"file '{previous}'\nfile '{output}'\n")
    combined = ROOT / COMBINED_NAME
    subprocess.run([FFMPEG, "-hide_banner", "-loglevel", "warning", "-y", "-f", "concat", "-safe", "0", "-i", str(concat), "-c", "copy", "-an", "-movflags", "+faststart", str(combined)], check=True)
    manifest = {
        "revision": 3, "duration_seconds": 40, "global_start_seconds": 55,
        "output": OUTPUT_NAME, "combined_preview": COMBINED_NAME,
        "width": W, "height": H, "fps": FPS,
        "audio": False, "burned_in_narration_subtitles": False,
        "camera_motion": False, "scrolling": False,
        "ui_framing_changes_within_conversation": False,
        "emphasis_methods": ["fixed spotlight", "single-row underline", "static outline", "side-by-side confirmation and receipt", "verified recurring-cost comparison chart"],
        "review_stitch": "Two overlapping screenshots of the same pending-review card; joined once inside a blank gutter; no financial text re-rendered",
        "financial_ui_text_recreated": False,
        "editorial_chart": {"source": "evidence/verification.json", "before": "258.00", "after": "230.00", "scope": "Monthly recurring-cost projection; not a refund"},
        "business_evidence": FACTS,
        "beats": [{"start": s, "end": e, "composition": k} for s, e, k in BEATS],
        "prior_versions_overwritten": False,
        "business_actions_repeated": False,
    }
    (REV / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    print(output, flush=True)
    print(combined, flush=True)


if __name__ == "__main__":
    main()
