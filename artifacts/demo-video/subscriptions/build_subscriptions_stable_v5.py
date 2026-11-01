"""Stable reading and paging, while retaining intentional question focus.

Only the two question beats zoom. The analysis scroll uses a once-rasterized
native page and a floating-point vertical offset; its scale and viewport never
change. Existing business-state compositions and narration remain intact.
"""

from __future__ import annotations

from functools import lru_cache
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess

from PIL import Image, ImageDraw, ImageFilter

ROOT = Path(__file__).resolve().parent
REV = ROOT / "revisions/v5"
REV.mkdir(parents=True, exist_ok=True)
spec = importlib.util.spec_from_file_location("bava_edit_v4", ROOT / "build_subscriptions_stable_v4.py")
previous_edit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(previous_edit)
native, brand = previous_edit.native, previous_edit.brand
W, H, FPS, DURATION = 1920, 1080, 30, 40
FFMPEG = native.FFMPEG
OUTPUT_NAME = "BAVA-subscriptions-40s-stable-v5.mp4"
COMBINED_NAME = "BAVA-preview-95s-stable-v5.mp4"
SCROLL_START, SCROLL_END = 10, 12
SOURCE_SCROLL_PIXELS = 490
VIEWPORT_WIDTH, VIEWPORT_HEIGHT = 1620, 900
SOURCE_HEIGHT = 655
SCROLL_BAND_HEIGHT = round((727 - 150) * VIEWPORT_HEIGHT / SOURCE_HEIGHT)
SCROLL_DISTANCE = SOURCE_SCROLL_PIXELS * VIEWPORT_HEIGHT / SOURCE_HEIGHT


def ease(value):
    """C2-continuous start/stop, without a velocity or acceleration jump."""
    v = min(1.0, max(0.0, value))
    return v * v * v * (v * (v * 6 - 15) + 10)


def question_amount(t):
    if t < .15:
        return 0.0
    if t < .8:
        return ease((t - .15) / .65)
    if t < 1.7:
        return 1.0
    if t < 2.35:
        return 1 - ease((t - 1.7) / .65)
    return 0.0


@lru_cache(maxsize=2)
def question_assets(name):
    source = native.IMAGES[name]
    # Use the same viewport as the analysis and consent. Focusing a question
    # must not first snap the whole page out to a differently sized view.
    base = native.viewport(name)
    dimmed = Image.blend(base.filter(ImageFilter.GaussianBlur(1.8)), Image.new("RGB", (W, H), (7, 16, 29)), .28)
    dimmed.paste(brand.SHELL.crop((0, 0, W, 100)), (0, 0))
    dimmed.paste(brand.SHELL.crop((0, 1020, W, H)), (0, 1020))
    input_patch = source.crop((272, 738, 1428, 799))
    input_patch = input_patch.resize((1750, round(1750 * 61 / 1156)), Image.Resampling.LANCZOS).convert("RGBA")
    mask = Image.new("L", input_patch.size)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, input_patch.width - 1, input_patch.height - 1), radius=10, fill=255)
    input_patch.putalpha(mask)
    return base, dimmed, input_patch


def question(name, t):
    base, dimmed, patch = question_assets(name)
    q = question_amount(t)
    if q <= 0:
        return base.copy()
    result = Image.blend(base, dimmed, q)
    # Affine subpixel placement avoids integer crop/resize jumps. The query
    # animation has an explicit hold and returns to its original position.
    original_width = 1156 * 1620 / 1180
    original_height = 61 * 900 / 655
    original_x = 150 + 12 * 1620 / 1180
    original_y = 112 + 588 * 900 / 655
    width = original_width + (1750 - original_width) * q
    height = original_height + (patch.height - original_height) * q
    x = original_x + (85 - original_x) * q
    y = original_y + (635 - original_y) * q
    factor_x, factor_y = patch.width / width, patch.height / height
    overlay = patch.transform((W, H), Image.Transform.AFFINE,
                              (factor_x, 0, -x * factor_x, 0, factor_y, -y * factor_y),
                              resample=Image.Resampling.BICUBIC)
    result.paste(overlay, (0, 0), overlay)
    return result


@lru_cache(maxsize=1)
def analysis_assets():
    # Same response, same state, two native scroll positions 490px apart.
    # Join in the blank gutter after the contract table, before the floating
    # "latest message" control. That viewport control must not enter the page.
    top = native.IMAGES["05-managed-and-detected"].crop((260, 150, 1440, 660))
    bottom = native.IMAGES["06-cost-and-renewal"].crop((260, 170, 1440, 727))
    page = Image.new("RGB", (1180, top.height + bottom.height), "white")
    page.paste(top, (0, 0))
    page.paste(bottom, (0, top.height))
    # The original screenshot scrollbar is chrome, not response content. Keep
    # it out of the moving page so no duplicate/moving scroll thumb is created.
    ImageDraw.Draw(page).rectangle((1166, 0, 1179, page.height), fill="white")
    fixed_scale_page = page.resize((VIEWPORT_WIDTH, round(page.height * VIEWPORT_HEIGHT / SOURCE_HEIGHT)), Image.Resampling.LANCZOS)
    # Source composer remains at a constant position throughout the scroll.
    fixed_viewport = native.IMAGES["05-managed-and-detected"].crop(native.VIEWPORT).resize((VIEWPORT_WIDTH, VIEWPORT_HEIGHT), Image.Resampling.LANCZOS)
    return fixed_scale_page, fixed_viewport


