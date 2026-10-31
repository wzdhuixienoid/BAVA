"""Render BAVA's 15-second silent opening from captured product UI.

No business result is synthesized. Only framing, motion and brand graphics are added.
"""

from __future__ import annotations

import json
import math
import os
import subprocess
from functools import lru_cache
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / "source"
W, H, FPS, DURATION = 1920, 1080, 30, 15
FFMPEG = os.environ.get(
    "BAVA_VIDEO_FFMPEG",
    "/private/tmp/banking-video-tools/imageio_ffmpeg/binaries/ffmpeg-macos-aarch64-v7.1",
)
AVENIR = "/System/Library/Fonts/Avenir Next.ttc"
PINGFANG = "/System/Library/AssetsV2/com_apple_MobileAsset_Font7/3419f2a427639ad8c8e139149a287865a90fa17e.asset/AssetData/PingFang.ttc"
WHITE = (238, 247, 250)
MINT = (86, 227, 204)
SLATE = (140, 164, 182)
PROMPT = "分析2026年8月消费，生成报告"


def ease(v: float) -> float:
    v = max(0.0, min(1.0, v))
    return 1 - (1 - v) ** 3


@lru_cache(maxsize=48)
def font(size: int, weight: int = 7, chinese: bool = False):
    return ImageFont.truetype(PINGFANG if chinese else AVENIR, size, index=0 if chinese else weight)


def background() -> Image.Image:
    y, x = np.mgrid[0:H, 0:W]
    glow = np.exp(-(((x - 1490) / 700) ** 2 + ((y - 450) / 620) ** 2))
    second = np.exp(-(((x - 280) / 1100) ** 2 + ((y - 920) / 420) ** 2))
    rgb = np.stack([7 + 2 * glow + 2 * second, 16 + 26 * glow + 7 * second, 29 + 30 * glow + 9 * second], axis=-1)
    im = Image.fromarray(np.uint8(np.clip(rgb, 0, 255)), "RGB")
    d = ImageDraw.Draw(im)
    for gx in range(1040, 1920, 56):
        for gy in range(130, 970, 56):
            d.ellipse((gx, gy, gx + 2, gy + 2), fill=(25, 54, 67))
    d.line((120, 987, 1800, 987), fill=(27, 50, 64), width=1)
    return im


BG = background()


def composite_alpha(base, layer, alpha):
    if alpha <= 0:
        return base
    if alpha < 1:
        layer = layer.copy()
        layer.putalpha(layer.getchannel("A").point(lambda v: round(v * alpha)))
    base.paste(layer, (0, 0), layer)
    return base


def text_layer(text, xy, size, color=WHITE, weight=7):
    layer = Image.new("RGBA", (W, H))
    ImageDraw.Draw(layer).text(xy, text, fill=color, font=font(size, weight))
    return layer


def line_progress(draw, points, progress, fill, width):
    lengths = [math.dist(a, b) for a, b in zip(points, points[1:])]
    remaining = sum(lengths) * max(0.0, min(1.0, progress))
    for a, b, length in zip(points, points[1:], lengths):
        if remaining <= 0:
            break
        q = min(1.0, remaining / length)
        end = (a[0] + q * (b[0] - a[0]), a[1] + q * (b[1] - a[1]))
        draw.line((a, end), fill=fill, width=width)
        remaining -= length


