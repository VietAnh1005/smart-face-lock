import multiprocessing as mp
import time

from ui.vision_worker import VisionWorker


def test_processes_survive_startup():
    """Process con phải sống qua lúc import xong (spawn trên macOS mất vài giây)."""
    worker = VisionWorker(mp.Queue(maxsize=1))
    for p in worker._processes:  # không bật thread camera: test chạy được khi không có camera
        p.start()
    try:
        time.sleep(6)
        assert [p.exitcode for p in worker._processes] == [None, None]
    finally:
        worker.stop()
        for p in worker._processes:
            p.join(3)


def test_encode_process_stops_after_repeated_errors(monkeypatch):
    """dlib lỗi liên tục: tiến trình tạo vector phải dừng để giao diện báo lỗi, không im lặng mãi."""
    import threading

    import numpy as np

    import core.face_encoder
    from ui.vision_worker import MAX_ANALYSIS_ERRORS, _encode_process

    def broken(*_):
        raise RuntimeError("dlib hỏng")

    monkeypatch.setattr(core.face_encoder, "encode_face", broken)
    jobs, encodings, stop = mp.Queue(), mp.Queue(), mp.Event()
    for i in range(MAX_ANALYSIS_ERRORS):
        jobs.put((i, np.zeros((2, 2, 3), np.uint8), (0, 1, 1, 0), None, True))
    worker = threading.Thread(target=_encode_process, args=(jobs, encodings, stop), daemon=True)
    worker.start()
    worker.join(10)
    stop.set()
    assert not worker.is_alive()
