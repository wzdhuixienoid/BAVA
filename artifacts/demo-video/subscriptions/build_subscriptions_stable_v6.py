"""Restore the original question shots; show fuller native business views.

Reading/scrolling stays as v5. The 27-35s sequence displays the whole captured
business area rather than isolated snippets. The receipt reference row is
omitted from the presentation, while the timestamp and true state stay intact.
"""

from __future__ import annotations

from functools import lru_cache
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent
REV = ROOT / "revisions/v6"
REV.mkdir(parents=True, exist_ok=True)
spec = importlib.util.spec_from_file_location("bava_edit_v5", ROOT / "build_subscriptions_stable_v5.py")
v5 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(v5)
native, brand = v5.native, v5.brand
W, H, FPS, DURATION = 1920, 1080, 30, 40
FFMPEG = v5.FFMPEG
OUTPUT_NAME = "BAVA-subscriptions-40s-stable-v6.mp4"
COMBINED_NAME = "BAVA-preview-95s-stable-v6.mp4"

# These are copied exactly from revisions/v1/build_subscriptions.py. Restore
# the original framing, easing, scale and timing, without a new focus effect.
def original_smooth(value):
    value = max(0, min(1, value))
    return value * value * (3 - 2 * value)


def original_camera(name, start, end, progress):
    image = native.IMAGES[name]
    q = original_smooth(progress)
    box = tuple(round(a + (b - a) * q) for a, b in zip(start, end))
    return brand.product_screen(image.crop(box), 0, zoom=0)


def original_question(t):
    if t < 2.5:
        return original_camera("01-query", (0, 0, 1440, 800), (260, 150, 1440, 805), original_smooth(t / 2.5))
    return original_camera("07-cancel-request", (260, 150, 1440, 805), (260, 190, 1367, 805), (t - 17.5) / 2.5)


CARD_WIDTH = 1064
CARD_X, CARD_Y = 428, 123
APPROVED_SOURCE = (472, 77, 1260, 621)
# Full result header and seven-step timeline, then native timestamp/footer.
# The reference label and value lie entirely inside the omitted 558-588 row.
RECEIPT_TOP_SOURCE = (472, 171, 1260, 558)
RECEIPT_BOTTOM_SOURCE = (472, 588, 1260, 621)
OMITTED_REFERENCE_ROW = (472, 558, 1260, 588)


@lru_cache(maxsize=2)
def business_card(success):
    if not success:
        card = native.IMAGES["09-approved"].crop(APPROVED_SOURCE)
    else:
        source = native.IMAGES["11-cancel-receipt"]
        top, bottom = source.crop(RECEIPT_TOP_SOURCE), source.crop(RECEIPT_BOTTOM_SOURCE)
        card = Image.new("RGB", (top.width, top.height + bottom.height))
        card.paste(top, (0, 0))
        card.paste(bottom, (0, top.height))
    return card.resize((CARD_WIDTH, round(CARD_WIDTH * card.height / card.width)), Image.Resampling.LANCZOS)


@lru_cache(maxsize=2)
def business_view(success):
    result = brand.SHELL.copy()
    # The same x/y and scale are used for both states. A clean state change
    # preserves legibility; the previous left/right snippet layout is removed.
    native.rounded_paste(result, business_card(success), (CARD_X, CARD_Y), 15, native.LINE)
    return result


def frame(t):
    if t < 2.5 or 17.5 <= t < 20:
        return original_question(t)
    if 27 <= t < 35:
        return business_view(t >= 30.5)
    return v5.frame(t)


SAMPLES = [1.25, 4.5, 8.5, 11, 13, 18.75, 22, 25.5, 28.5, 30.5, 33, 38]