def hero(t):
    im = BG.copy()
    d = ImageDraw.Draw(im)
    d.text((150, 138), "VERIFIED BANKING", font=font(20, 2), fill=MINT)
    composite_alpha(im, text_layer("BAVA", (137, 265), 230, weight=8), ease((t - .12) / .85))
    composite_alpha(im, text_layer("Banking AI for Verified Actions", (153, 555), 34, SLATE), ease((t - .60) / .65))
    words = ["Ask.", "Plan.", "Verify.", "Act."]
    positions = [153, 292, 447, 643]
    for i, (word, x) in enumerate(zip(words, positions)):
        composite_alpha(im, text_layer(word, (x, 650), 44, MINT if i == 2 else WHITE, 2), ease((t - .90 - .23 * i) / .55))
    d = ImageDraw.Draw(im)
    d.line((157, 760, 774, 760), fill=(31, 66, 77), width=2)
    for i, x in enumerate([158, 360, 568, 774]):
        q = ease((t - .95 - .23 * i) / .5)
        d.ellipse((x - 5, 755, x + 5, 765), fill=MINT if q > .5 else (41, 74, 86))
    ornament = Image.new("RGBA", (W, H))
    od = ImageDraw.Draw(ornament)
    cx, cy = 1435, 505
    od.ellipse((cx - 287, cy - 287, cx + 287, cy + 287), outline=(47, 98, 110, 95), width=2)
    od.arc((cx - 310, cy - 310, cx + 310, cy + 310), 200, 325, fill=(65, 157, 168, 125), width=3)
    od.arc((cx - 258, cy - 258, cx + 258, cy + 258), 15, 103, fill=(65, 157, 168, 100), width=2)
    shield = [(1435, 295), (1592, 350), (1592, 502), (1573, 565), (1530, 622), (1435, 687), (1340, 622), (1297, 565), (1278, 502), (1278, 350), (1435, 295)]
    line_progress(od, shield, ease((t - .3) / 1.2), (86, 227, 204, 235), 5)
    line_progress(od, [(1357, 487), (1413, 543), (1520, 429)], ease((t - 1.25) / .65), (219, 255, 246, 255), 12)
    for angle in [220, 310, 40, 130]:
        theta = math.radians(angle)
        px, py = cx + 287 * math.cos(theta), cy + 287 * math.sin(theta)
        od.ellipse((px - 9, py - 9, px + 9, py + 9), fill=(15, 44, 55, 255), outline=(86, 227, 204, 200), width=2)
    composite_alpha(im, ornament, ease((t - .15) / .7))
    d = ImageDraw.Draw(im)
    d.text((150, 1010), "合成数据 · 模拟银行环境", font=font(20, chinese=True), fill=SLATE)
    return im


def source(name):
    return Image.open(SOURCE / name).convert("RGB")


SCREENS = {
    "accounts": source("dashboard-ready.png"),
    "spending": source("spending-ready.png"),
    "subscriptions": source("subscriptions.png"),
    "wealth": source("wealth.png"),
}
CHAT = [source(f"chat-{i:02d}.png") for i in range(len(PROMPT) + 1)]


def shell():
    im = BG.copy()
    d = ImageDraw.Draw(im)
    d.text((150, 36), "BAVA", font=font(38, 8), fill=WHITE)
    d.text((1170, 47), "Ask. Plan. Verify. Act.", font=font(25, 2), fill=MINT)
    d.text((150, 1030), "合成数据 · 模拟银行环境", font=font(20, chinese=True), fill=SLATE)
    return im


SHELL = shell()
SCREEN_X, SCREEN_Y, SCREEN_W, SCREEN_H = 150, 112, 1620, 900
MASK = Image.new("L", (SCREEN_W, SCREEN_H))
ImageDraw.Draw(MASK).rounded_rectangle((0, 0, SCREEN_W - 1, SCREEN_H - 1), radius=18, fill=255)


def product_screen(image, progress=0.0, zoom=.018):
    im = SHELL.copy()
    q = max(0.0, min(1.0, progress))
    z = 1 + zoom * ease(q)
    screen = ImageOps.fit(image, (round(SCREEN_W * z), round(SCREEN_H * z)), method=Image.Resampling.LANCZOS)
    left = (screen.width - SCREEN_W) // 2
    top = (screen.height - SCREEN_H) // 2
    screen = screen.crop((left, top, left + SCREEN_W, top + SCREEN_H))
    im.paste(screen, (SCREEN_X, SCREEN_Y), MASK)
    ImageDraw.Draw(im).rounded_rectangle((SCREEN_X, SCREEN_Y, SCREEN_X + SCREEN_W, SCREEN_Y + SCREEN_H), radius=18, outline=(46, 77, 91), width=1)
    return im


