"""Đọc camera trong một thread, xử lý ảnh trong HAI TIẾN TRÌNH riêng.

dlib giữ GIL của Python suốt lúc tính (tạo vector ~400 ms), nên nếu xử lý chạy bằng thread
thì giao diện và việc đọc camera đều bị đứng theo. Tách sang process riêng thì:
- Thread đọc (trong process chính) luôn giữ frame mới nhất → video mượt theo tốc độ camera,
  bộ đệm camera không dồn frame cũ.
- Process phân tích: tìm mặt + landmark mọi frame (~20 frame/s), trả FrameResult về.
- Process tạo vector: nhận frame từ process phân tích khi rảnh, trả vector về để gắn vào kết quả.
  Frame nào không kịp xử lý thì bỏ qua.
Tkinter không an toàn khi gọi từ thread khác, nên thread đọc không chạm vào widget hay DB.
"""
import multiprocessing as mp
import queue
import threading
import traceback

import cv2
import numpy as np

from config import settings
from core.camera_stream import CameraError, CameraStream
from core.face_types import largest
from core.image_quality import brightness, brightness_ok, is_sharp
from services.frame_result import FrameResult


MAX_ANALYSIS_ERRORS = 10  # số frame lỗi liên tiếp trước khi báo lỗi lên giao diện


def _put_latest(q, item) -> None:
    """Chỉ giữ phần tử mới nhất: bên nhận chậm thì bỏ cái cũ chứ không dồn hàng."""
    try:
        q.put_nowait(item)
    except queue.Full:
        try:
            q.get_nowait()
        except queue.Empty:
            pass
        try:
            q.put_nowait(item)
        except queue.Full:
            pass


def _analyze(detector, frame: np.ndarray, seq: int, jobs, encodings) -> FrameResult:
    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    result = FrameResult(frame, detector.detect(rgb), dark=brightness(gray) < settings.MIN_BRIGHTNESS, seq=seq)
    if result.boxes:
        box = largest(result.boxes)  # nhiều người: xác thực người đứng gần nhất
        top, right, bottom, left = box
        crop = gray[top:bottom, left:right]
        result.landmarks = detector.landmarks(rgb, box)
        result.quality_ok = is_sharp(crop) and brightness_ok(crop)
        # Tiến trình tạo vector bận thì bỏ qua frame này. KHÔNG thay job cũ bằng job mới (_put_latest):
        # lấy job ra rồi bỏ lại ở mọi frame làm tiến trình tạo vector không bao giờ nhận kịp khi máy bận
        # (đo thật: 0 vector/giây ở CPU 79%). Độ trễ của vector được xử lý bằng số thứ tự frame.
        try:
            jobs.put_nowait((seq, rgb, box, result.landmarks, result.quality_ok))
        except queue.Full:
            pass
    try:
        result.encoding_seq, result.encoding, result.encoding_landmarks, result.encoding_quality = \
            encodings.get_nowait()
    except queue.Empty:
        pass
    return result


def _encode_process(jobs, encodings, stop) -> None:
    """Process con thứ hai: chỉ tạo vector 128 chiều (~400 ms/lần).

    Tách khỏi tiến trình tìm mặt để landmark (dùng cho nháy mắt, quay đầu) chạy đều ~20 frame/s,
    không bị chặn mỗi lần tạo vector. Đo thật: chung một tiến trình thì có khoảng trống tới ~870 ms
    giữa hai frame landmark, đủ để bỏ sót một cái nháy mắt. Trả vector kèm số thứ tự, landmark và
    độ nét của chính frame được tính, để bên dùng không ghép nhầm với frame hiện tại.
    """
    from core.face_encoder import encode_face  # nạp dlib chỉ trong tiến trình con, không trong tiến trình giao diện

    encodings.cancel_join_thread()
    errors = 0
    while not stop.is_set():
        try:
            seq, rgb, box, landmarks, quality_ok = jobs.get(timeout=0.2)
        except queue.Empty:
            continue
        try:
            _put_latest(encodings, (seq, encode_face(rgb, box), landmarks, quality_ok))
            errors = 0
        except Exception:  # lỗi một frame: bỏ qua, frame sau sẽ được giao lại
            traceback.print_exc()
            errors += 1
            if errors >= MAX_ANALYSIS_ERRORS:
                return  # lỗi kéo dài: dừng để is_alive() = False, giao diện báo "Tiến trình xử lý ảnh đã dừng"


