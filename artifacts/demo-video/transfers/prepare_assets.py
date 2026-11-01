"""Assemble same-state native UI captures; never recreate financial text."""

import json
import math
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / "source"
OUT = ROOT / "prepared"
OUT.mkdir(exist_ok=True)
PHASES = ["03-yellow-payee", "04-yellow-review", "05-yellow-approved", "06-yellow-success", "09-red-review", "10-red-confirmed", "11-red-challenge", "12-red-verified", "13-red-success"]


def read(path):
    return json.loads(path.read_text())


def assemble(prefix):
    captures = []
    for meta_path in sorted(SOURCE.glob(prefix + "-*-anchors.json")):
        cards = read(meta_path)
        if not cards:
            continue
        name = meta_path.name.removesuffix("-anchors.json")
        card = cards[-1]
        image = Image.open(SOURCE / (name + ".png")).convert("RGB")
        layout_path = SOURCE / (name + "-layout.json")
        layout = read(layout_path) if layout_path.exists() else {}
        overlays = layout.get("overlays", [])
        if not overlays and "回到最新消息" in (SOURCE / (name + ".txt")).read_text():
            overlays = [{"x": 710.6, "y": 591, "width": 118.8, "height": 34}]
        captures.append((name, card, image, overlays))
    assert captures, prefix
    width = round(captures[0][1]["width"])
    height = math.ceil(captures[0][1]["height"])
    assert len({(c[1]["width"], c[1]["height"], c[1]["text"]) for c in captures}) == 1, prefix
    row = np.arange(height, dtype=np.float64) + .5
    scores, patches = [], []
    for name, card, image, overlays in captures:
        absolute_y = row + card["y"]
        score = np.minimum(absolute_y - 80, 638 - absolute_y)
        score[(absolute_y < 80) | (absolute_y >= 638)] = -1e9
        for overlay in overlays:
            # Exclude the floating message-navigation control and its shadow;
            # get those same native page rows from another recorded viewport.
            score[(absolute_y >= overlay["y"] - 8) & (absolute_y <= overlay["y"] + overlay["height"] + 8)] = -1e9
        patch = image.transform((width, height), Image.Transform.AFFINE,
                                (1, 0, card["x"], 0, 1, card["y"]), Image.Resampling.BICUBIC)
        scores.append(score)
        patches.append(np.asarray(patch))
    scores = np.stack(scores)
    best = scores.argmax(axis=0)
    coverage = scores.max(axis=0) > -1e8
    assert coverage.all(), (prefix, np.flatnonzero(~coverage).tolist())
    # Use actual, aligned pixels from a single capture on each page row. All
    # captures in this group are the exact same workflow version and state.
    result = np.empty((height, width, 3), dtype=np.uint8)
    for i, patch in enumerate(patches):
        result[best == i] = patch[best == i]
    image = Image.fromarray(result)
    image.save(OUT / (prefix + "-full.png"))
    card = captures[0][1]
    blocks = [{**b, "x": b["x"] - card["x"], "y": b["y"] - card["y"]} for b in card.get("blocks", []) if b["height"] > 0 and b["width"] > 0]
    meta = {"width": width, "height": height, "same_state_all_rows_covered": bool(coverage.all()), "source_captures": [c[0] for c in captures], "blocks": blocks, "text": card["text"], "stitch_row_changes": np.flatnonzero(np.diff(best)).tolist()}
    return image, meta


def bands(image, sections):
    patches = [image.crop((0, max(0, round(a)), image.width, min(image.height, round(b)))) for a, b in sections]
    out = Image.new("RGB", (image.width, sum(p.height for p in patches)), image.getpixel((5, 5)))
    y = 0
    for patch in patches:
        out.paste(patch, (0, y))
        y += patch.height
    return out


def main():
    assets, metadata = {}, {}
    for phase in PHASES:
        assets[phase], metadata[phase] = assemble(phase)
    # Each displayed asset preserves whole functional UI groups. Redundant
    # risk information is already shown before the success receipt; omitting
    # that repeated group lets the transaction and all ten steps stay legible.
    displays = {
        "payee-choice": bands(assets["03-yellow-payee"], [(0, 65), (433, 768)]),
        "yellow-risk": assets["04-yellow-review"].crop((0, 0, 788, 335)),
        "yellow-review": bands(assets["04-yellow-review"], [(0, 65), (703, 1061)]),
        "yellow-approved": bands(assets["05-yellow-approved"], [(0, 65), (729, 1175)]),
        "yellow-success": bands(assets["06-yellow-success"], [(0, 225), (495, 857), (881, 918)]),
        "red-risk": assets["09-red-review"].crop((0, 0, 788, 391)),
        "red-review": bands(assets["09-red-review"], [(0, 65), (759, 1117)]),
        "red-confirmed": bands(assets["10-red-confirmed"], [(0, 65), (391, 875)]),
        "red-challenge": bands(assets["11-red-challenge"], [(0, 65), (391, 905)]),
        "red-verified": bands(assets["12-red-verified"], [(0, 65), (785, 1231)]),
        "red-success": bands(assets["13-red-success"], [(0, 225), (551, 913), (937, 974)]),
    }
    # Both receipt rows that contain the reference label/value are excluded in
    # full. Native timestamps and final outcome remain in the displayed image.
    for name, image in displays.items():
        image.save(OUT / (name + ".png"))
    # A reference row can also be visible behind the second question. Remove
    # that presentation detail from the screen before adding the focus effect.
    for name in ["01-yellow-query", "07-red-query"]:
        image = Image.open(SOURCE / (name + ".png")).convert("RGB")
        for card in read(SOURCE / (name + "-anchors.json")):
            for r in card.get("redactions", []):
                left, top = max(0, math.floor(r["x"] - 2)), max(0, math.floor(r["y"] - 3))
                right, bottom = min(image.width, math.ceil(r["x"] + r["width"] + 2)), min(image.height, math.ceil(r["y"] + r["height"] + 3))
                if right > left and bottom > top:
                    color = image.getpixel((min(image.width - 1, left + 2), max(0, top - 2)))
                    ImageDraw.Draw(image).rectangle((left, top, right, bottom), fill=color)
        image.save(OUT / (name + ".png"))
    dashboard = Image.open(SOURCE / "dashboard-full.png").convert("RGB")
    dashboard_anchors = read(SOURCE / "dashboard-anchors.json")
    for key, name in [("salary", "salary-after"), ("statement", "statement-after")]:
        r = dashboard_anchors[key]
        dashboard.crop((round(r["x"]), round(r["y"]), round(r["x"] + r["width"]), round(r["y"] + r["height"]))).save(OUT / (name + ".png"))
    (OUT / "sources.json").write_text(json.dumps({"phases": metadata, "displays": {name: {"width": im.width, "height": im.height} for name, im in displays.items()}, "reference_rows_in_presented_receipts": False, "financial_ui_text_recreated": False}, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"assembled_phases": len(assets), "display_assets": {name: im.size for name, im in displays.items()}, "all_same_state_rows_covered": True}, ensure_ascii=False))


if __name__ == "__main__":
    main()
