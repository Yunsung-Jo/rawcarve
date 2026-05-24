import struct
import pytest
from carver.extractors import jpeg_end, JPEG_MAX_FALLBACK_SIZE


# ── 테스트 헬퍼 ──────────────────────────────────────────────

def make_app_segment(marker_byte: int, payload: bytes) -> bytes:
    """마커 + 길이 + 페이로드 형식의 JPEG 세그먼트 생성."""
    length = len(payload) + 2  # 길이 필드 자신(2바이트) 포함
    return bytes([0xFF, marker_byte]) + struct.pack('>H', length) + payload


def make_jpeg(*segments: bytes, include_eoi: bool = True) -> bytes:
    """SOI + 세그먼트들 + EOI 형식의 최소 JPEG 생성."""
    data = b'\xff\xd8'
    for seg in segments:
        data += seg
    if include_eoi:
        data += b'\xff\xd9'
    return data


# APP0(JFIF) 세그먼트 — 실제 카메라 JPEG에 흔히 등장
APP0 = make_app_segment(0xE0, b'JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00')


# ── jpeg_end 테스트 ──────────────────────────────────────────

def test_jpeg_end_simple():
    """단순 SOI + APP0 + EOI 구조를 정확히 파싱한다."""
    data = make_jpeg(APP0)
    end, complete = jpeg_end(data, 0)
    assert end == len(data)
    assert complete is True


def test_jpeg_end_offset_not_zero():
    """오프셋 0이 아닌 위치에서도 올바르게 동작한다."""
    prefix = b'\x00' * 100
    data = prefix + make_jpeg(APP0)
    end, complete = jpeg_end(data, 100)
    assert end == len(data)
    assert complete is True


def test_jpeg_end_skips_embedded_thumbnail():
    """APP1 내부의 임베디드 썸네일 FF D9를 EOI로 오판하지 않는다."""
    thumbnail = b'\xff\xd8\xff\xd9'  # 내장 썸네일 (FF D9 포함)
    app1_payload = b'Exif\x00\x00' + thumbnail + b'\x00' * 8
    app1 = make_app_segment(0xE1, app1_payload)
    data = make_jpeg(app1)  # 진짜 EOI는 맨 끝
    end, complete = jpeg_end(data, 0)
    assert end == len(data)
    assert complete is True


def test_jpeg_end_no_eoi_uses_next_sig():
    """EOI가 없으면 next_sig_offset을 fallback으로 사용한다."""
    data = make_jpeg(APP0, include_eoi=False) + b'\x00' * 200
    next_sig = len(data) - 50
    end, complete = jpeg_end(data, 0, next_sig)
    assert end == next_sig
    assert complete is False


def test_jpeg_end_no_eoi_no_fallback_uses_size_limit():
    """EOI도 없고 next_sig도 없으면 10 MB 상한을 적용한다."""
    data = make_jpeg(APP0, include_eoi=False) + b'\x00' * 10
    end, complete = jpeg_end(data, 0)
    assert end == min(JPEG_MAX_FALLBACK_SIZE, len(data))
    assert complete is False


def test_jpeg_end_corrupt_segment_triggers_fallback():
    """세그먼트 길이 필드가 1(비정상)이면 fallback으로 전환한다."""
    corrupt = b'\xff\xe0\x00\x01'  # 길이=1, JPEG 스펙상 최솟값은 2
    data = b'\xff\xd8' + corrupt + b'\xff\xd9'
    end, complete = jpeg_end(data, 0, next_sig_offset=50)
    assert complete is False


def test_jpeg_end_raises_on_missing_soi():
    """SOI(FF D8)가 없으면 ValueError를 발생시킨다."""
    data = b'\x00' * 20
    with pytest.raises(ValueError, match='SOI'):
        jpeg_end(data, 0)
