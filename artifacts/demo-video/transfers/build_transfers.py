"""Render the 70-second intelligent-transfer segment from verified native UI."""

from functools import lru_cache
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

from PIL import Image, ImageDraw, ImageFilter, ImageOps

ROOT = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("bava_opening", ROOT.parent / "opening/build_opening.py")
brand = importlib.util.module_from_spec(spec)
spec.loader.exec_module(brand)
W, H, FPS, DURATION = 1920, 1080, 30, 70
FFMPEG = brand.FFMPEG
OUTPUT_NAME = "BAVA-transfers-70s-silent.mp4"
COMBINED_NAME = "BAVA-preview-165s-silent.mp4"
SAFE_BOTTOM = 970
SEPARATOR_Y = 987


def load(name):
    return Image.open(ROOT / "prepared" / (name + ".png")).convert("RGB")


def rounded(base, patch, x, y, radius=15, outline=True):
    assert y + patch.height <= SAFE_BOTTOM
    mask = Image.new("L", patch.size)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, patch.width - 1, patch.height - 1), radius=radius, fill=255)
    base.paste(patch, (x, y), mask)
    if outline:
        ImageDraw.Draw(base).rounded_rectangle((x, y, x + patch.width - 1, y + patch.height - 1), radius=radius, outline=(45, 73, 87), width=2)
    return base


@lru_cache(maxsize=12)
def panel(name):
    source = load(name)
    patch = source.resize((1064, round(source.height * 1064 / source.width)), Image.Resampling.LANCZOS)
    assert patch.height <= 844, (name, patch.size)
    # Fixed width and visual center. Each cut shows a whole functional group;
    # there is no camera movement or text resampling during the reading hold.
    return rounded(brand.SHELL.copy(), patch, 428, 123 + (844 - patch.height) // 2)


@lru_cache(maxsize=2)
def question_assets(name):
    source = load(name)
    screenshot = ImageOps.fit(source, (1530, 850), Image.Resampling.LANCZOS)
    base = rounded(brand.SHELL.copy(), screenshot, 195, 112, radius=18)
    detail = source.crop((270, 646, 1274, 710))
    detail = detail.resize((1510, round(1510 * detail.height / detail.width)), Image.Resampling.LANCZOS).convert("RGBA")
    mask = Image.new("L", detail.size)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, detail.width - 1, detail.height - 1), radius=13, fill=255)
    detail.putalpha(mask)
    return base, detail


def question(name, local):
    base, detail = question_assets(name)
    q = brand.ease((local - .45) / .6)
    if q <= 0:
        return base.copy()
    # Same opening-style ease, focus, blur, dim and soft shadow, adapted to the
    # default 1280x720 browser capture. Float transforms prevent crop rounding.
    out = Image.blend(base.filter(ImageFilter.GaussianBlur(1.8 * q)), Image.new("RGB", (W, H), (7, 16, 29)), .28 * q)
    out.paste(brand.SHELL.crop((0, 0, W, 100)), (0, 0))
    out.paste(brand.SHELL.crop((0, SAFE_BOTTOM + 1, W, H)), (0, SAFE_BOTTOM + 1))
    factor = 1530 / 1280
    crop_top = (720 - 850 / factor) / 2
    original_width = 1004 * factor
    original_height = 64 * factor
    original_x = 195 + 270 * factor
    original_y = 112 + (646 - crop_top) * factor
    width = original_width + (1510 - original_width) * q
    height = original_height + (detail.height - original_height) * q
    x = original_x + (205 - original_x) * q
    y = original_y + (635 - original_y) * q
    shadow = Image.new("RGBA", (W, H))
    ImageDraw.Draw(shadow).rounded_rectangle((x - 8, y - 8, x + width + 8, y + height + 8), radius=20, fill=(8, 20, 31, round(210 * q)))
    shadow = shadow.filter(ImageFilter.GaussianBlur(18))
    out.paste(shadow, (0, 0), shadow)
    fx, fy = detail.width / width, detail.height / height
    overlay = detail.transform((W, H), Image.Transform.AFFINE, (fx, 0, -x * fx, 0, fy, -y * fy), Image.Resampling.BICUBIC)
    out.paste(overlay, (0, 0), overlay)
    # Only the feather of the editorial shadow can reach this boundary; all
    # actual UI pixels already fit above it. Keep the separator/footer intact.
    out.paste(brand.SHELL.crop((0, SAFE_BOTTOM + 1, W, H)), (0, SAFE_BOTTOM + 1))
    return out


@lru_cache(maxsize=1)
def final_check():
    result = brand.SHELL.copy()
    salary, statement = load("salary-after"), load("statement-after")
    salary = salary.resize((600, round(salary.height * 600 / salary.width)), Image.Resampling.LANCZOS)
    statement = statement.resize((1520, round(statement.height * 1520 / statement.width)), Image.Resampling.LANCZOS)
    rounded(result, salary, 660, 155)
    rounded(result, statement, 200, 465)
    return result


