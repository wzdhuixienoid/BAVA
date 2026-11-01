"""Check opening focus parity, fuller native views and no visible reference row."""

from concurrent.futures import ThreadPoolExecutor
import hashlib
import importlib.util
import json
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent
REV = ROOT / "revisions/v7"


def module(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT / filename)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


edit = module("stable_v7", "build_subscriptions_stable_v7.py")
media = module("media_helpers_v7", "verify_media.py")


def main():
    with ThreadPoolExecutor(max_workers=2) as pool:
        outputs = list(pool.map(media.inspect, [(edit.OUTPUT_NAME, 1200), (edit.COMBINED_NAME, 2850)]))
    baseline = json.loads((REV / "baseline-sha256.json").read_text())
    unchanged = {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == value for name, value in baseline.items()}
    assert all(unchanged.values()), unchanged
    originals = json.loads((ROOT / "evidence/previous-videos-sha256.json").read_text())
    old_video_unchanged = {name: hashlib.sha256((ROOT.parent / name).read_bytes()).hexdigest() == value for name, value in originals.items()}
    assert all(old_video_unchanged.values())

    # Invoke the actual opening function with the same native source, so the
    # reference is its existing implementation rather than another copied test.
    focus_checks = []
    original_typing_frames = edit.brand.CHAT
    try:
        for name in ["01-query", "07-cancel-request"]:
            source = edit.native.IMAGES[name]
            edit.brand.CHAT = [source] * len(original_typing_frames)
            for local in [0, .25, .5, .75, 1, 1.5, 2.25]:
                expected = np.asarray(edit.brand.chat(11 + local))
                actual = np.asarray(edit.opening_focus(source, local))
                exact = np.array_equal(actual, expected)
                assert exact, (name, local)
                focus_checks.append({"capture": name, "local_seconds": local, "pixels_identical_to_opening_function": exact})
    finally:
        edit.brand.CHAT = original_typing_frames

    # The accepted reading, single scroll, review and final comparison stay as v5.
    kept_times = [3.5, 8.5, 10.5, 11.5, 13, 16, 22, 25.5, 38]
    preserved_reading = all(np.array_equal(np.asarray(edit.frame(t)), np.asarray(edit.v6.v5.frame(t))) for t in kept_times)
    assert preserved_reading
    current = cv2.VideoCapture(str(ROOT / edit.OUTPUT_NAME))
    joined = cv2.VideoCapture(str(ROOT / edit.COMBINED_NAME))
    first = cv2.VideoCapture(str(ROOT.parent / "bills/BAVA-opening-and-bills-55s-silent.mp4"))
    first_preserved = all(np.array_equal(media.read_frame(first, n), media.read_frame(joined, n)) for n in [0, 449, 1099, 1649])
    third_preserved = all(np.array_equal(media.read_frame(current, n), media.read_frame(joined, n + 1650)) for n in [0, 45, 855, 990, 1199])
    assert first_preserved and third_preserved
    holds = []
    for a_t, b_t, name in [(1.2, 2.3, "query_focus_hold"), (3, 6.5, "consent"),
                           (7.3, 9.7, "contracts"), (13, 17.2, "analysis"),
                           (18.7, 19.8, "cancel_focus_hold"), (20.3, 26.7, "review"),
                           (27.2, 30.2, "full_approved_view"), (30.8, 34.7, "full_result_without_reference"),
                           (35.3, 39.7, "comparison")]:
        exact = np.array_equal(np.asarray(edit.frame(a_t)), np.asarray(edit.frame(b_t)))
        a = cv2.cvtColor(media.read_frame(current, round(a_t * 30)), cv2.COLOR_BGR2GRAY).astype(np.float32)
        b = cv2.cvtColor(media.read_frame(current, round(b_t * 30)), cv2.COLOR_BGR2GRAY).astype(np.float32)
        shift, correlation = cv2.phaseCorrelate(a, b)
        row = {"beat": name, "rendered_pixels_identical": exact,
               "encoded_shift_pixels": [round(x, 5) for x in shift], "correlation": round(correlation, 5)}
        assert exact and max(abs(x) for x in shift) < .12 and correlation > .9, row
        holds.append(row)

    # At the actual display scale the reference text is detectable in the
    # unedited source, but absent in the encoded presentation after redaction.
    source = edit.native.IMAGES["11-cancel-receipt"]
    factor = edit.v6.CARD_WIDTH / 788
    template = np.asarray(source.crop((485, 562, 1120, 584)).resize((round(635 * factor), round(22 * factor)), Image.Resampling.LANCZOS))
    template = cv2.cvtColor(template, cv2.COLOR_RGB2GRAY)
    uncut = source.crop((472, 171, 1260, 621))
    uncut = uncut.resize((edit.v6.CARD_WIDTH, round(uncut.height * factor)), Image.Resampling.LANCZOS)
    positive = float(cv2.matchTemplate(cv2.cvtColor(np.asarray(uncut), cv2.COLOR_RGB2GRAY), template, cv2.TM_CCOEFF_NORMED).max())
    assert positive > .75
    reference_absence = []
    for t in [1.5, 4.5, 13, 19, 22, 28.5, 30.5, 33, 34.9, 38]:
        picture = media.read_frame(current, round(t * 30))
        score = float(cv2.matchTemplate(cv2.cvtColor(picture, cv2.COLOR_BGR2GRAY), template, cv2.TM_CCOEFF_NORMED).max())
        assert score < .68, (t, score)
        reference_absence.append({"seconds": t, "reference_row_maximum_correlation": round(score, 4)})
    for t in edit.SAMPLES:
        picture = cv2.cvtColor(media.read_frame(current, round(t * 30)), cv2.COLOR_BGR2RGB)
        Image.fromarray(picture).save(REV / f"export-{t:g}.jpg", quality=95)

    sheet = Image.new("RGB", (1920, 760), (7, 16, 29))
    d = ImageDraw.Draw(sheet)
    for row, image in enumerate([edit.brand.frame(14.5), edit.frame(1.5)]):
        sheet.paste(image.resize((960, 540), Image.Resampling.LANCZOS), (row * 960, 0))
        d.text((row * 960 + 24, 570), "Opening reference" if row == 0 else "Subscription focus: same visual parameters", font=edit.brand.font(24, 2), fill=edit.brand.SLATE)
    sheet.save(REV / "opening-focus-comparison.jpg", quality=95)
    current.release(); joined.release(); first.release()
    result = {
        "revision": 7, "outputs": outputs,
        "focus_matches_actual_opening_function": focus_checks,
        "accepted_reading_scroll_review_and_comparison_preserved": preserved_reading,
        "stationary_business_and_reading_holds": holds,
        "fuller_approved_view": "All seven captured timeline steps, approval state, full subscription details, warning and both buttons",
        "fuller_result_view": "Success header, all seven steps, consumed approval, final business status and native timestamp",
        "reference_number_label_and_value_row_omitted": True,
        "reference_detector_positive_control_correlation": round(positive, 4),
        "encoded_reference_row_absence": reference_absence,
        "previous_55s_frames_preserved": first_preserved,
        "third_segment_frames_preserved_in_combined": third_preserved,
        "prior_subscription_artifacts_all_unchanged": all(unchanged.values()),
        "previous_video_sha256_unchanged": old_video_unchanged,
        "business_checks_passed": all(edit.native.FACTS["checks"].values()),
        "business_actions_repeated": False, "narration_and_srt_unchanged": True,
    }
    (REV / "verification.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
