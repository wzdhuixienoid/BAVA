"""Match the opening focus exactly; retain complete native business cards.

Use the opening's own framing, easing, blur, dim, shadow and input placement.
Stable reading and scrolling are inherited from v5; fuller business views with
the reference row removed are inherited from v6. No business action is repeated.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess

from PIL import Image, ImageDraw, ImageFilter

ROOT = Path(__file__).resolve().parent
REV = ROOT / "revisions/v7"
REV.mkdir(parents=True, exist_ok=True)
spec = importlib.util.spec_from_file_location("bava_edit_v6", ROOT / "build_subscriptions_stable_v6.py")
v6 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(v6)
native, brand = v6.native, v6.brand
W, H, FPS, DURATION = 1920, 1080, 30, 40
FFMPEG = v6.FFMPEG
OUTPUT_NAME = "BAVA-subscriptions-40s-stable-v7.mp4"
COMBINED_NAME = "BAVA-preview-95s-stable-v7.mp4"


def opening_focus(image, local):
    """Same rendering operations as opening/build_opening.py::chat.

    The source is the actual captured query rather than the opening's typing
    sequence. All visual parameters and the ease-out focus timing are identical.
    """
    result = brand.product_screen(image, 0)
    q = brand.ease((local - .45) / .6)
    if q <= 0:
        return result
    dimmed = result.filter(ImageFilter.GaussianBlur(1.8 * q))
    result = Image.blend(dimmed, Image.new("RGB", (W, H), (7, 16, 29)), .28 * q)
    result.paste(brand.SHELL.crop((0, 0, W, 100)), (0, 0))
    result.paste(brand.SHELL.crop((0, 1020, W, H)), (0, 1020))
    detail = image.crop((270, 730, 1433, 807))
    width = round(1308 + (1510 - 1308) * q)
    height = round(width * detail.height / detail.width)
    detail = detail.resize((width, height), Image.Resampling.LANCZOS)
    x = round(454 + (205 - 454) * q)
    y = round(923 + (635 - 923) * q)
    mask = Image.new("L", detail.size)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, width - 1, height - 1), radius=13, fill=255)
    shadow = Image.new("RGBA", (W, H))
    ImageDraw.Draw(shadow).rounded_rectangle((x - 8, y - 8, x + width + 8, y + height + 8), radius=20, fill=(8, 20, 31, 210))
    shadow = shadow.filter(ImageFilter.GaussianBlur(18))
    brand.composite_alpha(result, shadow, q)
    result.paste(detail, (x, y), mask)
    return result


def frame(t):
    if t < 2.5:
        return opening_focus(native.IMAGES["01-query"], t)
    if 17.5 <= t < 20:
        return opening_focus(native.IMAGES["07-cancel-request"], t - 17.5)
    return v6.frame(t)


SAMPLES = [.25, .75, 1.5, 4.5, 8.5, 11, 13, 19, 22, 28.5, 33, 38]


def baseline():
    path = REV / "baseline-sha256.json"
    if not path.exists():
        targets = [*ROOT.glob("*.mp4"), *ROOT.glob("*.srt"), *ROOT.glob("narration-*.json")]
        values = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in targets if p.name not in {OUTPUT_NAME, COMBINED_NAME}}
        path.write_text(json.dumps(values, ensure_ascii=False, indent=2) + "\n")


def preview():
    sheet = Image.new("RGB", (1920, 1020), (7, 16, 29))
    draw = ImageDraw.Draw(sheet)
    for i, t in enumerate(SAMPLES):
        picture = frame(t)
        picture.save(REV / f"preview-{t:g}.jpg", quality=95)
        x, y = i % 4 * 480, i // 4 * 340
        sheet.paste(picture.resize((480, 270), Image.Resampling.LANCZOS), (x, y))
        full = t + 55
        draw.text((x + 20, y + 286), f"{int(full // 60):02d}:{full % 60:05.2f}", font=brand.font(22, 2), fill=brand.SLATE)
    sheet.save(ROOT / "BAVA-subscriptions-stable-v7-storyboard.jpg", quality=95)
    frame(28.5).save(ROOT / "BAVA-subscriptions-stable-v7-cover.jpg", quality=95)


def main():
    assert all(native.FACTS["checks"].values())
    baseline()
    preview()
    output = ROOT / OUTPUT_NAME
    command = [FFMPEG, "-hide_banner", "-loglevel", "warning", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "pipe:0", "-an", "-c:v", "libx264", "-preset", "medium", "-crf", "17", "-pix_fmt", "yuv420p", "-movflags", "+faststart", "-metadata", "title=BAVA | Subscription management | Opening-matched focus v7", str(output)]
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
        "revision": 7, "output": OUTPUT_NAME, "combined_preview": COMBINED_NAME,
        "width": W, "height": H, "fps": FPS, "duration_seconds": DURATION,
        "global_start_seconds": 55, "audio": False, "burned_in_narration_subtitles": False,
        "question_focus_reference": "opening/build_opening.py::chat",
        "question_focus": {"intervals": [[0, 2.5], [17.5, 20]], "base": "Full native product screen, as in the opening", "ease": "Opening ease-out, local .45 to 1.05 seconds", "input_crop": [270, 730, 1433, 807], "width": [1308, 1510], "x": [454, 205], "y": [923, 635], "blur_radius": "1.8*q", "dim": ".28*q", "shadow_blur_radius": 18},
        "stable_reading_and_scroll": "Exact v5 compositions retained outside focus and 27-35s business views",
        "business_display": "Full captured approved business area at 27-30.5s and full receipt at 30.5-35s, with reference label and value omitted",
        "business_card_anchor": {"x": v6.CARD_X, "y": v6.CARD_Y, "width": v6.CARD_WIDTH},
        "approved_source_crop": v6.APPROVED_SOURCE,
        "receipt_source_crops": [v6.RECEIPT_TOP_SOURCE, v6.RECEIPT_BOTTOM_SOURCE],
        "receipt_omitted_reference_row": v6.OMITTED_REFERENCE_ROW,
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
