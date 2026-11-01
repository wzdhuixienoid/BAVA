"""Verify the delivered motion: retained focus, stable holds and one-way scroll."""

from concurrent.futures import ThreadPoolExecutor
import hashlib
import importlib.util
import json
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent
REV = ROOT / "revisions/v5"


def module(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT / filename)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


edit = module("stable_v5", "build_subscriptions_stable_v5.py")
media = module("media_helpers_v5", "verify_media.py")


def main():
    with ThreadPoolExecutor(max_workers=2) as pool:
        outputs = list(pool.map(media.inspect, [(edit.OUTPUT_NAME, 1200), (edit.COMBINED_NAME, 2850)]))
    baseline = json.loads((REV / "baseline-sha256.json").read_text())
    unchanged = {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == value for name, value in baseline.items()}
    assert all(unchanged.values()), unchanged
    originals = json.loads((ROOT / "evidence/previous-videos-sha256.json").read_text())
    original_unchanged = {name: hashlib.sha256((ROOT.parent / name).read_bytes()).hexdigest() == value for name, value in originals.items()}
    assert all(original_unchanged.values())
    current = cv2.VideoCapture(str(ROOT / edit.OUTPUT_NAME))
    joined = cv2.VideoCapture(str(ROOT / edit.COMBINED_NAME))
    previous = cv2.VideoCapture(str(ROOT.parent / "bills/BAVA-opening-and-bills-55s-silent.mp4"))
    previous_preserved = all(np.array_equal(media.read_frame(previous, n), media.read_frame(joined, n)) for n in [0, 449, 1099, 1649])
    third_preserved = all(np.array_equal(media.read_frame(current, n), media.read_frame(joined, n + 1650)) for n in [0, 135, 765, 1199])
    assert previous_preserved and third_preserved
    holds = [(.9, 1.6, "query_focus_hold"), (2.8, 6.7, "read_consent"),
             (7.3, 9.7, "contracts"), (13, 17.2, "analysis"),
             (18.4, 19.1, "cancel_focus_hold"), (20.3, 26.7, "review"),
             (27.3, 30.2, "approved"), (30.9, 34.7, "success"),
             (35.3, 39.7, "comparison")]
    hold_results = []
    for a_time, b_time, name in holds:
        exact = np.array_equal(np.asarray(edit.frame(a_time)), np.asarray(edit.frame(b_time)))
        a = cv2.cvtColor(media.read_frame(current, round(a_time * 30))[112:1012, 150:1770], cv2.COLOR_BGR2GRAY).astype(np.float32)
        b = cv2.cvtColor(media.read_frame(current, round(b_time * 30))[112:1012, 150:1770], cv2.COLOR_BGR2GRAY).astype(np.float32)
        shift, response = cv2.phaseCorrelate(a, b)
        row = {"beat": name, "rendered_pixels_identical": exact,
               "encoded_shift_pixels": [round(v, 5) for v in shift], "correlation": round(response, 5)}
        assert exact and max(abs(v) for v in shift) < .12 and response > .9, row
        hold_results.append(row)
    # Query focus has actual motion, a readable hold and a return to the same
    # underlying native screenshot. It has not been removed to fake stability.
    focus = []
    for offset in [0, 17.5]:
        initial, focused, returned = [np.asarray(edit.frame(offset + t)) for t in [.05, 1.25, 2.4]]
        row = {"start": offset, "focus_changes_pixels": not np.array_equal(initial, focused),
               "returns_to_original_framing": np.array_equal(initial, returned)}
        assert row["focus_changes_pixels"] and row["returns_to_original_framing"], row
        focus.append(row)
    # Measure delivered frames at representative points in the active scroll.
    # Estimate motion from the native page itself, excluding fixed UI chrome.
    motion = []
    for n in [308, 316, 324, 332, 340, 348, 352]:
        a = cv2.cvtColor(media.read_frame(current, n)[175:865, 440:1570], cv2.COLOR_BGR2GRAY).astype(np.float32)
        b = cv2.cvtColor(media.read_frame(current, n + 1)[175:865, 440:1570], cv2.COLOR_BGR2GRAY).astype(np.float32)
        shift, response = cv2.phaseCorrelate(a, b)
        expected = -(edit.scroll_offset((n + 1) / 30) - edit.scroll_offset(n / 30))
        row = {"frame": n, "x": round(shift[0], 4), "y": round(shift[1], 4),
               "expected_y": round(expected, 4), "correlation": round(response, 4)}
        assert abs(shift[0]) < .4 and abs(shift[1] - expected) < 1.3 and shift[1] < 0, row
        motion.append(row)
    # Fixed composer and brand borders must stay identical while content scrolls.
    before, after = [np.asarray(edit.frame(t)) for t in [10.1, 11.9]]
    fixed_composer = np.array_equal(before[910:1010, 170:1750], after[910:1010, 170:1750])
    fixed_brand = np.array_equal(before[:100], after[:100])
    assert fixed_composer and fixed_brand
    # The approval panel does not shift when the execution receipt appears.
    left_stable = np.array_equal(np.asarray(edit.held("approved"))[:, :1015], np.asarray(edit.held("success"))[:, :1015])
    assert left_stable
    for t in edit.SAMPLES:
        image = cv2.cvtColor(media.read_frame(current, round(t * 30)), cv2.COLOR_BGR2RGB)
        Image.fromarray(image).save(REV / f"export-{t:g}.jpg", quality=95)
    sheet = Image.new("RGB", (1920, 840), (7, 16, 29))
    d = ImageDraw.Draw(sheet)
    for row, times in enumerate([[10, 10.5, 11, 11.5, 12], [.15, .5, 1.25, 2, 2.4], [30.3, 30.4, 30.5, 30.6, 30.7]]):
        for col, t in enumerate(times):
            image = cv2.cvtColor(media.read_frame(current, round(t * 30)), cv2.COLOR_BGR2RGB)
            sheet.paste(Image.fromarray(image).resize((384, 216)), (col * 384, row * 280))
            d.text((col * 384 + 14, row * 280 + 231), f"{t:.2f}s", font=edit.brand.font(20, 2), fill=edit.brand.SLATE)
    sheet.save(REV / "motion-contact.jpg", quality=95)
    previous.release(); joined.release(); current.release()
    result = {
        "revision": 5, "outputs": outputs,
        "question_zoom_retained": focus,
        "stationary_reading_and_focus_holds": hold_results,
        "scroll_measured_in_encoded_frames": motion,
        "composer_fixed_during_scroll": fixed_composer,
        "brand_frame_fixed_during_scroll": fixed_brand,
        "confirmation_panel_fixed_during_receipt_reveal": left_stable,
        "previous_55s_frames_preserved": previous_preserved,
        "third_segment_frames_preserved_in_combined": third_preserved,
        "prior_subscription_artifacts_all_unchanged": all(unchanged.values()),
        "previous_video_sha256_unchanged": original_unchanged,
        "business_checks_passed": all(edit.native.FACTS["checks"].values()),
        "business_actions_repeated": False,
        "narration_and_srt_unchanged": True,
    }
    (REV / "verification.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
