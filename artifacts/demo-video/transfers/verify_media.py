"""Verify the encoded fourth segment, preservation, stability and UI privacy."""

from concurrent.futures import ThreadPoolExecutor
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess

import cv2
import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("transfer_edit", ROOT / "build_transfers.py")
edit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(edit)


def read_frame(cap, n):
    cap.set(cv2.CAP_PROP_POS_FRAMES, n)
    ok, picture = cap.read()
    assert ok, n
    return picture


def inspect(item):
    name, expected_frames = item
    path = ROOT / name
    cap = cv2.VideoCapture(str(path))
    assert cap.isOpened()
    result = {"file": name, "width": int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), "height": int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)), "fps": cap.get(cv2.CAP_PROP_FPS), "frames": int(cap.get(cv2.CAP_PROP_FRAME_COUNT)), "bytes": path.stat().st_size}
    cap.release()
    result["duration_seconds"] = result["frames"] / result["fps"]
    info = subprocess.run([edit.FFMPEG, "-hide_banner", "-i", str(path)], capture_output=True, text=True).stderr
    result["has_audio_stream"] = "Audio:" in info
    result["h264_yuv420p"] = "Video: h264" in info and "yuv420p" in info
    decoded = subprocess.run([edit.FFMPEG, "-hide_banner", "-v", "error", "-xerror", "-i", str(path), "-f", "null", "-"], capture_output=True, text=True)
    result["full_decode_passed"] = decoded.returncode == 0 and not decoded.stderr.strip()
    assert (result["width"], result["height"], result["fps"], result["frames"]) == (1920, 1080, 30, expected_frames), result
    assert not result["has_audio_stream"] and result["h264_yuv420p"] and result["full_decode_passed"], (result, decoded.stderr)
    return result


