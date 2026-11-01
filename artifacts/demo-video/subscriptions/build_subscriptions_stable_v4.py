"""Quiet edit: locked framing, longer holds and no overlapping page text.

Reuses the existing verified native UI compositions. No UI operation is repeated,
no prior artifact is overwritten, and the 40-second narration timing is retained.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import subprocess
from functools import lru_cache

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent
REV = ROOT / "revisions/v4"
REV.mkdir(parents=True, exist_ok=True)
spec = importlib.util.spec_from_file_location("subscription_native_compositions", ROOT / "build_subscriptions_stable_v3.py")
native = importlib.util.module_from_spec(spec)
spec.loader.exec_module(native)
brand = native.brand
W, H, FPS, DURATION = 1920, 1080, 30, 40
OUTPUT_NAME = "BAVA-subscriptions-40s-stable-v4.mp4"
COMBINED_NAME = "BAVA-preview-95s-stable-v4.mp4"
FFMPEG = native.FFMPEG

# Every beat has exactly one cached image. There is no per-frame cropping,
# rounding of camera coordinates, zoom, scrolling or changing focal point.
BEATS = [
    (0, 2.5, "query"),
    (2.5, 7, "consent"),
    (7, 11.5, "contracts"),
    (11.5, 17.5, "analysis"),
    (17.5, 20, "cancel"),
    (20, 27, "review"),
    (27, 30.5, "approved"),
    (30.5, 35, "success"),
    (35, 40, "comparison"),
]


@lru_cache(maxsize=12)
def still(name):
    if name == "analysis":
        # Cost and merchant boundary are visible on the same stationary page.
        # Keep a single thin guide rather than changing masks mid-explanation.
        image = native.viewport("06-cost-and-renewal")
        draw = ImageDraw.Draw(image)
        x1, y1, _, y2 = native.map_box((471, 211, 1258, 711))
        draw.line((x1 - 10, y1, x1 - 10, y2), fill=brand.MINT, width=3)
        return image
    if name == "review":
        # The full pending-review card stays still for seven seconds. Its risk,
        # bound subscription and confirmation button remain visible together.
        image = native.review("risk").copy()
        ImageDraw.Draw(image).rounded_rectangle((442, 769, 1476, 989), radius=10, outline=brand.MINT, width=2)
        return image
    if name == "approved":
        return native.confirmation_and_result(False)
    if name == "success":
        return native.confirmation_and_result(True)
    if name == "comparison":
        return native.result_comparison()
    return native.conversation(name)


def content(t):
    return still(next(key for start, end, key in BEATS if start <= t < end))


# A page swap fades out completely before the next page appears. At no point
# are two different text positions superimposed; all page geometry stays fixed.
PAGE_CHANGES = [2.5, 7, 11.5, 20, 27, 35]
HALF_FADE = .2
NEUTRAL_PAGE = brand.SHELL.copy()
ImageDraw.Draw(NEUTRAL_PAGE).rounded_rectangle((150, 112, 1769, 1011), radius=18, fill=(255, 255, 255), outline=native.LINE, width=2)


def smooth(value):
    value = min(1.0, max(0.0, value))
    return value * value * (3 - 2 * value)


def frame(t):
    for cut in PAGE_CHANGES:
        # A white page matte keeps the brightness of conversation transitions
        # steady; navy is used only when changing the editorial composition.
        matte = NEUTRAL_PAGE if cut in [2.5, 7, 11.5] else brand.SHELL
        if cut - HALF_FADE <= t < cut:
            return Image.blend(content(cut - HALF_FADE - .001), matte, smooth((t - cut + HALF_FADE) / HALF_FADE))
        if cut <= t < cut + HALF_FADE:
            return Image.blend(matte, content(cut + HALF_FADE + .001), smooth((t - cut) / HALF_FADE))
    # The two changes below keep their underlying page/layout in place. Only
    # the input field emphasis or actual returned result changes opacity.
    for cut in [17.5, 30.5]:
        if cut - .15 <= t < cut + .15:
            return Image.blend(content(cut - .151), content(cut + .151), smooth((t - cut + .15) / .3))
    return content(t)


SAMPLES = [1.25, 4.5, 9, 13, 16, 18.5, 21, 25.5, 28.5, 33, 36.5, 39]


def preview():
    sheet = Image.new("RGB", (1920, 1020), (7, 16, 29))
    draw = ImageDraw.Draw(sheet)
    for i, t in enumerate(SAMPLES):
        image = frame(t)
        image.save(REV / f"preview-{t:g}.jpg", quality=95)
        x, y = i % 4 * 480, i // 4 * 340
        sheet.paste(image.resize((480, 270), Image.Resampling.LANCZOS), (x, y))
        full = t + 55
        draw.text((x + 20, y + 286), f"{int(full // 60):02d}:{full % 60:05.2f}", font=brand.font(22, 2), fill=brand.SLATE)
    sheet.save(ROOT / "BAVA-subscriptions-stable-v4-storyboard.jpg", quality=95)
    frame(33).save(ROOT / "BAVA-subscriptions-stable-v4-cover.jpg", quality=95)


def main():
    assert all(native.FACTS["checks"].values())
    preview()
    output = ROOT / OUTPUT_NAME
    command = [FFMPEG, "-hide_banner", "-loglevel", "warning", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "pipe:0", "-an", "-c:v", "libx264", "-preset", "medium", "-crf", "17", "-pix_fmt", "yuv420p", "-movflags", "+faststart", "-metadata", "title=BAVA | Subscription management | Locked framing v4", str(output)]
    with (REV / "render.log").open("w") as log:
        process = subprocess.Popen(command, stdin=subprocess.PIPE, stderr=log)
        for i in range(FPS * DURATION):
            process.stdin.write(frame(i / FPS).tobytes())
            if i % (FPS * 5) == 0:
                print(f"Rendered {i // FPS:02d}/{DURATION}s", flush=True)
        process.stdin.close()
        if process.wait() != 0:
            raise RuntimeError((REV / "render.log").read_text())
    concat = REV / "concat.txt"
    previous = ROOT.parent / "bills/BAVA-opening-and-bills-55s-silent.mp4"
    concat.write_text(f"file '{previous}'\nfile '{output}'\n")
    combined = ROOT / COMBINED_NAME
    subprocess.run([FFMPEG, "-hide_banner", "-loglevel", "warning", "-y", "-f", "concat", "-safe", "0", "-i", str(concat), "-c", "copy", "-an", "-movflags", "+faststart", str(combined)], check=True)
    manifest = {
        "revision": 4, "output": OUTPUT_NAME, "combined_preview": COMBINED_NAME,
        "width": W, "height": H, "fps": FPS, "duration_seconds": DURATION,
        "global_start_seconds": 55, "audio": False, "burned_in_narration_subtitles": False,
        "camera_motion": False, "scrolling": False, "zoom": False,
        "page_transition": "Fade through a fixed white page matte for conversation changes, navy for editorial layout changes; never overlap two text positions",
        "within_page_transition": "Opacity only; same pixel coordinates",
        "fewer_beats": "Nine stable compositions, with a six-second analysis hold, seven-second review hold and five-second final check",
        "source": "Existing verified native UI captures and same-state review-card stitch from v3",
        "editorial_comparison": "Clearly separate navy chart using verified recurring-cost projection 258 to 230; not a refund",
        "financial_ui_text_recreated": False, "business_actions_repeated": False,
        "narration_timing_unchanged": True, "prior_artifacts_overwritten": False,
        "beats": [{"start": s, "end": e, "composition": key} for s, e, key in BEATS],
        "business_check_count": len(native.FACTS["checks"]),
    }
    (REV / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    print(output, flush=True)
    print(combined, flush=True)


if __name__ == "__main__":
    main()
