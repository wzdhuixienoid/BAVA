"""Render the 40-second subscription demo from verified, ordered UI captures.

Stable revision: each shot has one fixed framing and fixed red annotations.
Financial UI, authorization states and results remain the captured product
pixels. No narration is rendered and no camera movement is interpolated.
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
OPENING = ROOT.parent / "opening"
FPS, DURATION = 30, 40
spec = importlib.util.spec_from_file_location("bava_opening", OPENING / "build_opening.py")
brand = importlib.util.module_from_spec(spec)
spec.loader.exec_module(brand)
W, H, FFMPEG = brand.W, brand.H, brand.FFMPEG
OUTPUT_NAME = "BAVA-subscriptions-40s-stable-v2.mp4"
COMBINED_NAME = "BAVA-preview-95s-stable-v2.mp4"
RED = (224, 51, 51)
FULL = (0, 5, 1440, 805)
READ = (320, 100, 1400, 700)
ANALYSIS = (320, 116, 1400, 716)
WORKFLOW = (320, 80, 1400, 680)


def smooth(value):
    value = max(0, min(1, value))
    return value * value * (3 - 2 * value)


def load(name):
    return Image.open(SOURCE / (name + ".png")).convert("RGB")


IMAGES = {name: load(name) for name in [
    "01-query", "02-read-consent", "03-read-authorized",
    "05-managed-and-detected", "06-cost-and-renewal", "07-cancel-request",
    "08-review-full", "08-review", "09-approved", "11-cancel-receipt",
    "12-current-state", "13-cancelled-contract",
]}


def shot(start, end, name, crop, rectangles, purpose):
    return {"start": start, "end": end, "capture": name, "crop": crop,
            "red_boxes_in_source_pixels": rectangles, "purpose": purpose}


# All boxes use coordinates in the original screenshots. The composition is
# constant for the entire shot; annotations never pulse, travel or grow.
SHOTS = [
    shot(0, 2.5, "01-query", FULL, [(272, 738, 1428, 799)], "Subscription query in composer"),
    shot(2.5, 6, "02-read-consent", READ, [(465, 239, 1266, 353)], "Five-minute read authorization"),
    shot(6, 7, "03-read-authorized", READ, [(481, 263, 640, 315)], "Read consent granted; query resumes"),
    shot(7, 10.5, "05-managed-and-detected", ANALYSIS, [(465, 392, 1266, 650)], "Managed contracts and renewal dates"),
    shot(10.5, 14, "06-cost-and-renewal", ANALYSIS, [(464, 386, 1266, 711)], "Cost, price change and upcoming renewals"),
    shot(14, 17.5, "06-cost-and-renewal", ANALYSIS, [(464, 207, 1266, 372)], "Same stationary page; highlight merchant-side management"),
    shot(17.5, 20, "07-cancel-request", FULL, [(272, 738, 1428, 799)], "Natural-language cancellation request"),
    shot(20, 23.5, "08-review-full", WORKFLOW, [(480, 160, 1252, 253)], "YELLOW risk and required user confirmation"),
    shot(23.5, 27, "08-review", WORKFLOW, [(479, 442, 1252, 614)], "Bound subscription details and confirm button"),
    shot(27, 30.5, "09-approved", WORKFLOW, [(480, 484, 1252, 569)], "Approved but not yet effective; continue execution"),
    shot(30.5, 35, "11-cancel-receipt", WORKFLOW, [(481, 447, 1251, 611)], "Final result, consumed approval and provider reference"),
    shot(35, 37.5, "12-current-state", FULL, [(536, 154, 1269, 256)], "Refreshed monthly and yearly recurring cost"),
    shot(37.5, 40, "13-cancelled-contract", FULL, [(181, 476, 722, 766)], "Cancelled contract in page context, without an extreme close-up"),
]


@lru_cache(maxsize=32)
def render_shot(index):
    item = SHOTS[index]
    source = IMAGES[item["capture"]]
    crop = item["crop"]
    assert 0 <= crop[0] < crop[2] <= source.width
    assert 0 <= crop[1] < crop[3] <= source.height
    # Every crop has the exact 1620:900 ratio, so no hidden fitting offsets occur.
    assert abs((crop[2] - crop[0]) / (crop[3] - crop[1]) - 1.8) < 1e-9
    image = brand.product_screen(source.crop(crop), 0, zoom=0)
    draw = ImageDraw.Draw(image)
    scale = 1620 / (crop[2] - crop[0])
    for box in item["red_boxes_in_source_pixels"]:
        assert crop[0] <= box[0] < box[2] <= crop[2]
        assert crop[1] <= box[1] < box[3] <= crop[3]
        mapped = (150 + (box[0] - crop[0]) * scale,
                  112 + (box[1] - crop[1]) * scale,
                  150 + (box[2] - crop[0]) * scale,
                  112 + (box[3] - crop[1]) * scale)
        draw.rounded_rectangle(tuple(round(v) for v in mapped), radius=8, outline=RED, width=4)
    return image


def content(t):
    return render_shot(next(i for i, item in enumerate(SHOTS) if item["start"] <= t < item["end"]))


# Dissolve only between different framings. Native business-state changes use
# clean cuts. The highlight change at 14s retains the exact same page pixels.
DISSOLVES = [2.5, 7, 17.5, 20, 35]


def frame(t):
    for cut in DISSOLVES:
        if cut - .1 <= t < cut + .1:
            return Image.blend(content(cut - .101), content(cut + .101), smooth((t - cut + .1) / .2))
    return content(t)


def main():
    facts = json.loads((ROOT / "evidence/verification.json").read_text())
    if not all(facts["checks"].values()):
        raise RuntimeError("Business evidence has not passed verification")
    output = ROOT / OUTPUT_NAME
    cmd = [FFMPEG, "-hide_banner", "-loglevel", "warning", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "pipe:0", "-an", "-c:v", "libx264", "-preset", "medium", "-crf", "17", "-pix_fmt", "yuv420p", "-movflags", "+faststart", "-metadata", "title=BAVA | Subscription management", str(output)]
    times = [1.5, 4.5, 8.5, 12, 15.5, 18.5, 21.5, 25.5, 29, 33, 36, 39]
    samples = []
    (ROOT / "frames").mkdir(exist_ok=True)
    with (ROOT / "render.log").open("w") as log:
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=log)
        for i in range(FPS * DURATION):
            im = frame(i / FPS)
            proc.stdin.write(im.tobytes())
            if i in [round(t * FPS) for t in times]:
                im.save(ROOT / "frames" / f"stable-v2-{i / FPS:05.2f}.png")
                samples.append(im.copy())
            if i % (FPS * 5) == 0:
                print(f"Rendered {i // FPS:02d}/{DURATION}s", flush=True)
        proc.stdin.close()
        if proc.wait() != 0:
            raise RuntimeError((ROOT / "render.log").read_text())
    sheet = Image.new("RGB", (1920, 1020), (7, 16, 29))
    d = ImageDraw.Draw(sheet)
    for i, im in enumerate(samples):
        x, y = (i % 4) * 480, (i // 4) * 340
        sheet.paste(im.resize((480, 270), Image.Resampling.LANCZOS), (x, y))
        absolute = times[i] + 55
        d.text((x + 20, y + 286), f"{int(absolute // 60):02d}:{absolute % 60:05.2f}", font=brand.font(22, 2), fill=brand.SLATE)
    sheet.save(ROOT / "BAVA-subscriptions-stable-v2-storyboard.jpg", quality=95)
    frame(33).save(ROOT / "BAVA-subscriptions-stable-v2-cover.jpg", quality=95)
    manifest = {
        "revision": 2,
        "output": OUTPUT_NAME,
        "combined_preview": COMBINED_NAME,
        "duration_seconds": DURATION,
        "global_start_seconds": 55,
        "width": W, "height": H, "fps": FPS,
        "audio": False,
        "burned_in_subtitles": False,
        "business_results_fabricated": False,
        "source_type": "Ordered actual local mock-bank UI captures with fixed framing, stationary red outline annotations and five short dissolves; idle waiting omitted",
        "camera_motion": False,
        "subpixel_resampling_over_time": False,
        "max_product_display_scale": 1.5,
        "annotation": "One fixed 4px red outline at a time, no pulse, no movement, no replacement of native UI text",
        "financial_text_recreated": False,
        "business_evidence": facts,
        "shots": SHOTS,
        "environment_mutations": "Revision 2 is an offline edit of the existing verified captures; no additional banking action",
        "cost_scope": "Recurring-cost projection; not a refund, cash credit or proof of live merchant cancellation",
    }
    (ROOT / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    previous = ROOT.parent / "bills/BAVA-opening-and-bills-55s-silent.mp4"
    concat = ROOT / "concat.txt"
    concat.write_text(f"file '{previous}'\nfile '{output}'\n")
    combined = ROOT / COMBINED_NAME
    subprocess.run([FFMPEG, "-hide_banner", "-loglevel", "warning", "-y", "-f", "concat", "-safe", "0", "-i", str(concat), "-c", "copy", "-an", "-movflags", "+faststart", str(combined)], check=True)
    print(output, flush=True)
    print(combined, flush=True)


if __name__ == "__main__":
    main()
