import numpy as np

from tests.conftest import vector
from tools.measure_far_frr import session_report


def test_session_report_splits_genuine_and_impostor():
    templates = {"An": [vector(1)], "Binh": [vector(2)]}
    sessions = {"An": np.array([vector(1), vector(1) * 1.01])}
    genuine, impostor = session_report(sessions, templates)
    assert len(genuine) == 2 and len(impostor) == 2
    assert genuine.max() < 0.1 and impostor.min() > 1.0
