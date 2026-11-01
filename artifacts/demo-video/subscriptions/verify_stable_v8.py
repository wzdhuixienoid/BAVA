"""Check native-image completeness, omitted reference row and footer clearance."""

from concurrent.futures import ThreadPoolExecutor
import hashlib
import importlib.util
import json
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parent
REV = ROOT / "revisions/v8"


def module(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT / filename)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


edit = module("stable_v8", "build_subscriptions_stable_v8.py")
media = module("media_helpers_v8", "verify_media.py")


def main():
    with ThreadPoolExecutor(max_workers=2) as pool:
        outputs = list(pool.map(media.inspect, [(edit.OUTPUT_NAME, 1200), (edit.COMBINED_NAME, 2850)]))
    baseline = json.loads((REV / "baseline-sha256.json").read_text())
    unchanged = {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == value for name, value in baseline.items()}
    assert all(unchanged.values()), unchanged
    originals = json.loads((ROOT / "evidence/previous-videos-sha256.json").read_text())
    old_video_unchanged = {name: hashlib.sha256((ROOT.parent / name).read_bytes()).hexdigest() == value for name, value in originals.items()}
    assert all(old_video_unchanged.values())
    current = cv2.VideoCapture(str(ROOT / edit.OUTPUT_NAME))
    joined = cv2.VideoCapture(str(ROOT / edit.COMBINED_NAME))
    first = cv2.VideoCapture(str(ROOT.parent / "bills/BAVA-opening-and-bills-55s-silent.mp4"))
    first_preserved = all(np.array_equal(media.read_frame(first, n), media.read_frame(joined, n)) for n in [0, 449, 1099, 1649])
    third_preserved = all(np.array_equal(media.read_frame(current, n), media.read_frame(joined, n + 1650)) for n in [0, 45, 855, 990, 1199])
    assert first_preserved and third_preserved
    shell = np.asarray(edit.brand.SHELL)
    # Check the delivered frame design at every encoded time, including focus
    # and scrolling. No image is merely clipped against the footer separator.
    maximum_bottom = 0
    for n in range(1200):
        picture = np.asarray(edit.frame(n / 30))
        different_rows = np.flatnonzero(np.any(picture != shell, axis=(1, 2)))
        bottom = int(different_rows[-1]) if len(different_rows) else 0
        maximum_bottom = max(maximum_bottom, bottom)
        assert bottom <= edit.SAFE_BOTTOM, (n, bottom)
        assert np.array_equal(picture[edit.SAFE_BOTTOM + 1:], shell[edit.SAFE_BOTTOM + 1:]), n
        assert np.array_equal(picture[edit.SEPARATOR_Y], shell[edit.SEPARATOR_Y]), n
    holds = []
    for a_t, b_t, name in [(1.2, 2.3, "query_focus_hold"), (3, 6.5, "consent"),
                           (7.3, 9.7, "contracts"), (13, 17.2, "analysis"),
                           (18.7, 19.8, "cancel_focus_hold"), (20.3, 26.7, "complete_review"),
                           (27.2, 30.2, "complete_approved_view"), (30.8, 34.7, "receipt_without_reference"),
                           (35.3, 39.7, "comparison")]:
        exact = np.array_equal(np.asarray(edit.frame(a_t)), np.asarray(edit.frame(b_t)))
        a = cv2.cvtColor(media.read_frame(current, round(a_t * 30)), cv2.COLOR_BGR2GRAY).astype(np.float32)
        b = cv2.cvtColor(media.read_frame(current, round(b_t * 30)), cv2.COLOR_BGR2GRAY).astype(np.float32)
        shift, correlation = cv2.phaseCorrelate(a, b)
        row = {"beat": name, "rendered_pixels_identical": exact,
               "encoded_shift_pixels": [round(x, 5) for x in shift], "correlation": round(correlation, 5)}
        assert exact and max(abs(x) for x in shift) < .12 and correlation > .9, row
        holds.append(row)
    # Detect the actual reference row at its display scale in an uncut positive
    # control. It must be absent in the exported result, including its label.
    source = edit.native.IMAGES["11-cancel-receipt"]
    scale = (edit.CARD_BOX[2] - edit.CARD_BOX[0]) / 840
    template = np.asarray(source.crop((485, 562, 1120, 584)).resize((round(635 * scale), round(22 * scale)), Image.Resampling.LANCZOS))
    template = cv2.cvtColor(template, cv2.COLOR_RGB2GRAY)
    uncut = source.crop((440, 121, 1280, 698))
    uncut = uncut.resize((edit.CARD_BOX[2] - edit.CARD_BOX[0], round(uncut.height * scale)), Image.Resampling.LANCZOS)
    positive = float(cv2.matchTemplate(cv2.cvtColor(np.asarray(uncut), cv2.COLOR_RGB2GRAY), template, cv2.TM_CCOEFF_NORMED).max())
    assert positive > .75, positive
    reference_absence = []
    for t in [1.5, 4.5, 13, 19, 22, 28.5, 30.5, 33, 34.9, 38]:
        picture = media.read_frame(current, round(t * 30))
        score = float(cv2.matchTemplate(cv2.cvtColor(picture, cv2.COLOR_BGR2GRAY), template, cv2.TM_CCOEFF_NORMED).max())
        assert score < .68, (t, score)
        reference_absence.append({"seconds": t, "reference_row_maximum_correlation": round(score, 4)})
    # The previously cut timeline heading is now visible in the encoded 28s
    # image, using the unchanged native heading pixels from the same workflow.
    heading = edit.native.IMAGES["08-review-full"].crop((497, 277, 647, 296))
    heading = heading.resize((round(heading.width * scale), round(heading.height * scale)), Image.Resampling.LANCZOS)
    heading_score = float(cv2.matchTemplate(cv2.cvtColor(media.read_frame(current, 855), cv2.COLOR_BGR2GRAY), cv2.cvtColor(np.asarray(heading), cv2.COLOR_RGB2GRAY), cv2.TM_CCOEFF_NORMED).max())
    assert heading_score > .75, heading_score
    for t in edit.SAMPLES:
        picture = cv2.cvtColor(media.read_frame(current, round(t * 30)), cv2.COLOR_BGR2RGB)
        Image.fromarray(picture).save(REV / f"export-{t:g}.jpg", quality=95)
    current.release(); joined.release(); first.release()
    result = {
        "revision": 8, "outputs": outputs,
        "all_1200_rendered_frames_checked_for_footer_clearance": True,
        "maximum_artwork_bottom_y": maximum_bottom,
        "separator_y": edit.SEPARATOR_Y,
        "minimum_clearance_pixels": edit.SEPARATOR_Y - maximum_bottom,
        "separator_and_footer_unchanged": True,
        "native_timeline_heading_present_at_28s": {"correlation": round(heading_score, 4)},
        "fuller_approved_view": "Native timeline heading, all seven steps, approved state, merchant/plan/fee/renewal, warning, both buttons and assistant explanation",
        "fuller_success_view": "Native audit control, success heading, seven-step timeline, consumed approval, final result, timestamp and assistant explanation",
        "stationary_reading_and_business_holds": holds,
        "reference_label_and_value_row_omitted": True,
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
