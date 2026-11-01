"""Build the re-recorded 40-second statement segment from verified product captures."""

from __future__ import annotations

import bisect
import importlib.util
import json
import math
import os
import subprocess
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageOps

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / "source"
OPENING = ROOT.parent / "opening"
FPS, DURATION = 30, 40
spec = importlib.util.spec_from_file_location("bava_opening", OPENING / "build_opening.py")
brand = importlib.util.module_from_spec(spec)
spec.loader.exec_module(brand)
FFMPEG = brand.FFMPEG
W, H = brand.W, brand.H


def smooth(v):
    v = max(0.0, min(1.0, v))
    return v * v * (3 - 2 * v)


def load(name):
    return Image.open(SOURCE / name).convert("RGB")


REQUEST = load("01-request.png")
SENT = load("02-sent.png")
COMPLETED = load("04-report-created.png")
PROCESS = load("03-process-expanded.png")
REPORT = load("report-full.png")
HISTORY = load("09-history.png")
TIMING = json.loads((SOURCE / "processing/timing.json").read_text())
FRAME_TIMES = [item["seconds"] for item in TIMING]
LIVE_DURATION = FRAME_TIMES[-1]
ANCHORS = json.loads((SOURCE / "report-anchors.json").read_text())


@lru_cache(maxsize=160)
def live_frame(index):
    return load("processing/" + TIMING[index]["file"])


def focus_start(t):
    """Reverse the opening's input focus, using this take's real input image."""
    q = 1 - smooth((t - .25) / 1.05)
    im = brand.product_screen(REQUEST)
    if q > 0:
        im = Image.blend(im.filter(ImageFilter.GaussianBlur(1.8 * q)), Image.new("RGB", (W, H), (7, 16, 29)), .28 * q)
        im.paste(brand.SHELL.crop((0, 0, W, 100)), (0, 0))
        im.paste(brand.SHELL.crop((0, 1020, W, H)), (0, 1020))
        detail = REQUEST.crop((270, 730, 1433, 807))
        width = round(1308 + 202 * q)
        height = round(width * detail.height / detail.width)
        detail = detail.resize((width, height), Image.Resampling.LANCZOS)
        x, y = round(454 - 249 * q), round(923 - 288 * q)
        mask = Image.new("L", detail.size)
        ImageDraw.Draw(mask).rounded_rectangle((0, 0, width - 1, height - 1), radius=13, fill=255)
        im.paste(detail, (x, y), mask)
    if 1.55 < t < 2.05:
        # Editorial click emphasis for the actual recorded Send action.
        d = ImageDraw.Draw(im)
        r = 12 + 26 * smooth((t - 1.55) / .5)
        d.ellipse((1712 - r, 969 - r, 1712 + r, 969 + r), outline=brand.MINT, width=3)
    if t >= 2.05:
        sent = brand.product_screen(SENT)
        return Image.blend(im, sent, smooth((t - 2.05) / .25))
    return im


def ui_focus(image, progress=0.0):
    # A crop of the captured product, without re-rendering its data or labels.
    return brand.product_screen(image.crop((420, 150, 1380, 690)), progress, zoom=.012)


def report_view(y, rent_highlight=0.0):
    x, width, height = 130, 1180, 664
    y = round(max(0, min(REPORT.height - height, y)))
    shot = REPORT.crop((x, y, x + width, y + height))
    if rent_highlight > 0:
        row = ANCHORS["rows"][0]
        draw = ImageDraw.Draw(shot)
        box = (row["x"] - x + 2, row["y"] - y + 2, row["x"] - x + row["width"] - 2, row["y"] - y + row["height"] - 2)
        draw.rounded_rectangle(box, radius=7, outline=(46, 153, 148), width=2)
    return brand.product_screen(shot, 0, zoom=0)


def content(t):
    if t < 3:
        return focus_start(t)
    if t < 7:
        i = min(len(TIMING) - 1, max(0, bisect.bisect_right(FRAME_TIMES, (t - 3) / 4 * LIVE_DURATION) - 1))
        return brand.product_screen(live_frame(i), 0, zoom=0)
    if t < 10:
        return ui_focus(COMPLETED, (t - 7) / 3)
    if t < 12:
        return brand.product_screen(PROCESS.crop((420, 70, 1380, 610)), (t - 10) / 2, zoom=.008)
    if t < 20:
        return report_view(18 + 58 * smooth((t - 12) / 8))
    if t < 26:
        return report_view(330 + 65 * smooth((t - 20) / 6))
    if t < 30:
        return report_view(945 + 45 * smooth((t - 26) / 4))
    if t < 35:
        return report_view(1305 + 25 * smooth((t - 30) / 5), rent_highlight=1 if 31 < t < 34.5 else 0)
    return brand.product_screen(HISTORY, (t - 35) / 5, zoom=.018)