def scroll_offset(t):
    return SCROLL_DISTANCE * ease((t - SCROLL_START) / (SCROLL_END - SCROLL_START))


def analysis(t):
    page, fixed = analysis_assets()
    offset = scroll_offset(t)
    # One immutable page raster, one vertical degree of freedom. No rounding
    # of camera bounds, no changing width/height and no horizontal translation.
    band = page.transform((VIEWPORT_WIDTH, SCROLL_BAND_HEIGHT), Image.Transform.AFFINE,
                          (1, 0, 0, 0, 1, offset), Image.Resampling.BICUBIC)
    viewport = fixed.copy()
    viewport.paste(band, (0, 0))
    # A quiet marker is shown only after the page has come to rest.
    if t >= SCROLL_END + .25:
        alpha = ease((t - SCROLL_END - .25) / .3)
        marker = Image.new("RGBA", viewport.size)
        draw = ImageDraw.Draw(marker)
        x = round((471 - 260) * VIEWPORT_WIDTH / 1180) - 10
        y1 = round((211 - 150) * VIEWPORT_HEIGHT / SOURCE_HEIGHT)
        y2 = round((711 - 150) * VIEWPORT_HEIGHT / SOURCE_HEIGHT)
        draw.line((x, y1, x, y2), fill=(*brand.MINT, round(255 * alpha)), width=3)
        viewport.paste(marker, (0, 0), marker)
    result = brand.SHELL.copy()
    native.rounded_paste(result, viewport, (150, 112), 18, native.LINE)
    return result


@lru_cache(maxsize=6)
def held(name):
    if name == "consent":
        return native.conversation("consent")
    return previous_edit.still(name)


BEATS = [
    (0, 2.5, "query_focus"),
    (2.5, 7, "consent"),
    (7, 10, "contracts_hold"),
    (10, 12, "one_vertical_scroll"),
    (12, 17.5, "analysis_hold"),
    (17.5, 20, "cancel_focus"),
    (20, 27, "review"),
    (27, 30.5, "approved"),
    (30.5, 35, "success"),
    (35, 40, "comparison"),
]


def content(t):
    if t < 2.5:
        return question("01-query", t)
    if t < 7:
        return held("consent")
    if t < 17.5:
        return analysis(t)
    if t < 20:
        return question("07-cancel-request", t - 17.5)
    if t < 27:
        return held("review")
    if t < 30.5:
        return held("approved")
    if t < 35:
        return held("success")
    return held("comparison")


def frame(t):
    # Clean cuts at user actions/page changes avoid white/navy flashes and
    # superimposed text at different positions. The receipt reveal retains
    # its existing layout: only the previously empty right column changes.
    if 30.35 <= t < 30.65:
        return Image.blend(held("approved"), held("success"), ease((t - 30.35) / .3))
    return content(t)


SAMPLES = [1.25, 4.5, 8.5, 10, 11, 13, 16, 18.75, 22, 28.5, 33, 38]


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
    sheet.save(ROOT / "BAVA-subscriptions-stable-v5-storyboard.jpg", quality=95)
    frame(33).save(ROOT / "BAVA-subscriptions-stable-v5-cover.jpg", quality=95)


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
    command = [FFMPEG, "-hide_banner", "-loglevel", "warning", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "pipe:0", "-an", "-c:v", "libx264", "-preset", "medium", "-crf", "17", "-pix_fmt", "yuv420p", "-movflags", "+faststart", "-metadata", "title=BAVA | Subscription management | Stable paging v5", str(output)]
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
        "revision": 5, "output": OUTPUT_NAME, "combined_preview": COMBINED_NAME,
        "width": W, "height": H, "fps": FPS, "duration_seconds": DURATION,
        "global_start_seconds": 55, "audio": False, "burned_in_narration_subtitles": False,
        "intentional_question_focus": "Retained twice, with smooth in/hold/out and subpixel placement",
        "reading_camera": "Locked width, height, scale and horizontal position",
        "analysis_scroll": {"start": SCROLL_START, "end": SCROLL_END, "source_distance_pixels": SOURCE_SCROLL_PIXELS, "rasterization": "Once before animation", "interpolation": "Floating point vertical offset, bicubic sampling, quintic easing"},
        "page_changes": "Clean cuts at actions; no whole-page crossfades, blank frames or text overlaps",
        "receipt_reveal": "Opacity only within a fixed right-side panel; left confirmation panel and arrow stay unchanged",
        "source": "Previously verified native screenshots; same-state response stitch and existing same-state review stitch",
        "financial_ui_text_recreated": False, "business_actions_repeated": False,
        "narration_timing_unchanged": True, "prior_artifacts_overwritten": False,
        "beats": [{"start": s, "end": e, "composition": name} for s, e, name in BEATS],
        "business_check_count": len(native.FACTS["checks"]),
    }
    (REV / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    print(output, flush=True)
    print(combined, flush=True)


if __name__ == "__main__":
    main()
