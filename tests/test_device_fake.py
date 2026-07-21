from ks.device.fake import FakeDevice


def test_fake_device_records_taps_and_returns_png():
    d = FakeDevice(png_bytes=b"\x89PNG\r\n\x1a\nfake")
    assert d.screencap().startswith(b"\x89PNG")
    d.tap(10, 20)
    d.tap(30, 40)
    assert d.taps == [(10, 20), (30, 40)]