SHOTS = [
    (0, 4, "yellow-query", "Natural-language request; retain the opening-style question focus"),
    (4, 11, "payee-choice", "Two real same-name candidates; bank and masked account require user choice"),
    (11, 14, "yellow-risk", "Actual YELLOW decision, personal limit and daily exposure"),
    (14, 18, "yellow-review", "Complete bound account, payee, bank, amount and remark before approval"),
    (18, 22, "yellow-approved", "Approval is complete but transfer has not been submitted"),
    (22, 27, "yellow-success", "Native success receipt, transaction details and all ten execution steps"),
    (27, 31, "red-query", "Second request, 1200 yuan, with opening-style focus"),
    (31, 35, "red-risk", "RED: personal limit reached and daily exposure 1300 exceeds 1000"),
    (35, 39, "red-review", "Complete 1200-yuan transfer details before confirmation"),
    (39, 45, "red-confirmed", "Confirmation alone stops at the separate identity-verification gate"),
    (45, 51, "red-challenge", "Actual Mock challenge pending; no verification code is displayed"),
    (51, 56, "red-verified", "Identity verified; transaction details and explicit commit remain visible"),
    (56, 64, "red-success", "Native final success, consumed approval, verified auth and complete timeline"),
    (64, 70, "final-check", "Fresh native balance and filtered ledger show both posted transfers"),
]


def frame(t):
    name = next(name for start, end, name, _ in SHOTS if start <= t < end)
    if name == "yellow-query":
        return question("01-yellow-query", t)
    if name == "red-query":
        return question("07-red-query", t - 27)
    if name == "final-check":
        return final_check()
    return panel(name)


SAMPLES = [1.5, 7, 12.5, 16, 20, 24.5, 28.5, 33, 37, 42, 48, 53.5, 60, 67]


def preview():
    (ROOT / "frames").mkdir(exist_ok=True)
    sheet = Image.new("RGB", (1920, 1360), (7, 16, 29))
    draw = ImageDraw.Draw(sheet)
    for i, t in enumerate(SAMPLES):
        picture = frame(t)
        picture.save(ROOT / "frames" / f"preview-{t:g}.jpg", quality=95)
        x, y = i % 4 * 480, i // 4 * 340
        sheet.paste(picture.resize((480, 270), Image.Resampling.LANCZOS), (x, y))
        absolute = t + 95
        draw.text((x + 20, y + 286), f"{int(absolute // 60):02d}:{absolute % 60:05.2f}", font=brand.font(22, 2), fill=brand.SLATE)
    sheet.save(ROOT / "BAVA-transfers-storyboard.jpg", quality=95)
    frame(60).save(ROOT / "BAVA-transfers-cover.jpg", quality=95)


def main():
    facts = json.loads((ROOT / "evidence/verification.json").read_text())
    assert all(facts["checks"].values())
    preview()
    if "--preview-only" in sys.argv:
        return
    output = ROOT / OUTPUT_NAME
    command = [FFMPEG, "-hide_banner", "-loglevel", "warning", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "pipe:0", "-an", "-c:v", "libx264", "-preset", "medium", "-crf", "17", "-pix_fmt", "yuv420p", "-movflags", "+faststart", "-metadata", "title=BAVA | Intelligent transfers | Verified actions", str(output)]
    with (ROOT / "render.log").open("w") as log:
        process = subprocess.Popen(command, stdin=subprocess.PIPE, stderr=log)
        for n in range(FPS * DURATION):
            process.stdin.write(frame(n / FPS).tobytes())
            if n % (FPS * 5) == 0:
                print(f"Rendered {n // FPS:02d}/{DURATION}s", flush=True)
        process.stdin.close()
        if process.wait() != 0:
            raise RuntimeError((ROOT / "render.log").read_text())
    previous = ROOT.parent / "subscriptions/BAVA-preview-95s-stable-v8.mp4"
    concat = ROOT / "concat.txt"
    concat.write_text(f"file '{previous}'\nfile '{output}'\n")
    combined = ROOT / COMBINED_NAME
    subprocess.run([FFMPEG, "-hide_banner", "-loglevel", "warning", "-y", "-f", "concat", "-safe", "0", "-i", str(concat), "-c", "copy", "-an", "-movflags", "+faststart", str(combined)], check=True)
    manifest = {
        "part": 4, "scenario": "Intelligent transfers with same-name selection and YELLOW/RED control",
        "output": OUTPUT_NAME, "combined_preview": COMBINED_NAME,
        "width": W, "height": H, "fps": FPS, "duration_seconds": DURATION,
        "global_start_seconds": 95, "global_end_seconds": 165,
        "audio": False, "burned_in_narration_subtitles": False,
        "source": "Actual local Mock bank UI captures, same-state native-card reconstruction and whole functional-group framing; no recreated financial text",
        "question_focus": "Opening-style ease-out focus, dim, blur and shadow; float placement, fixed background, two requests",
        "reading_motion": "Static cached compositions; clean state cuts, no continuous panning, zoom or overlapping page text",
        "footer_separator_y": SEPARATOR_Y, "maximum_image_or_shadow_bottom_y": SAFE_BOTTOM,
        "reference_numbers_visible": False, "verification_code_visible": False,
        "receipt_presentation": "Native transaction header/details, complete ten-step timeline and timestamp; repeated risk block and reference row omitted",
        "authentication_boundary": "MOCK_CODE verification only; no real SMS, face, U-shield or live bank MFA",
        "business_results_fabricated": False, "business_verification": facts,
        "previous_artifacts_overwritten": False,
        "shots": [{"start": s, "end": e, "asset": name, "purpose": purpose} for s, e, name, purpose in SHOTS],
    }
    (ROOT / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    print(output, flush=True)
    print(combined, flush=True)


if __name__ == "__main__":
    main()