def _analysis_process(frames, results, stop, jobs, encodings) -> None:
    """Chạy trong process con: nhận frame, trả FrameResult."""
    from core.face_detector import FaceDetector  # nạp dlib chỉ trong tiến trình con

    results.cancel_join_thread()
    jobs.cancel_join_thread()
    detector, errors, seq = FaceDetector(), 0, 0
    while not stop.is_set():
        try:
            frame = frames.get(timeout=0.2)
        except queue.Empty:
            continue
        seq += 1
        try:
            result = _analyze(detector, frame, seq, jobs, encodings)
            errors = 0
        except Exception as exc:  # một frame lỗi không được làm chết cả tiến trình xử lý
            traceback.print_exc()
            errors += 1
            if errors < MAX_ANALYSIS_ERRORS:
                continue  # lỗi thoáng qua: bỏ frame này, không hủy phiên của người dùng
            result = FrameResult(None, error=f"Lỗi xử lý ảnh: {exc}")
        _put_latest(results, result)


class VisionWorker:
    def __init__(self, out: mp.Queue) -> None:
        self._out = out
        self._frames: mp.Queue = mp.Queue(maxsize=1)
        # Frame/kết quả còn dở trong queue lúc thoát thì bỏ, không chờ gửi (nếu không app sẽ treo khi tắt).
        self._frames.cancel_join_thread()
        out.cancel_join_thread()
        self._stop_event = mp.Event()
        self._lock = threading.Lock()
        self._frame: np.ndarray | None = None
        # Giữa 2 process con, chỉ giữ cái mới nhất. Phải giữ tham chiếu trên self: Process.start() bỏ
        # tham chiếu tới args, queue bị thu gom thì trên macOS semaphore bị xóa trước khi process con
        # (spawn, import dlib mất vài giây) kịp mở lại → process con chết với FileNotFoundError.
        self._jobs, self._encodings = jobs, encodings = mp.Queue(maxsize=1), mp.Queue(maxsize=1)
        self._processes = [
            mp.Process(target=_analysis_process, args=(self._frames, out, self._stop_event, jobs, encodings),
                       daemon=True),
            mp.Process(target=_encode_process, args=(jobs, encodings, self._stop_event), daemon=True),
        ]
        self._capture = threading.Thread(target=self._capture_loop, daemon=True)

    def start(self) -> None:
        for process in self._processes:
            process.start()
        self._capture.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._capture.is_alive():  # chưa start() thì không có gì để chờ
            self._capture.join(timeout=1)  # để thread kịp release() camera trước khi ứng dụng thoát

    def is_alive(self) -> bool:
        """False nếu một tiến trình xử lý ảnh hoặc thread đọc camera đã chết."""
        return self._stop_event.is_set() or (all(p.is_alive() for p in self._processes)
                                             and self._capture.is_alive())

    def latest_frame(self) -> np.ndarray | None:
        """Frame camera mới nhất để hiển thị (chưa xử lý)."""
        with self._lock:
            return self._frame

    def _capture_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                with CameraStream() as cam:
                    while not self._stop_event.is_set():
                        frame = cam.read_frame()
                        if frame is None:
                            continue
                        with self._lock:
                            self._frame = frame
                        try:
                            self._frames.put_nowait(frame)  # process con đang bận thì bỏ frame này
                        except queue.Full:
                            pass
            except Exception as exc:  # CameraError hoặc lỗi bất ngờ của OpenCV: báo lỗi rồi thử mở lại
                if not isinstance(exc, CameraError):
                    traceback.print_exc()
                # Giữ frame cuối để màn hình vẫn có hình nền cho thông báo lỗi.
                _put_latest(self._out, FrameResult(None, error=str(exc)))
                self._stop_event.wait(2)  # thử mở lại camera sau 2 giây
