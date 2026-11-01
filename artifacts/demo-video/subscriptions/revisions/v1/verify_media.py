"""Check exported media, caption timing and preservation of earlier segments."""

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
spec = importlib.util.spec_from_file_location("bava_opening", ROOT.parent / "opening/build_opening.py")
brand = importlib.util.module_from_spec(spec)
spec.loader.exec_module(brand)
FFMPEG = brand.FFMPEG


def inspect(item):
    name, expected_frames = item
    path = ROOT / name
    cap = cv2.VideoCapture(str(path))
    assert cap.isOpened(), name
    result = {
        "file": name,
        "width": int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)),
        "height": int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)),
        "fps": cap.get(cv2.CAP_PROP_FPS),
        "frames": int(cap.get(cv2.CAP_PROP_FRAME_COUNT)),
        "bytes": path.stat().st_size,
    }
    cap.release()
    result["duration_seconds"] = result["frames"] / result["fps"]
    info = subprocess.run([FFMPEG, "-hide_banner", "-i", str(path)], capture_output=True, text=True).stderr
    result["has_audio_stream"] = "Audio:" in info
    result["h264"] = "Video: h264" in info
    result["pixel_format_yuv420p"] = "yuv420p" in info
    decoded = subprocess.run([FFMPEG, "-hide_banner", "-v", "error", "-xerror", "-i", str(path), "-f", "null", "-"], capture_output=True, text=True)
    result["full_decode_passed"] = decoded.returncode == 0 and not decoded.stderr.strip()
    assert (result["width"], result["height"], result["fps"], result["frames"]) == (1920, 1080, 30, expected_frames), result
    assert not result["has_audio_stream"] and result["h264"] and result["pixel_format_yuv420p"] and result["full_decode_passed"], (result, decoded.stderr)
    return result


def read_frame(cap, index):
    cap.set(cv2.CAP_PROP_POS_FRAMES, index)
    ok, frame = cap.read()
    assert ok, index
    return frame


def main():
    outputs = [("BAVA-subscriptions-40s-silent.mp4", 1200), ("BAVA-preview-95s-silent.mp4", 2850)]
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(inspect, outputs))
    baseline = json.loads((ROOT / "evidence/previous-videos-sha256.json").read_text())
    originals = {name: hashlib.sha256((ROOT.parent / name).read_bytes()).hexdigest() == sha for name, sha in baseline.items()}
    assert all(originals.values()), originals
    previous = cv2.VideoCapture(str(ROOT.parent / "bills/BAVA-opening-and-bills-55s-silent.mp4"))
    current = cv2.VideoCapture(str(ROOT / outputs[0][0]))
    joined = cv2.VideoCapture(str(ROOT / outputs[1][0]))
    preserved_before = all(np.array_equal(read_frame(previous, n), read_frame(joined, n)) for n in [0, 449, 1099, 1649])
    preserved_after = all(np.array_equal(read_frame(current, n), read_frame(joined, n + 1650)) for n in [0, 135, 765, 1199])
    assert preserved_before and preserved_after
    for t in [1.5, 4.5, 8.5, 12, 15.5, 18.5, 21.5, 25.5, 29, 33, 36, 39]:
        im = cv2.cvtColor(read_frame(current, round(t * 30)), cv2.COLOR_BGR2RGB)
        Image.fromarray(im).save(ROOT / "frames" / f"export-{t:g}.jpg", quality=95)
    previous.release(); current.release(); joined.release()
    facts = json.loads((ROOT / "evidence/verification.json").read_text())
    cues = json.loads((ROOT / "narration-00-95.json").read_text())["cues"]
    first = json.loads((ROOT.parent / "bills/narration-00-55.json").read_text())["cues"]
    assert cues[:len(first)] == first
    assert cues[0]["start"] == 0 and cues[-1]["end"] == 95
    assert all(a["end"] == b["start"] for a, b in zip(cues, cues[1:]))
    result = {
        "outputs": results,
        "previous_video_sha256_unchanged": originals,
        "previous_55s_frames_preserved_in_joined_preview": preserved_before,
        "third_segment_frames_preserved_in_joined_preview": preserved_after,
        "previous_narration_unchanged": True,
        "caption_timeline_continuous_0_to_95": True,
        "business_evidence_passed": all(facts["checks"].values()),
        "business_check_count": len(facts["checks"]),
    }
    assert result["business_evidence_passed"]
    (ROOT / "verification.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