def frame(t):
    for cut in [7, 10, 12, 20, 26, 30, 35]:
        if cut - .15 <= t < cut + .15:
            return Image.blend(content(cut - .151), content(cut + .151), smooth((t - cut + .15) / .3))
    return content(t)


SHOTS = [
    [0, 3, "Request and recorded Send action"],
    [3, 7, "Actual UI capture after the request; waiting omitted"],
    [7, 10, "Report created in this conversation"],
    [10, 12, "Expand the completed task's actual execution record"],
    [12, 20, "Report overview and previous-month comparison"],
    [20, 26, "Category breakdown"],
    [26, 30, "Verified insights and transactions to review"],
    [30, 35, "Source transaction and report data scope"],
    [35, 40, "Same report saved in history"],
]


def main():
    facts = json.loads((ROOT / "evidence/verification.json").read_text())
    if not all(facts["checks"].values()):
        raise RuntimeError("Business evidence has not passed verification")
    output = ROOT / "BAVA-bills-40s-silent.mp4"
    cmd = [FFMPEG, "-hide_banner", "-loglevel", "warning", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "pipe:0", "-an", "-c:v", "libx264", "-preset", "medium", "-crf", "17", "-pix_fmt", "yuv420p", "-movflags", "+faststart", "-metadata", "title=BAVA | Statement analysis", str(output)]
    times = [1, 5, 8.5, 15, 23, 28, 32.5, 37.5]
    samples = []
    with (ROOT / "render.log").open("w") as log:
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=log)
        for i in range(FPS * DURATION):
            im = frame(i / FPS)
            proc.stdin.write(im.tobytes())
            if i in [round(t * FPS) for t in times]:
                im.save(ROOT / "frames" / f"{i / FPS:05.2f}.png")
                samples.append(im.copy())
            if i % (FPS * 5) == 0:
                print(f"Rendered {i // FPS:02d}/{DURATION}s", flush=True)
        proc.stdin.close()
        if proc.wait() != 0:
            raise RuntimeError((ROOT / "render.log").read_text())
    sheet = Image.new("RGB", (1920, 680), (7, 16, 29))
    d = ImageDraw.Draw(sheet)
    for i, im in enumerate(samples):
        x, y = (i % 4) * 480, (i // 4) * 340
        sheet.paste(im.resize((480, 270), Image.Resampling.LANCZOS), (x, y))
        d.text((x + 20, y + 286), f"00:{times[i] + 15:05.2f}", font=brand.font(22, 2), fill=brand.SLATE)
    sheet.save(ROOT / "BAVA-bills-storyboard.jpg", quality=95)
    frame(15).save(ROOT / "BAVA-bills-cover.jpg", quality=95)
    manifest = {
        "take": "Fresh isolated environment after deleting the previous segment's four captures",
        "duration_seconds": 40,
        "global_start_seconds": 15,
        "width": W,
        "height": H,
        "fps": FPS,
        "audio": False,
        "burned_in_subtitles": False,
        "business_results_fabricated": False,
        "source_type": "Actual local mock-banking UI screenshots, continuous UI captures after submitting the request, and camera motion",
        "model_timeout_changed": False,
        "business_evidence": facts,
        "shots": SHOTS,
        "editorial_highlight": "Outline only, around the actual rent transaction; financial text is unchanged",
    }
    (ROOT / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    concat = ROOT / "concat.txt"
    concat.write_text("file '" + str(OPENING / "BAVA-opening-15s-silent.mp4") + "'\nfile '" + str(output) + "'\n")
    combined = ROOT / "BAVA-opening-and-bills-55s-silent.mp4"
    subprocess.run([FFMPEG, "-hide_banner", "-loglevel", "warning", "-y", "-f", "concat", "-safe", "0", "-i", str(concat), "-c", "copy", "-an", "-movflags", "+faststart", str(combined)], check=True)
    print(output, flush=True)
    print(combined, flush=True)


if __name__ == "__main__":
    main()
