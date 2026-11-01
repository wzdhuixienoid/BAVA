"""Render the 40-second subscription demo from verified, ordered UI captures.

Only camera framing and short dissolves are added. Financial UI, authorization
states and results remain the captured product pixels. No narration is rendered.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
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


def camera(name, start=None, end=None, progress=0):
    image = IMAGES[name]
    if start:
        end = end or start
        q = smooth(progress)
        box = tuple(round(a + (b - a) * q) for a, b in zip(start, end))
        if not (0 <= box[0] < box[2] <= image.width and 0 <= box[1] < box[3] <= image.height):
            raise ValueError((name, box, image.size))
        image = image.crop(box)
    return brand.product_screen(image, 0, zoom=0)


def content(t):
    if t < 2.5:
        # Begin with the actual submitted text in context, then bring it closer.
        return camera("01-query", (0, 0, 1440, 800), (260, 150, 1440, 805), smooth(t / 2.5))
    if t < 6:
        # Consent precedes any subscription results in this conversation.
        return camera("02-read-consent", (310, 90, 1390, 690), (440, 140, 1280, 607), (t - 2.5) / 2)
    if t < 7:
        return camera("03-read-authorized", (440, 140, 1280, 607))
    if t < 10.5:
        return camera("05-managed-and-detected", (430, 260, 1288, 737), (443, 260, 1283, 727), (t - 7) / 3.5)
    if t < 14:
        return camera("06-cost-and-renewal", (405, 205, 1330, 719), (425, 221, 1315, 715), (t - 10.5) / 3.5)
    if t < 17.5:
        return camera("06-cost-and-renewal", (440, 185, 1280, 652), (440, 170, 1280, 637), (t - 14) / 3.5)
    if t < 20:
        return camera("07-cancel-request", (260, 150, 1440, 805), (260, 190, 1367, 805), (t - 17.5) / 2.5)
    if t < 23.5:
        return camera("08-review-full", (440, 86, 1280, 553), (440, 105, 1280, 572), (t - 20) / 3.5)
    if t < 27:
        # The lower recorded viewport includes the actual contract and confirm button.
        return camera("08-review", (440, 125, 1280, 592), (440, 151, 1280, 618), (t - 23.5) / 3.5)
    if t < 30.5:
        # Approved is explicitly still awaiting submission; no success is shown yet.
        return camera("09-approved", (440, 119, 1280, 586), (440, 140, 1280, 607), (t - 27) / 3.5)
    if t < 35:
        return camera("11-cancel-receipt", (440, 157, 1280, 624), (440, 162, 1280, 629), (t - 30.5) / 4.5)
    if t < 37.5:
        return camera("12-current-state", (160, 25, 1285, 650), (175, 35, 1273, 645), (t - 35) / 2.5)
    return camera("13-cancelled-contract", (175, 471, 715, 771), (180, 477, 711, 772), (t - 37.5) / 2.5)


CUTS = [2.5, 6, 7, 10.5, 14, 17.5, 20, 23.5, 27, 30.5, 35, 37.5]


def frame(t):
    for cut in CUTS:
        if cut - .12 <= t < cut + .12:
            return Image.blend(content(cut - .121), content(cut + .121), smooth((t - cut + .12) / .24))
    return content(t)


SHOTS = [
    [0, 2.5, "Ask: actual subscription query in composer"],
    [2.5, 6, "Explicit read consent, valid for five minutes"],
    [6, 7, "Read consent granted; query resumes"],
    [7, 10.5, "Actual managed-contract table with fees and renewal dates"],
    [10.5, 14, "Detected merchant billing, monthly cost, price change and renewals"],
    [14, 17.5, "Merchant-side management boundary in the real analysis"],
    [17.5, 20, "Natural-language cancellation request for the same video subscription"],
    [20, 23.5, "YELLOW review with explicit user confirmation required"],
    [23.5, 27, "Review the bound merchant, plan, fee and renewal; confirm cancellation"],
    [27, 30.5, "Ready for commit is not effective yet; continue execution"],
    [30.5, 35, "Actual succeeded receipt, consumed approval and provider reference"],
    [35, 37.5, "Fresh query after cancellation: monthly cost 230"],
    [37.5, 40, "Same contract is cancelled, recurring monthly cost zero"],
]


def main():
    facts = json.loads((ROOT / "evidence/verification.json").read_text())
    if not all(facts["checks"].values()):
        raise RuntimeError("Business evidence has not passed verification")
    output = ROOT / "BAVA-subscriptions-40s-silent.mp4"
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
                im.save(ROOT / "frames" / f"{i / FPS:05.2f}.png")
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
    sheet.save(ROOT / "BAVA-subscriptions-storyboard.jpg", quality=95)
    frame(33).save(ROOT / "BAVA-subscriptions-cover.jpg", quality=95)
    manifest = {
        "duration_seconds": DURATION,
        "global_start_seconds": 55,
        "width": W, "height": H, "fps": FPS,
        "audio": False,
        "burned_in_subtitles": False,
        "business_results_fabricated": False,
        "source_type": "Ordered actual local mock-bank UI captures with editorial camera motion and short dissolves; idle waiting omitted",
        "financial_text_recreated": False,
        "business_evidence": facts,
        "shots": SHOTS,
        "environment_mutations": "Only normal user-approved Mock subscription cancellation through the product UI; no code/config changes",
        "cost_scope": "Recurring-cost projection; not a refund, cash credit or proof of live merchant cancellation",
    }
    (ROOT / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    previous = ROOT.parent / "bills/BAVA-opening-and-bills-55s-silent.mp4"
    concat = ROOT / "concat.txt"
    concat.write_text(f"file '{previous}'\nfile '{output}'\n")
    combined = ROOT / "BAVA-preview-95s-silent.mp4"
    subprocess.run([FFMPEG, "-hide_banner", "-loglevel", "warning", "-y", "-f", "concat", "-safe", "0", "-i", str(concat), "-c", "copy", "-an", "-movflags", "+faststart", str(combined)], check=True)
    print(output, flush=True)
    print(combined, flush=True)


if __name__ == "__main__":
    main()