def chat(t):
    local = t - 11
    typed = max(0, min(len(PROMPT), int((local - .6) / 2.0 * len(PROMPT))))
    img = CHAT[typed]
    im = product_screen(img, 0)
    q = ease((local - .45) / .6)
    if q <= 0:
        return im
    dimmed = im.filter(ImageFilter.GaussianBlur(1.8 * q))
    dark = Image.new("RGB", (W, H), (7, 16, 29))
    im = Image.blend(dimmed, dark, .28 * q)
    im.paste(SHELL.crop((0, 0, W, 100)), (0, 0))
    im.paste(SHELL.crop((0, 1020, W, H)), (0, 1020))
    detail = img.crop((270, 730, 1433, 807))
    start_w, end_w = 1308, 1510
    width = round(start_w + (end_w - start_w) * q)
    height = round(width * detail.height / detail.width)
    detail = detail.resize((width, height), Image.Resampling.LANCZOS)
    x = round(454 + (205 - 454) * q)
    y = round(923 + (635 - 923) * q)
    mask = Image.new("L", detail.size)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, width - 1, height - 1), radius=13, fill=255)
    shadow = Image.new("RGBA", (W, H))
    sd = ImageDraw.Draw(shadow)
    sd.rounded_rectangle((x - 8, y - 8, x + width + 8, y + height + 8), radius=20, fill=(8, 20, 31, 210))
    shadow = shadow.filter(ImageFilter.GaussianBlur(18))
    composite_alpha(im, shadow, q)
    im.paste(detail, (x, y), mask)
    return im


SHOTS = [
    (3.5, 5.0, "accounts"),
    (5.0, 7.0, "spending"),
    (7.0, 9.0, "subscriptions"),
    (9.0, 11.0, "wealth"),
]


def content(t):
    if t < 3.5:
        return hero(t)
    if t >= 11:
        return chat(t)
    for start, end, name in SHOTS:
        if start <= t < end:
            return product_screen(SCREENS[name], (t - start) / (end - start))
    raise ValueError(t)


def frame(t):
    # Short dissolves connect honest captures; no business states are reordered.
    for cut in [3.5, 5.0, 7.0, 9.0, 11.0]:
        if cut - .12 <= t < cut + .12:
            a = content(cut - .121)
            b = content(cut + .121)
            return Image.blend(a, b, ease((t - cut + .12) / .24))
    return content(t)


def main():
    output = ROOT / "BAVA-opening-15s-silent.mp4"
    cmd = [FFMPEG, "-hide_banner", "-loglevel", "warning", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "pipe:0", "-an", "-c:v", "libx264", "-preset", "medium", "-crf", "17", "-pix_fmt", "yuv420p", "-movflags", "+faststart", "-metadata", "title=BAVA | Ask. Plan. Verify. Act.", str(output)]
    sample_times = [2.7, 4.25, 6.0, 8.0, 10.0, 14.5]
    samples = []
    with (ROOT / "render.log").open("w") as log:
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=log)
        for i in range(FPS * DURATION):
            im = frame(i / FPS)
            proc.stdin.write(im.tobytes())
            if i in [round(v * FPS) for v in sample_times]:
                im.save(ROOT / "frames" / f"{i / FPS:05.2f}.png")
                samples.append(im.copy())
            if i % FPS == 0:
                print(f"Rendered {i // FPS:02d}/{DURATION}s", flush=True)
        proc.stdin.close()
        if proc.wait() != 0:
            raise RuntimeError((ROOT / "render.log").read_text())
    sheet = Image.new("RGB", (1440, 810), (7, 16, 29))
    for i, im in enumerate(samples):
        sheet.paste(im.resize((480, 270), Image.Resampling.LANCZOS), ((i % 3) * 480, (i // 3) * 405))
    # Arrange the six frames with breathing room and timecode captions outside images.
    d = ImageDraw.Draw(sheet)
    for i, t in enumerate(sample_times):
        d.text(((i % 3) * 480 + 20, (i // 3) * 405 + 286), f"00:{t:05.2f}", font=font(24, 2), fill=SLATE)
    sheet.save(ROOT / "BAVA-opening-storyboard.jpg", quality=94)
    frame(2.7).save(ROOT / "BAVA-opening-cover.jpg", quality=96)
    manifest = {
        "duration_seconds": DURATION,
        "width": W,
        "height": H,
        "fps": FPS,
        "audio": False,
        "burned_in_subtitles": False,
        "source": "Actual local mock banking UI captured with browser tools, plus original code-rendered brand motion graphics.",
        "business_results_fabricated": False,
        "prompt_submitted": False,
        "shots": [[0, 3.5, "BAVA brand"], *SHOTS, [11, 15, "Real chat composer; staged typing, not submitted"]],
    }
    (ROOT / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    print(output, flush=True)


if __name__ == "__main__":
    main()