def main():
    with ThreadPoolExecutor(max_workers=2) as pool:
        outputs = list(pool.map(inspect, [(edit.OUTPUT_NAME, 2100), (edit.COMBINED_NAME, 4950)]))
    baseline = json.loads((ROOT / "evidence/previous-videos-sha256.json").read_text())
    unchanged = {name: hashlib.sha256((ROOT.parent / name).read_bytes()).hexdigest() == digest for name, digest in baseline.items()}
    assert all(unchanged.values())
    first = cv2.VideoCapture(str(ROOT.parent / "subscriptions/BAVA-preview-95s-stable-v8.mp4"))
    current = cv2.VideoCapture(str(ROOT / edit.OUTPUT_NAME))
    joined = cv2.VideoCapture(str(ROOT / edit.COMBINED_NAME))
    first_preserved = all(np.array_equal(read_frame(first, n), read_frame(joined, n)) for n in [0, 449, 1649, 2849])
    fourth_preserved = all(np.array_equal(read_frame(current, n), read_frame(joined, n + 2850)) for n in [0, 120, 660, 930, 1439, 2099])
    assert first_preserved and fourth_preserved
    shell = np.asarray(edit.brand.SHELL)
    stillness = []
    for start, end, name, _ in edit.SHOTS:
        a_t = start + (1.2 if name in {"yellow-query", "red-query"} else .3)
        b_t = end - .3
        a_raw, b_raw = np.asarray(edit.frame(a_t)), np.asarray(edit.frame(b_t))
        exact = np.array_equal(a_raw, b_raw)
        a = cv2.cvtColor(read_frame(current, round(a_t * 30)), cv2.COLOR_BGR2GRAY).astype(np.float32)
        b = cv2.cvtColor(read_frame(current, round(b_t * 30)), cv2.COLOR_BGR2GRAY).astype(np.float32)
        shift, response = cv2.phaseCorrelate(a, b)
        row = {"asset": name, "reading_hold_pixels_identical": exact, "encoded_translation_pixels": [round(v, 5) for v in shift], "correlation": round(response, 5)}
        assert exact and max(abs(v) for v in shift) < .12 and response > .9, row
        stillness.append(row)
    # Every distinct held design and every frame of both focus animations is
    # checked for footer clearance; other frames reuse these exact stills.
    times = sorted(set(edit.SAMPLES + [n / 30 for n in range(120)] + [27 + n / 30 for n in range(120)]))
    maximum_bottom = 0
    for t in times:
        raw = np.asarray(edit.frame(t))
        rows = np.flatnonzero(np.any(raw != shell, axis=(1, 2)))
        maximum_bottom = max(maximum_bottom, int(rows[-1]) if len(rows) else 0)
        assert np.array_equal(raw[edit.SAFE_BOTTOM + 1:], shell[edit.SAFE_BOTTOM + 1:]), t
        assert np.array_equal(raw[edit.SEPARATOR_Y], shell[edit.SEPARATOR_Y]), t
    # Positive controls show the provider reference would be detectable if the
    # original native row had been left in. Check actual exported designs,
    # including the second question's background, at the matching UI scales.
    templates = []
    controls = []
    for color, row_y in [("yellow", 861), ("red", 917)]:
        source = Image.open(ROOT / "prepared" / (("06-yellow-success" if color == "yellow" else "13-red-success") + "-full.png")).convert("RGB")
        row = source.crop((17, row_y, 771, row_y + 16))
        factor = 1064 / 788
        template = row.resize((round(row.width * factor), round(row.height * factor)), Image.Resampling.LANCZOS)
        gray = cv2.cvtColor(np.asarray(template), cv2.COLOR_RGB2GRAY)
        uncut = source.resize((1064, round(source.height * factor)), Image.Resampling.LANCZOS)
        positive = float(cv2.matchTemplate(cv2.cvtColor(np.asarray(uncut), cv2.COLOR_RGB2GRAY), gray, cv2.TM_CCOEFF_NORMED).max())
        assert positive > .75, (color, positive)
        controls.append({"transfer": color, "positive_reference_correlation": round(positive, 4)})
        for scale in [1, .885]:
            templates.append((color, scale, cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)))
    absence = []
    for t in sorted(set(edit.SAMPLES + [0, .75, 27, 27.75, 30, 63.5])):
        gray = cv2.cvtColor(read_frame(current, round(t * 30)), cv2.COLOR_BGR2GRAY)
        scores = [float(cv2.matchTemplate(gray, template, cv2.TM_CCOEFF_NORMED).max()) for _, _, template in templates]
        maximum = max(scores)
        assert maximum < .72, (t, maximum)
        absence.append({"seconds": t, "maximum_reference_correlation": round(maximum, 4)})
    for t in edit.SAMPLES:
        picture = cv2.cvtColor(read_frame(current, round(t * 30)), cv2.COLOR_BGR2RGB)
        Image.fromarray(picture).save(ROOT / "frames" / f"export-{t:g}.jpg", quality=95)
    prior_cues = json.loads((ROOT.parent / "subscriptions/narration-00-95.json").read_text())["cues"]
    cues = json.loads((ROOT / "narration-00-165.json").read_text())["cues"]
    assert cues[:len(prior_cues)] == prior_cues
    assert cues[0]["start"] == 0 and cues[-1]["end"] == 165 and all(a["end"] == b["start"] for a, b in zip(cues, cues[1:]))
    facts = json.loads((ROOT / "evidence/verification.json").read_text())
    prepared = json.loads((ROOT / "prepared/sources.json").read_text())
    assert all(facts["checks"].values()) and all(p["same_state_all_rows_covered"] for p in prepared["phases"].values())
    first.release(); current.release(); joined.release()
    result = {"part": 4, "outputs": outputs, "previous_video_sha256_unchanged": unchanged,
              "previous_95s_frames_preserved": first_preserved, "fourth_segment_preserved_in_combined": fourth_preserved,
              "reading_and_focus_holds": stillness, "maximum_artwork_or_shadow_bottom_y": maximum_bottom,
              "footer_separator_y": edit.SEPARATOR_Y, "minimum_footer_clearance_pixels": edit.SEPARATOR_Y - maximum_bottom,
              "all_distinct_holds_and_focus_frames_checked_for_clearance": True,
              "reference_detector_positive_controls": controls, "encoded_reference_absence": absence,
              "no_verification_code_in_capture_text": facts["checks"]["no_verification_code_in_ui_capture_text"],
              "same_state_card_reconstruction_complete": True, "business_checks_passed": True, "business_check_count": len(facts["checks"]),
              "previous_narration_unchanged": True, "subtitle_timeline_continuous_0_to_165": True}
    (ROOT / "verification.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
