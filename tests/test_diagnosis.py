import io
import struct
import pytest
from pathlib import Path
from PIL import Image
from carver.diagnosis import DiagnosisResult, diagnose


def _make_jpeg(w=64, h=64, color=(100, 150, 200)) -> bytes:
    # 그라디언트 이미지로 생성해 스캔 데이터에 FF 00 스터핑 바이트가 생기도록 한다.
    # 단색 이미지는 DCT 계수가 균일해 스터핑 바이트가 없으므로 BAD_STUFF 테스트가 불가능하다.
    pixels = []
    for y in range(h):
        for x in range(w):
            pixels.extend([
                (color[0] + x + y * 2) % 256,
                (color[1] + x * 2 + y) % 256,
                (color[2] + x + y) % 256,
            ])
    img = Image.frombytes('RGB', (w, h), bytes(pixels))
    buf = io.BytesIO()
    img.save(buf, format='JPEG', quality=85)
    return buf.getvalue()


def test_clean_file(tmp_path):
    p = tmp_path / 'clean.jpg'
    p.write_bytes(_make_jpeg())
    r = diagnose(p)
    assert r.causes == ['CLEAN']
    assert r.sof == (64, 64, 3)
    assert r.scan_start > 0
    assert r.has_eoi is True


def test_false_positive_impossible_ncomp(tmp_path):
    data = bytearray(_make_jpeg())
    # SOF0 구조: FF C0 LL LL PP HH HH WW WW NN  (NN = ncomp, pos+9)
    for i in range(len(data) - 1):
        if data[i] == 0xFF and data[i + 1] == 0xC0:
            data[i + 9] = 195  # 불가능한 ncomp
            break
    p = tmp_path / 'fp.jpg'
    p.write_bytes(bytes(data))
    r = diagnose(p)
    assert 'FALSE_POSITIVE' in r.causes


def test_false_positive_no_sof(tmp_path):
    # SOI + APP0 만 있고 SOF 없음
    p = tmp_path / 'nosof.jpg'
    p.write_bytes(b'\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00')
    r = diagnose(p)
    assert 'FALSE_POSITIVE' in r.causes


def _scan_start(data: bytes) -> int:
    from carver.diagnosis import _parse_header
    return _parse_header(data)['scan_start']


def test_marker_byte_flip(tmp_path):
    data = bytearray(_make_jpeg())
    for i in range(len(data) - 1):
        if data[i] == 0xFF and data[i + 1] == 0xDB:  # DQT -> SOF11
            data[i + 1] = 0xCB
            break
    p = tmp_path / 'flip.jpg'
    p.write_bytes(bytes(data))
    r = diagnose(p)
    assert 'MARKER_BYTE_FLIP' in r.causes
    assert r.broken_marker == 0xCB


def test_bad_stuff(tmp_path):
    data = bytearray(_make_jpeg())
    ss = _scan_start(bytes(data))
    for i in range(ss, len(data) - 1):
        if data[i] == 0xFF and data[i + 1] == 0x00:
            data[i + 1] = 0xEC  # 스터핑 위반
            break
    p = tmp_path / 'bad.jpg'
    p.write_bytes(bytes(data))
    r = diagnose(p)
    assert 'BAD_STUFF' in r.causes
    assert r.first_bad_offset is not None and r.first_bad_offset >= 0


def test_gray_mcu(tmp_path):
    data = bytearray(_make_jpeg())
    ss = _scan_start(bytes(data))
    pattern = bytes([0x01, 0x45, 0x00, 0x14, 0x50]) * 6
    data = data[:ss] + pattern + data[ss:]
    p = tmp_path / 'gray.jpg'
    p.write_bytes(bytes(data))
    r = diagnose(p)
    assert 'GRAY_MCU' in r.causes
    assert r.gray_run_offset == 0
    assert r.gray_run_len == len(pattern)


def test_zero_fill(tmp_path):
    data = bytearray(_make_jpeg())
    ss = _scan_start(bytes(data))
    data = data[:ss] + bytes(len(data) - ss)
    p = tmp_path / 'zero.jpg'
    p.write_bytes(bytes(data))
    r = diagnose(p)
    assert 'ZERO_FILL' in r.causes


from carver.diagnosis import _find_scan_end


def test_find_scan_end_stops_at_sda():
    # FF 00 FF 00 FF DA ... 구조에서 FF DA 위치를 반환해야 한다
    data = bytes([0xFF, 0x00, 0xFF, 0x00, 0xFF, 0xDA, 0x00, 0x0C])
    assert _find_scan_end(data, 0) == 4


def test_find_scan_end_skips_violations():
    # FF EC (위반)는 경계가 아니므로 건너뛰고, 이후 FF D9에서 종료해야 한다
    data = bytes([0xFF, 0x00, 0xFF, 0xEC, 0xFF, 0xD9])
    assert _find_scan_end(data, 0) == 4


def test_find_scan_end_no_boundary():
    # 경계 마커 없으면 len(data) 반환
    data = bytes([0xFF, 0x00, 0xAB, 0xCD])
    assert _find_scan_end(data, 0) == len(data)


def test_find_scan_end_rst_continues():
    # FF D5 (RST5)는 스캔 데이터의 일부이므로 계속 진행해야 한다
    data = bytes([0xFF, 0xD5, 0xFF, 0xDA])
    assert _find_scan_end(data, 0) == 2


def _make_progressive_jpeg(w=128, h=128) -> bytes:
    import numpy as np
    rng = np.random.default_rng(seed=7)
    arr = rng.integers(0, 256, (h, w, 3), dtype=np.uint8)
    img = Image.fromarray(arr, mode='RGB')
    buf = io.BytesIO()
    img.save(buf, format='JPEG', progressive=True, quality=85)
    return buf.getvalue()


def test_parse_header_progressive_has_scan_ranges():
    from carver.diagnosis import _parse_header
    data = _make_progressive_jpeg()
    hdr = _parse_header(data)
    # Progressive JPEG는 여러 SOS를 가진다
    assert len(hdr['scan_ranges']) >= 2
    # 각 범위의 start < end 이어야 한다
    for start, end in hdr['scan_ranges']:
        assert start < end
    # scan_start는 여전히 첫 번째 스캔 시작을 가리켜야 한다
    assert hdr['scan_start'] == hdr['scan_ranges'][0][0]


def test_parse_header_baseline_has_one_scan_range():
    from carver.diagnosis import _parse_header
    data = _make_jpeg()  # 기존 헬퍼: baseline JPEG
    hdr = _parse_header(data)
    assert len(hdr['scan_ranges']) == 1
    assert hdr['scan_ranges'][0][0] == hdr['scan_start']


def test_diagnose_progressive_has_scan_ranges(tmp_path):
    data = _make_progressive_jpeg()
    p = tmp_path / 'prog.jpg'
    p.write_bytes(data)
    r = diagnose(p)
    assert len(r.scan_ranges) >= 2


def test_diagnose_progressive_scan_boundary_not_bad_stuff(tmp_path):
    """Progressive JPEG의 스캔 경계 마커(FF DA)가 BAD_STUFF로 탐지되면 안 된다."""
    data = _make_progressive_jpeg()
    p = tmp_path / 'prog.jpg'
    p.write_bytes(data)
    r = diagnose(p)
    assert 'BAD_STUFF' not in r.causes
    assert r.causes == ['CLEAN']
