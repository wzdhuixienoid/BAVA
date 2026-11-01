"""Fuller native business screenshots, with no reference row and safe bounds.

Retain the latest opening-style focus and stable scrolling. Expand 27-35s to
include the captured business area and surrounding explanation in one image.
Keep every presentation image above the existing footer separator at y=987.
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
REV = ROOT / "revisions/v8"
REV.mkdir(parents=True, exist_ok=True)
spec = importlib.util.spec_from_file_location("bava_edit_v7", ROOT / "build_subscriptions_stable_v7.py")
previous = importlib.util.module_from_spec(spec)
spec.loader.exec_module(previous)
native, brand = previous.native, previous.brand
W, H, FPS, DURATION = 1920, 1080, 30, 40
FFMPEG = previous.FFMPEG
OUTPUT_NAME = "BAVA-subscriptions-40s-stable-v8.mp4"
COMBINED_NAME = "BAVA-preview-95s-stable-v8.mp4"
SEPARATOR_Y = 987
SAFE_BOTTOM = 970

# Continuous native viewport includes every visible task step, approval state,
# bound subscription, warning/commit controls and the assistant's explanation.
APPROVED_HEADER_SOURCE = (440, 263, 1280, 355)
APPROVED_BODY_SOURCE = (440, 117, 1280, 698)
RECEIPT_TOP_SOURCE = (440, 121, 1280, 558)
RECEIPT_BOTTOM_SOURCE = (440, 588, 1280, 698)
OMITTED_REFERENCE_ROW = (440, 558, 1280, 588)
CARD_BOX = (428, 106, 1492, 970)
CHAT_BOX = (195, 112, 1725, 962)
REVIEW_BOX = (448, 120, 1472, 966)


@lru_cache(maxsize=2)
def business_source(success):
    if not success:
        # The approved screenshot starts inside the first timeline row. Its
        # heading and two already-completed first steps are unchanged from the
        # preceding captured review. Restore those unchanged native pixels,
        # joining in the empty gutter before step 3. All approval-dependent
        # rows, contract, warning and buttons come from the approved capture.
        top = native.IMAGES["08-review-full"].crop(APPROVED_HEADER_SOURCE)
        bottom = native.IMAGES["09-approved"].crop(APPROVED_BODY_SOURCE)
        image = Image.new("RGB", (top.width, top.height + bottom.height), "white")
        image.paste(top, (0, 0))
        image.paste(bottom, (0, top.height))
        return image
    source = native.IMAGES["11-cancel-receipt"]
    top, bottom = source.crop(RECEIPT_TOP_SOURCE), source.crop(RECEIPT_BOTTOM_SOURCE)
    # Remove the label and value together. Native timestamp, true success
    # state and every timeline step are retained without rewriting UI text.
    image = Image.new("RGB", (top.width, top.height + bottom.height), "white")
    image.paste(top, (0, 0))
    image.paste(bottom, (0, top.height))
    return image


@lru_cache(maxsize=2)
def business_view(success):
    result = brand.SHELL.copy()
    x1, y1, x2, y2 = CARD_BOX
    # One fixed outer frame for both states; the native receipt can be shorter
    # without moving, rescaling or changing the panel's lower boundary.
    panel = Image.new("RGB", (x2 - x1, y2 - y1), "white")
    image = business_source(success)
    fitted = image.resize((panel.width, round(panel.width * image.height / image.width)), Image.Resampling.LANCZOS)
    assert fitted.height <= panel.height
    panel.paste(fitted, (0, 0))
    native.rounded_paste(result, panel, (x1, y1), 15, native.LINE)
    return result


def contain_chat(image):
    # A constant fit for every conversation frame preserves the existing
    # question animation and scroll timing, while keeping the composer above
    # the separator. The brand header, line and footer remain at native size.
    result = brand.SHELL.copy()
    panel = image.crop((150, 112, 1770, 1012))
    panel = panel.resize((CHAT_BOX[2] - CHAT_BOX[0], CHAT_BOX[3] - CHAT_BOX[1]), Image.Resampling.LANCZOS)
    native.rounded_paste(result, panel, CHAT_BOX[:2], 18, native.LINE)
    return result


@lru_cache(maxsize=1)
def review_view():
    result = brand.SHELL.copy()
    # Preserve the complete same-state review card, including its bottom
    # confirmation controls, rather than clipping it at the footer line.
    panel = previous.frame(22).crop((424, 119, 1496, 1005))
    panel = panel.resize((REVIEW_BOX[2] - REVIEW_BOX[0], REVIEW_BOX[3] - REVIEW_BOX[1]), Image.Resampling.LANCZOS)
    native.rounded_paste(result, panel, REVIEW_BOX[:2], 15)
    return result


def frame(t):
    if t < 20:
        return contain_chat(previous.frame(t))
    if t < 27:
        return review_view()
    if t < 35:
        return business_view(t >= 30.5)
    return previous.frame(t)


SAMPLES = [1.5, 4.5, 8.5, 11, 13, 19, 22, 26, 28.5, 30.5, 33, 38]


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
    sheet.save(ROOT / "BAVA-subscriptions-stable-v8-storyboard.jpg", quality=95)
    frame(28.5).save(ROOT / "BAVA-subscriptions-stable-v8-cover.jpg", quality=95)


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
    command = [FFMPEG, "-hide_banner", "-loglevel", "warning", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "pipe:0", "-an", "-c:v", "libx264", "-preset", "medium", "-crf", "17", "-pix_fmt", "yuv420p", "-movflags", "+faststart", "-metadata", "title=BAVA | Subscription management | Complete cards and safe bounds v8", str(output)]
    with (REV / "render.log").open("w") as log:
        process = subprocess.Popen(command, stdin=subprocess.PIPE, stderr=log)
        for i in range(FPS * DURATION):
            process.stdin.write(frame(i / FPS).tobytes())
            if i % (FPS * 5) == 0:
                print(f"Rendered {i // FPS:02d}/{DURATION}s", flush=True)
        process.stdin.close()
        if process.wait() != 0:
            raise RuntimeError((REV / "render.log").read_text())
    earlier = ROOT.parent / "bills/BAVA-opening-and-bills-55s-silent.mp4"
    concat = REV / "concat.txt"
    concat.write_text(f"file '{earlier}'\nfile '{output}'\n")
    combined = ROOT / COMBINED_NAME
    subprocess.run([FFMPEG, "-hide_banner", "-loglevel", "warning", "-y", "-f", "concat", "-safe", "0", "-i", str(concat), "-c", "copy", "-an", "-movflags", "+faststart", str(combined)], check=True)
    manifest = {
        "revision": 8, "output": OUTPUT_NAME, "combined_preview": COMBINED_NAME,
        "width": W, "height": H, "fps": FPS, "duration_seconds": DURATION,
        "global_start_seconds": 55, "audio": False, "burned_in_narration_subtitles": False,
        "around_28_seconds": "One continuous native screenshot including every visible execution step, approval state, subscription details, warning, commit and cancel controls, plus surrounding explanation",
        "approved_source_crops": [APPROVED_HEADER_SOURCE, APPROVED_BODY_SOURCE],
        "approved_heading_stitch": "Unchanged native timeline heading and already-completed steps 1-2 from the same workflow; approved-dependent steps 3-7 and all controls use the actual approved screenshot",
        "receipt_source_crops": [RECEIPT_TOP_SOURCE, RECEIPT_BOTTOM_SOURCE],
        "omitted_reference_row": OMITTED_REFERENCE_ROW,
        "reference_label_and_value_visible": False,
        "business_panel_box": CARD_BOX,
        "conversation_panel_box": CHAT_BOX,
        "review_image_box": REVIEW_BOX,
        "footer_separator_y": SEPARATOR_Y,
        "maximum_image_bottom_y": SAFE_BOTTOM,
        "minimum_gap_above_separator_pixels": SEPARATOR_Y - SAFE_BOTTOM,
        "question_focus_and_scroll": "Latest v7 animation and v5 stable scroll preserved with a constant fit inside the safe image area",
        "business_financial_text_recreated": False,
        "business_actions_repeated": False,
        "narration_and_timing_changed": False,
        "previous_artifacts_overwritten": False,
        "business_check_count": len(native.FACTS["checks"]),
    }
    (REV / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    print(output, flush=True)
    print(combined, flush=True)


if __name__ == "__main__":
    main()
