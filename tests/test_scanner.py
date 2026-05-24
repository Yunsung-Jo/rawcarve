import mmap
import struct
import pytest
from carver.scanner import find_all_hits
from carver.models import FileHit


# ── 테스트 헬퍼 ──────────────────────────────────────────────

def make_mmap(data: bytes) -> mmap.mmap:
    """bytes를 익명 mmap으로 변환."""
    mm = mmap.mmap(-1, len(data))
    mm.write(data)
    mm.seek(0)
    return mm


def image_with(size: int, jpeg_offsets: list[int], avi_offsets: list[int]) -> bytes:
    """지정된 위치에 시그니처를 심은 더미 이미지 생성."""
    data = bytearray(b'\x00' * size)
    for off in jpeg_offsets:
        data[off:off + 3] = b'\xff\xd8\xff'
    for off in avi_offsets:
        data[off:off + 4] = b'RIFF'
        if off + 12 <= size:
            data[off + 8:off + 12] = b'AVI '
    return bytes(data)


# ── 테스트 ──────────────────────────────────────────────────

def test_finds_jpeg():
    mm = make_mmap(image_with(1024, jpeg_offsets=[100], avi_offsets=[]))
    hits = find_all_hits(mm)
    mm.close()
    assert len(hits) == 1
    assert hits[0].file_type == 'jpeg'
    assert hits[0].offset == 100


def test_finds_avi():
    mm = make_mmap(image_with(1024, jpeg_offsets=[], avi_offsets=[200]))
    hits = find_all_hits(mm)
    mm.close()
    assert len(hits) == 1
    assert hits[0].file_type == 'avi'
    assert hits[0].offset == 200


def test_finds_both_sorted():
    mm = make_mmap(image_with(2048, jpeg_offsets=[500, 100], avi_offsets=[300]))
    hits = find_all_hits(mm)
    mm.close()
    offsets = [h.offset for h in hits]
    assert offsets == sorted(offsets)
    assert len(hits) == 3


def test_ignores_non_avi_riff():
    """WAV 등 AVI 가 아닌 RIFF 포맷은 무시한다."""
    data = bytearray(b'\x00' * 1024)
    data[100:104] = b'RIFF'
    data[108:112] = b'WAVE'  # AVI  가 아님
    mm = make_mmap(bytes(data))
    hits = find_all_hits(mm)
    mm.close()
    assert not any(h.file_type == 'avi' for h in hits)


def test_empty_image():
    mm = make_mmap(b'\x00' * 512)
    hits = find_all_hits(mm)
    mm.close()
    assert hits == []


def test_multiple_jpeg_signatures():
    """같은 이미지에 JPEG 시그니처가 여러 개 있으면 모두 반환한다."""
    mm = make_mmap(image_with(4096, jpeg_offsets=[100, 500, 1000], avi_offsets=[]))
    hits = find_all_hits(mm)
    mm.close()
    jpeg_hits = [h for h in hits if h.file_type == 'jpeg']
    assert len(jpeg_hits) == 3
    assert [h.offset for h in jpeg_hits] == [100, 500, 1000]
