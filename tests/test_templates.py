import numpy as np

from ks.vision.templates import match_template


def test_match_template_finds_bright_square():
    hay = np.zeros((200, 200, 3), dtype=np.uint8)
    hay[50:70, 80:100] = 255
    needle = np.full((20, 20, 3), 255, dtype=np.uint8)
    m = match_template(hay, needle, threshold=0.9)
    assert m is not None
    assert abs(m.x - 80) <= 2
    assert abs(m.y - 50) <= 2
