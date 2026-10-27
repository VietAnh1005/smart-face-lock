"""Thu ảnh và đo FAR/FRR offline.

    python -m tools.measure_far_frr capture "Ten Nguoi"   # chụp 20 ảnh vào dataset/Ten Nguoi/
    python -m tools.measure_far_frr measure               # so mọi cặp ảnh trong dataset/

FAR (nhận nhầm) = tỉ lệ cặp KHÁC người có khoảng cách < ngưỡng.
FRR (từ chối nhầm) = tỉ lệ cặp CÙNG người có khoảng cách >= ngưỡng.

    python -m tools.measure_far_frr capture-session "Ten"  # 12 giây: nháy mắt, quay đầu, há miệng
    python -m tools.measure_far_frr measure-session        # khoảng cách theo phiên tới ảnh trong dataset/

Theo phiên: mỗi vector của một phiên so với ảnh đăng ký (dataset/<tên>/) của cùng người và của người khác.
Ngưỡng MATCH_THRESHOLD / SESSION_MATCH_RATIO tốt phải nằm trong khoảng trống giữa hai nhóm.
"""
import itertools
import sys
import time

import cv2
import numpy as np

from config import settings
from core.camera_stream import CameraStream
from core.face_detector import FaceDetector
from core.face_encoder import encode_face
from core.face_matcher import distance_to
from core.face_types import largest

DATASET = settings.BASE_DIR / "dataset"
THRESHOLDS = (0.40, 0.45, 0.50, 0.55, 0.60)


def capture(name: str, count: int = 20) -> None:
    folder = DATASET / name
    folder.mkdir(parents=True, exist_ok=True)
    detector, saved = FaceDetector(), 0
    with CameraStream() as cam:
        while saved < count:
            frame = cam.read_frame()
            if frame is None or len(detector.detect(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))) != 1:
                continue
            ok, jpg = cv2.imencode(".jpg", frame)  # imwrite không ghi được đường dẫn có dấu trên Windows
            if not ok:
                continue
            (folder / f"{saved:02d}.jpg").write_bytes(jpg.tobytes())
            saved += 1
            print(f"Đã chụp {saved}/{count} — đổi nhẹ tư thế, biểu cảm")
            time.sleep(0.5)


def measure() -> None:
    encodings = [(name, enc) for name, encs in _load_templates().items() for enc in encs]
    genuine, impostor = [], []
    for (p1, e1), (p2, e2) in itertools.combinations(encodings, 2):
        (genuine if p1 == p2 else impostor).append(float(np.linalg.norm(e1 - e2)))
    print(f"{len(encodings)} ảnh, {len(genuine)} cặp cùng người, {len(impostor)} cặp khác người")
    if not genuine or not impostor:
        print("Cần ít nhất 2 người, mỗi người ít nhất 2 ảnh.")
        return
    genuine, impostor = np.array(genuine), np.array(impostor)
    print("Ngưỡng |   FAR    |   FRR")
    for t in THRESHOLDS:
        print(f" {t:.2f}  | {np.mean(impostor < t):7.3%} | {np.mean(genuine >= t):7.3%}")



SESSIONS = settings.BASE_DIR / "dataset_sessions"


def _load_templates() -> dict[str, list[np.ndarray]]:
    detector, templates = FaceDetector(), {}
    for person in sorted(p for p in DATASET.iterdir() if p.is_dir()):
        for image_path in sorted(person.glob("*.jpg")):
            bgr = cv2.imdecode(np.fromfile(image_path, np.uint8), cv2.IMREAD_COLOR)
            if bgr is None:  # file hỏng / không phải ảnh
                print(f"Bỏ qua {image_path}: không đọc được ảnh")
                continue
            rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
            boxes = detector.detect(rgb)
            if len(boxes) == 1:
                templates.setdefault(person.name, []).append(encode_face(rgb, boxes[0]))
    return templates


def capture_session(name: str, seconds: float = 12) -> None:
    """Thu vector liên tục như lúc mở cửa thật (có quay đầu), lưu dataset_sessions/<tên>.npy."""
    detector, encodings = FaceDetector(), []
    print(f"Trong {seconds:.0f} giây: nháy mắt, quay đầu trái/phải, há miệng, rồi nhìn thẳng.")
    end = time.monotonic() + seconds
    with CameraStream() as cam:
        while time.monotonic() < end:
            frame = cam.read_frame()
            if frame is None:
                continue
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            boxes = detector.detect(rgb)
            if boxes:
                encodings.append(encode_face(rgb, largest(boxes)))
    SESSIONS.mkdir(exist_ok=True)
    np.save(SESSIONS / f"{name}.npy", np.array(encodings))
    print(f"Đã lưu {len(encodings)} vector.")


def session_report(sessions: dict[str, np.ndarray],
                   templates: dict[str, list[np.ndarray]]) -> tuple[np.ndarray, np.ndarray]:
    genuine, impostor = [], []
    for name, encodings in sessions.items():
        for enc in encodings:
            for person, encs in templates.items():
                (genuine if person == name else impostor).append(distance_to(enc, encs))
    return np.array(genuine), np.array(impostor)


def measure_session() -> None:
    templates = _load_templates()
    sessions = {p.stem: np.load(p) for p in sorted(SESSIONS.glob("*.npy"))}
    genuine, impostor = session_report(sessions, templates)
    if not len(genuine) or not len(impostor):
        print("Cần ảnh đăng ký của ≥ 2 người (capture) và ≥ 1 phiên (capture-session).")
        return
    print(f"Cùng người: {len(genuine)} vector, max {genuine.max():.3f}, p95 {np.percentile(genuine, 95):.3f}")
    print(f"Khác người: {len(impostor)} vector, min {impostor.min():.3f}, p5 {np.percentile(impostor, 5):.3f}")
    print("Ngưỡng | % vector cùng người khớp (cần ≥ SESSION_MATCH_RATIO) | % vector khác người khớp")
    for t in THRESHOLDS:
        print(f" {t:.2f}  | {np.mean(genuine < t):7.1%} | {np.mean(impostor < t):7.1%}")
    out = SESSIONS / "distances.csv"
    out.write_text("kind,distance\n" + "".join(f"genuine,{d:.4f}\n" for d in genuine)
                   + "".join(f"impostor,{d:.4f}\n" for d in impostor), encoding="utf-8")
    print(f"Đã ghi {out} (vẽ hai phân bố cạnh nhau để so sánh).")

if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "capture":
        capture(sys.argv[2])
    elif len(sys.argv) == 2 and sys.argv[1] == "measure":
        measure()
    elif len(sys.argv) == 3 and sys.argv[1] == "capture-session":
        capture_session(sys.argv[2])
    elif len(sys.argv) == 2 and sys.argv[1] == "measure-session":
        measure_session()
    else:
        print(__doc__)
