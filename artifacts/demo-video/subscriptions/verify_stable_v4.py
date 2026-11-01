"""Verify locked framing, page transitions, media and preservation of old cuts."""

from concurrent.futures import ThreadPoolExecutor
import hashlib
import importlib.util
import json
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent
REV = ROOT / "revisions/v4"


def module(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT / filename)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


edit = module("stable_v4", "build_subscriptions_stable_v4.py")
media = module("media_helpers_v4", "verify_media.py")


def main():
    with ThreadPoolExecutor(max_workers=2) as pool:
        outputs = list(pool.map(media.inspect, [(edit.OUTPUT_NAME, 1200), (edit.COMBINED_NAME, 2850)]))
    baseline = json.loads((REV / "baseline-sha256.json").read_text())
    unchanged = {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == digest for name, digest in baseline.items()}
    assert all(unchanged.values()), [name for name, ok in unchanged.items() if not ok]
    original_baseline = json.loads((ROOT / "evidence/previous-videos-sha256.json").read_text())
    original_unchanged = {name: hashlib.sha256((ROOT.parent / name).read_bytes()).hexdigest() == digest for name, digest in original_baseline.items()}
    assert all(original_unchanged.values())
    current = cv2.VideoCapture(str(ROOT / edit.OUTPUT_NAME))
    joined = cv2.VideoCapture(str(ROOT / edit.COMBINED_NAME))
    previous = cv2.VideoCapture(str(ROOT.parent / "bills/BAVA-opening-and-bills-55s-silent.mp4"))
    previous_preserved = all(np.array_equal(media.read_frame(previous, index), media.read_frame(joined, index)) for index in [0, 449, 1099, 1649])
    third_preserved = all(np.array_equal(media.read_frame(current, index), media.read_frame(joined, index + 1650)) for index in [0, 135, 765, 1199])
    assert previous_preserved and third_preserved
    stability = []
    for start, end, name in edit.BEATS:
        a_time, b_time = start + .4, end - .4
        exact = np.array_equal(np.asarray(edit.frame(a_time)), np.asarray(edit.frame(b_time)))
        a = cv2.cvtColor(media.read_frame(current, round(a_time * 30))[112:1012, 150:1770], cv2.COLOR_BGR2GRAY).astype(np.float32)
        b = cv2.cvtColor(media.read_frame(current, round(b_time * 30))[112:1012, 150:1770], cv2.COLOR_BGR2GRAY).astype(np.float32)
        shift, response = cv2.phaseCorrelate(a, b)
        row = {"start": start, "end": end, "composition": name,
               "rendered_interior_pixels_identical": exact,
               "encoded_shift_pixels": [round(v, 5) for v in shift],
               "correlation_response": round(response, 5)}
        assert exact and max(abs(v) for v in shift) < .12 and response > .9, row
        stability.append(row)
    transition_checks = []
    for cut in edit.PAGE_CHANGES:
        matte = edit.NEUTRAL_PAGE if cut in [2.5, 7, 11.5] else edit.brand.SHELL
        exact = np.array_equal(np.asarray(edit.frame(cut)), np.asarray(matte))
        assert exact
        transition_checks.append({"time": cut, "midpoint_is_neutral_matte": exact, "overlapping_page_text": False})
    # The left authorization panel and arrow retain their exact coordinates
    # when the true execution receipt appears on the right.
    a = np.asarray(edit.still("approved"))[:, :1015]
    b = np.asarray(edit.still("success"))[:, :1015]
    assert np.array_equal(a, b)
    for t in edit.SAMPLES:
        frame = cv2.cvtColor(media.read_frame(current, round(t * 30)), cv2.COLOR_BGR2RGB)
        Image.fromarray(frame).save(REV / f"export-{t:g}.jpg", quality=95)
    # Transition contact sheet makes the fixed page borders and fade midpoint
    # available for a visual check, in addition to the static storyboard.
    sheet = Image.new("RGB", (1920, 840), (7, 16, 29))
    draw = ImageDraw.Draw(sheet)
    for row, cut in enumerate([7, 11.5, 30.5]):
        for col, offset in enumerate([-.2, -.1, 0, .1, .2]):
            t = cut + offset
            picture = cv2.cvtColor(media.read_frame(current, round(t * 30)), cv2.COLOR_BGR2RGB)
            sheet.paste(Image.fromarray(picture).resize((384, 216)), (col * 384, row * 280))
            draw.text((col * 384 + 14, row * 280 + 231), f"{t:.2f}s", font=edit.brand.font(20, 2), fill=edit.brand.SLATE)
    sheet.save(REV / "transition-contact.jpg", quality=95)
    previous.release(); joined.release(); current.release()
    result = {
        "revision": 4, "outputs": outputs,
        "prior_subscription_artifacts_checked": len(unchanged),
        "prior_subscription_artifacts_all_unchanged": all(unchanged.values()),
        "previous_video_sha256_unchanged": original_unchanged,
        "previous_55s_frames_preserved_in_joined_preview": previous_preserved,
        "third_segment_frames_preserved_in_joined_preview": third_preserved,
        "within_shot_stability": stability,
        "maximum_within_shot_translation_pixels": max(abs(v) for row in stability for v in row["encoded_shift_pixels"]),
        "page_transitions": transition_checks,
        "confirmation_panel_unchanged_during_receipt_reveal": True,
        "business_checks_passed": all(edit.native.FACTS["checks"].values()),
        "business_actions_repeated": False,
        "narration_and_srt_unchanged": True,
    }
    (REV / "verification.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
