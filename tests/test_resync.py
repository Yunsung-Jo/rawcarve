"""carver.resync 복구 엔진 검증."""
import io

import numpy as np
import pytest
from PIL import Image

from carver import jpegdecode as jd
from carver import resync


def encode(img: np.ndarray, subsampling: int = 1, quality: int = 92) -> bytes:
    buf = io.BytesIO()
    Image.fromarray(img).save(buf, format='JPEG', quality=quality, subsampling=subsampling)
    return buf.getvalue()


def textured_image(h=256, w=384, seed=0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    xx, yy = np.meshgrid(np.linspace(0, 255, w), np.linspace(0, 255, h))
    base = np.stack([xx, yy, (xx + yy) / 2], -1) + rng.normal(0, 25, (h, w, 3))
    return np.clip(base, 0, 255).astype(np.uint8)


def corrupt_entropy(data: bytes, n_bytes: int, seed: int = 1) -> bytes:
    """SOS 이후 엔트로피의 한 덩어리를 손상시켜 디싱크를 유발(디스크 손상 모사)."""
    h = jd.parse_header(data)
    start = h.scan_start
    last_eoi = data.rfind(b'\xff\xd9')
    arr = bytearray(data)
    rng = np.random.default_rng(seed)
    pos = start + (last_eoi - start) * 2 // 5        # 엔트로피 ~40% 지점
    for i in range(n_bytes):
        arr[pos + i] = int(rng.integers(0, 256))
    return bytes(arr)


# ── gray_fraction ──────────────────────────────────────────

def test_gray_fraction_detects_gray():
    gray = np.full((64, 64, 3), 128, np.uint8)
    assert resync.gray_fraction(gray) > 0.95


def test_gray_fraction_low_on_texture():
    assert resync.gray_fraction(textured_image()) < 0.2


# ── 복구 ────────────────────────────────────────────────────

def test_recover_clean_image_is_noop():
    """손상 없는 이미지는 회색이 낮고 편집(ops)이 거의 없다."""
    dec = jd.Decoder(encode(textured_image()))
    rgb, stats, _segs = resync.recover(dec)
    assert resync.gray_fraction(rgb) < 0.1
    assert stats['resync'] == 0 and stats['hole'] == 0


def test_recover_output_shape():
    dec = jd.Decoder(encode(textured_image(200, 320)))
    rgb, _stats, _segs = resync.recover(dec)
    assert rgb.shape == (200, 320, 3)


def test_recover_segments_strictly_increasing_bits():
    """회귀 방지: 세그먼트 시작 비트는 단조 증가해야 한다.

    과거 버그는 디싱크 후 mcu_bit가 미기록(0)으로 남아 resync가 비트 0으로 역행,
    스트림 앞부분을 반복 디코딩(주기적 중복)했다. 손상본을 복구해 비트위치가
    뒤로 가지 않음을 확인한다."""
    data = corrupt_entropy(encode(textured_image(), subsampling=1), n_bytes=40)
    dec = jd.Decoder(data)
    _rgb, _stats, segments = resync.recover(dec)
    start_bits = [sbit for (_sm, sbit, _dc) in sorted(segments)]
    assert start_bits == sorted(start_bits)          # 단조 비감소
    assert len(set(start_bits)) == len(start_bits)   # 중복(재디코딩) 없음


def test_recover_fast_and_thorough_both_run():
    """철저(기본)·빠른 모드 모두 유효한 이미지를 낸다(파라미터 스레딩 스모크)."""
    data = corrupt_entropy(encode(textured_image(200, 320)), n_bytes=24)
    for kw in ({}, dict(resync_near=160000, resync_full=False, time_budget=5.0)):
        dec = jd.Decoder(data)
        rgb, _stats, _segs = resync.recover(dec, **kw)
        assert rgb.shape == (200, 320, 3)


def test_recover_bytes_handles_garbage():
    """디코드 불가 입력은 (None, {})로 안전 처리."""
    rgb, stats = resync.recover_bytes(b'\xff\xd8not a real jpeg\xff\xd9')
    assert rgb is None and stats == {}


def test_recover_file_roundtrip(tmp_path):
    """recover_file이 유효한 JPEG를 저장한다."""
    src = tmp_path / '0xDEADBEEF.jpg'
    src.write_bytes(corrupt_entropy(encode(textured_image()), n_bytes=24))
    out, action, info = resync.recover_file(src, tmp_path)
    assert action in ('RECOVERED', 'CLEAN')
    if action == 'RECOVERED':
        assert out.exists()
        Image.open(out).load()                       # 유효 JPEG
        assert 'gray_before' in info and 'gray_after' in info
