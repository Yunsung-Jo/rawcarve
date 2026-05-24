import mmap
import struct
import tempfile
from pathlib import Path
from io import StringIO

from carver.models import FileHit
from carve import process, is_in_range, make_output_dirs


# ── 테스트 헬퍼 ──────────────────────────────────────────────

# 실제 파서를 통과하는 최소 JPEG: SOI + APP0(JFIF) + EOI
_APP0 = b'\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00'
MINIMAL_JPEG = b'\xff\xd8' + _APP0 + b'\xff\xd9'

# 최소 AVI: RIFF + chunk_size + AVI
MINIMAL_AVI = b'RIFF' + struct.pack('<I', 4) + b'AVI '


def make_mmap(data: bytes) -> mmap.mmap:
    mm = mmap.mmap(-1, len(data))
    mm.write(data)
    mm.seek(0)
    return mm


# ── is_in_range 테스트 ──────────────────────────────────────

def test_is_in_range_inside():
    assert is_in_range(150, [(100, 200)]) is True


def test_is_in_range_outside():
    assert is_in_range(50, [(100, 200)]) is False


def test_is_in_range_boundary():
    assert is_in_range(100, [(100, 200)]) is False  # 시작점은 범위 밖
    assert is_in_range(200, [(100, 200)]) is False  # 끝점도 범위 밖


# ── make_output_dirs 테스트 ─────────────────────────────────

def test_make_output_dirs_creates_jpeg_and_avi(tmp_path):
    make_output_dirs(tmp_path, save_thumbnails=False)
    assert (tmp_path / 'jpeg').exists()
    assert (tmp_path / 'avi').exists()
    assert not (tmp_path / 'jpeg_thumbnails').exists()


def test_make_output_dirs_creates_thumbnails_when_flagged(tmp_path):
    make_output_dirs(tmp_path, save_thumbnails=True)
    assert (tmp_path / 'jpeg_thumbnails').exists()


# ── process() 통합 테스트 ────────────────────────────────────

def test_process_extracts_jpeg(tmp_path):
    """process()가 JPEG를 jpeg/ 폴더에 추출한다."""
    padding = b'\x00' * 100
    img = padding + MINIMAL_JPEG + b'\x00' * 100
    mm = make_mmap(img)
    make_output_dirs(tmp_path, save_thumbnails=False)
    hits = [FileHit('jpeg', 100)]

    result = process(mm, hits, tmp_path, 500 * 1024 * 1024, False, StringIO())
    mm.close()

    assert result['jpeg'] == 1
    out = tmp_path / 'jpeg' / '0x00000064.jpg'
    assert out.exists()
    assert out.read_bytes()[:2] == b'\xff\xd8'


def test_process_extracts_avi(tmp_path):
    """process()가 AVI를 avi/ 폴더에 추출한다."""
    padding = b'\x00' * 100
    img = padding + MINIMAL_AVI + b'\x00' * 100
    mm = make_mmap(img)
    make_output_dirs(tmp_path, save_thumbnails=False)
    hits = [FileHit('avi', 100)]

    result = process(mm, hits, tmp_path, 500 * 1024 * 1024, False, StringIO())
    mm.close()

    assert result['avi'] == 1
    out = tmp_path / 'avi' / '0x00000064.avi'
    assert out.exists()


def test_process_skips_embedded_thumbnail(tmp_path):
    """부모 JPEG 범위 내 오프셋의 JPEG hit은 썸네일로 처리한다."""
    padding = b'\x00' * 100
    img = padding + MINIMAL_JPEG + b'\x00' * 100
    mm = make_mmap(img)
    make_output_dirs(tmp_path, save_thumbnails=False)

    # 부모(100)와 썸네일(110, 부모 범위 내)
    hits = [FileHit('jpeg', 100), FileHit('jpeg', 110)]

    result = process(mm, hits, tmp_path, 500 * 1024 * 1024, False, StringIO())
    mm.close()

    assert result['jpeg'] == 1
    assert result['thumbnails'] == 1
    assert not (tmp_path / 'jpeg' / '0x0000006E.jpg').exists()


def test_process_saves_thumbnail_when_flagged(tmp_path):
    """--save-thumbnails 플래그 시 썸네일을 jpeg_thumbnails/에 저장한다."""
    padding = b'\x00' * 100
    img = padding + MINIMAL_JPEG + b'\x00' * 100
    mm = make_mmap(img)
    make_output_dirs(tmp_path, save_thumbnails=True)

    hits = [FileHit('jpeg', 100), FileHit('jpeg', 110)]

    result = process(mm, hits, tmp_path, 500 * 1024 * 1024, True, StringIO())
    mm.close()

    assert result['thumbnails'] == 1
    assert (tmp_path / 'jpeg_thumbnails' / '0x0000006E.jpg').exists()


def test_process_counts_errors_without_crash(tmp_path):
    """추출 중 예외가 발생해도 프로그램이 중단되지 않고 error로 기록한다."""
    img = b'\x00' * 200
    mm = make_mmap(img)
    make_output_dirs(tmp_path, save_thumbnails=False)

    # RIFF 없는 위치에 avi hit → avi_end가 ValueError 발생
    hits = [FileHit('avi', 50)]

    result = process(mm, hits, tmp_path, 500 * 1024 * 1024, False, StringIO())
    mm.close()

    assert result['errors'] == 1
    assert result['avi'] == 0
