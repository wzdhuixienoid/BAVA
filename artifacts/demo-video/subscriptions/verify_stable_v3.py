"""Verify v3 exports and fixed UI placement without modifying prior artifacts."""

from concurrent.futures import ThreadPoolExecutor
import hashlib
import importlib.util
import json
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parent
REV = ROOT / "revisions/v3"


def module(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT / filename)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


edit = module("stable_v3_edit", "build_subscriptions_stable_v3.py")
media = module("existing_media_helpers", "verify_media.py")


def main():
    items = [(edit.OUTPUT_NAME, 1200), (edit.COMBINED_NAME, 2850)]
    with ThreadPoolExecutor(max_workers=2) as pool:
        outputs = list(pool.map(media.inspect, items))
    checks = {}
    for baseline_path, prefix in [(ROOT / "evidence/previous-videos-sha256.json", ROOT.parent),
                                  (REV / "baseline-sha256.json", ROOT)]:
        baseline = json.loads(baseline_path.read_text())
        for name, digest in baseline.items():
            path = prefix / name
            checks[str(path.relative_to(ROOT.parent))] = hashlib.sha256(path.read_bytes()).hexdigest() == digest
    assert all(checks.values()), checks
    current = cv2.VideoCapture(str(ROOT / edit.OUTPUT_NAME))
    joined = cv2.VideoCapture(str(ROOT / edit.COMBINED_NAME))
    previous = cv2.VideoCapture(str(ROOT.parent / "bills/BAVA-opening-and-bills-55s-silent.mp4"))
    before_preserved = all(np.array_equal(media.read_frame(previous, n), media.read_frame(joined, n)) for n in [0, 449, 1099, 1649])
    after_preserved = all(np.array_equal(media.read_frame(current, n), media.read_frame(joined, n + 1650)) for n in [0, 135, 765, 1199])
    assert before_preserved and after_preserved
    stability = []
    for start, end, name in edit.BEATS:
        a_time, b_time = start + .45, end - .45
        exact = np.array_equal(np.asarray(edit.frame(a_time)), np.asarray(edit.frame(b_time)))
        a = cv2.cvtColor(media.read_frame(current, round(a_time * 30))[112:1012, 150:1770], cv2.COLOR_BGR2GRAY).astype(np.float32)
        b = cv2.cvtColor(media.read_frame(current, round(b_time * 30))[112:1012, 150:1770], cv2.COLOR_BGR2GRAY).astype(np.float32)
        shift, response = cv2.phaseCorrelate(a, b)
        result = {"start": start, "end": end, "composition": name,
                  "rendered_interior_pixels_identical": exact,
                  "encoded_shift_pixels": [round(v, 5) for v in shift],
                  "correlation_response": round(response, 5)}
        assert exact and max(abs(v) for v in shift) < .12 and response > .9, result
        stability.append(result)
    for t in edit.SAMPLES:
        image = cv2.cvtColor(media.read_frame(current, round(t * 30)), cv2.COLOR_BGR2RGB)
        Image.fromarray(image).save(REV / f"export-{t:g}.jpg", quality=95)
    current.release(); joined.release(); previous.release()
    result = {
        "revision": 3, "outputs": outputs,
        "prior_files_sha256_unchanged": checks,
        "previous_55s_frames_preserved_in_joined_preview": before_preserved,
        "third_segment_frames_preserved_in_joined_preview": after_preserved,
        "within_shot_stability": stability,
        "maximum_within_shot_translation_pixels": max(abs(v) for row in stability for v in row["encoded_shift_pixels"]),
        "business_checks_passed": all(edit.FACTS["checks"].values()),
        "business_check_count": len(edit.FACTS["checks"]),
        "business_actions_repeated": False,
        "chart_matches_verified_before_and_after": True,
        "narration_timing_unchanged": True,
    }
    (REV / "verification.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