def preview():
    sheet = Image.new("RGB", (1920, 1020), (7, 16, 29))
    d = ImageDraw.Draw(sheet)
    for i, t in enumerate(SAMPLES):
        image = frame(t)
        image.save(REV / f"preview-{t:g}.jpg", quality=95)
        x, y = i % 4 * 480, i // 4 * 340
        sheet.paste(image.resize((480, 270), Image.Resampling.LANCZOS), (x, y))
        full = t + 55
        d.text((x + 20, y + 286), f"{int(full // 60):02d}:{full % 60:05.2f}", font=brand.font(22, 2), fill=brand.SLATE)
    sheet.save(ROOT / "BAVA-subscriptions-stable-v6-storyboard.jpg", quality=95)
    frame(28.5).save(ROOT / "BAVA-subscriptions-stable-v6-cover.jpg", quality=95)


def baseline():
    path = REV / "baseline-sha256.json"
    if not path.exists():
        targets = [*ROOT.glob("*.mp4"), *ROOT.glob("*.srt"), *ROOT.glob("narration-*.json")]
        values = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in targets if p.name not in {OUTPUT_NAME, COMBINED_NAME}}
        path.write_text(json.dumps(values, ensure_ascii=False, indent=2) + "\n")


def main():
    assert all(native.FACTS["checks"].values())
    baseline()
    preview()
    output = ROOT / OUTPUT_NAME
    command = [FFMPEG, "-hide_banner", "-loglevel", "warning", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "pipe:0", "-an", "-c:v", "libx264", "-preset", "medium", "-crf", "17", "-pix_fmt", "yuv420p", "-movflags", "+faststart", "-metadata", "title=BAVA | Subscription management | Full business cards v6", str(output)]
    with (REV / "render.log").open("w") as log:
        process = subprocess.Popen(command, stdin=subprocess.PIPE, stderr=log)
        for i in range(FPS * DURATION):
            process.stdin.write(frame(i / FPS).tobytes())
            if i % (FPS * 5) == 0:
                print(f"Rendered {i // FPS:02d}/{DURATION}s", flush=True)
        process.stdin.close()
        if process.wait() != 0:
            raise RuntimeError((REV / "render.log").read_text())
    previous = ROOT.parent / "bills/BAVA-opening-and-bills-55s-silent.mp4"
    concat = REV / "concat.txt"
    concat.write_text(f"file '{previous}'\nfile '{output}'\n")
    combined = ROOT / COMBINED_NAME
    subprocess.run([FFMPEG, "-hide_banner", "-loglevel", "warning", "-y", "-f", "concat", "-safe", "0", "-i", str(concat), "-c", "copy", "-an", "-movflags", "+faststart", str(combined)], check=True)
    manifest = {
        "revision": 6, "output": OUTPUT_NAME, "combined_preview": COMBINED_NAME,
        "width": W, "height": H, "fps": FPS, "duration_seconds": DURATION,
        "global_start_seconds": 55, "audio": False, "burned_in_narration_subtitles": False,
        "question_focus": "Original v1 framing/easing/timing restored at 0-2.5 and 17.5-20; no floating input substitute",
        "stable_reading_and_scroll": "Unchanged v5 frames outside the explicitly revised ranges",
        "business_display": "27-30.5 full captured approved business area; 30.5-35 full receipt with native timestamp, omitting the reference row",
        "business_card_anchor": {"x": CARD_X, "y": CARD_Y, "width": CARD_WIDTH},
        "approved_source_crop": APPROVED_SOURCE,
        "receipt_source_crops": [RECEIPT_TOP_SOURCE, RECEIPT_BOTTOM_SOURCE],
        "receipt_omitted_reference_row": OMITTED_REFERENCE_ROW,
        "reference_number_visible": False,
        "financial_text_recreated": False, "business_actions_repeated": False,
        "narration_timing_unchanged": True, "prior_artifacts_overwritten": False,
        "business_check_count": len(native.FACTS["checks"]),
    }
    (REV / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    print(output, flush=True)
    print(combined, flush=True)


if __name__ == "__main__":
    main()
