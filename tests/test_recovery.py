import csv
import io
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest
from PIL import Image
from carver.recovery import detect_damaged_blocks, interpolate_damaged_blocks

_RECOVER_SCRIPT = Path(__file__).parent.parent / 'recover.py'


def _solid(h=64, w=64, color=(100, 150, 200)) -> np.ndarray:
    arr = np.zeros((h, w, 3), dtype=np.uint8)
    arr[:, :] = color
    return arr


def _gray128(h=64, w=64) -> np.ndarray:
    return np.full((h, w, 3), 128, dtype=np.uint8)


def test_detect_all_damaged():
    damaged = detect_damaged_blocks(_gray128())
    assert damaged.shape == (8, 8)
    assert damaged.all()


def test_detect_none_damaged():
    damaged = detect_damaged_blocks(_solid())
    assert not damaged.any()


def test_detect_one_damaged_block():
    arr = _solid()
    arr[:8, :8] = 128  # 좌상단 블록을 회색으로
    damaged = detect_damaged_blocks(arr)
    assert damaged[0, 0]
    assert not damaged[0, 1]


def test_interpolate_fills_gray_block():
    arr = _solid()
    arr[:8, :8] = 128
    damaged = detect_damaged_blocks(arr)
    result = interpolate_damaged_blocks(arr, damaged)
    block = result[:8, :8]
    # 보간 후 회색(128±2)이 아니어야 함
    assert not np.all(np.abs(block.astype(int) - 128) <= 2)


def test_interpolate_preserves_valid_blocks():
    arr = _solid()
    arr[:8, :8] = 128
    damaged = detect_damaged_blocks(arr)
    result = interpolate_damaged_blocks(arr, damaged)
    assert np.array_equal(result[8:, 8:], arr[8:, 8:])


from carver.recovery import _collect_violations, _patch_bad_stuff, _force_decode_arr


def _make_jpeg(w=64, h=64, color=None) -> bytes:
    """랜덤 노이즈 이미지를 JPEG으로 인코딩. FF 00 스터핑 바이트가 충분히 생성되도록 함.
    color 지정 시 해당 색상 기반 노이즈 이미지를 사용한다 (FF 00 생성 보장)."""
    rng = np.random.default_rng(seed=42)
    if color is not None:
        base = np.full((h, w, 3), color, dtype=np.int32)
        noise = rng.integers(-30, 30, (h, w, 3), dtype=np.int32)
        arr = np.clip(base + noise, 0, 255).astype(np.uint8)
    else:
        arr = rng.integers(0, 256, (h, w, 3), dtype=np.uint8)
    img = Image.fromarray(arr, mode='RGB')
    buf = io.BytesIO()
    img.save(buf, format='JPEG', quality=95)
    return buf.getvalue()


def _corrupt(data: bytes, count: int = 1) -> tuple[bytes, int]:
    """스캔 데이터 내 FF 00 을 count개 FF EC 로 교체. (patched_data, scan_start) 반환."""
    from carver.diagnosis import _parse_header
    ss = _parse_header(data)['scan_start']
    arr = bytearray(data)
    found = 0
    for i in range(ss, len(arr) - 1):
        if arr[i] == 0xFF and arr[i + 1] == 0x00:
            arr[i + 1] = 0xEC
            found += 1
            if found >= count:
                break
    return bytes(arr), ss


def test_collect_violations():
    data, ss = _corrupt(_make_jpeg(), count=3)
    viols = _collect_violations(data, ss)
    assert len(viols) >= 3


def test_patch_removes_all_violations():
    data, ss = _corrupt(_make_jpeg(), count=2)
    viols = _collect_violations(data, ss)
    patched = _patch_bad_stuff(data, viols)
    assert len(_collect_violations(patched, ss)) == 0


def test_force_decode_clean():
    arr = _force_decode_arr(_make_jpeg())
    assert arr is not None
    assert arr.shape == (64, 64, 3)


def test_force_decode_corrupted():
    data, _ = _corrupt(_make_jpeg(), count=10)
    arr = _force_decode_arr(data)
    assert arr is not None  # LOAD_TRUNCATED_IMAGES=True 로 항상 반환


from carver.recovery import recover_file
from carver.diagnosis import diagnose, DiagnosisResult


def test_recover_file_bad_stuff(tmp_path):
    data, _ = _corrupt(_make_jpeg(color=(200, 100, 50)), count=2)
    p = tmp_path / '0x00001000.jpg'
    p.write_bytes(data)
    out = tmp_path / 'out'
    out.mkdir()
    r = diagnose(p)
    result_path, action = recover_file(p, r, out)
    assert action in ('RECOVERED_PATCHED', 'RECOVERED_INTERPOLATED')
    assert result_path is not None and result_path.exists()
    img = Image.open(result_path)
    assert img.size == (64, 64)


def test_recover_file_clean(tmp_path):
    p = tmp_path / 'clean.jpg'
    p.write_bytes(_make_jpeg())
    out = tmp_path / 'out'
    out.mkdir()
    r = diagnose(p)
    result_path, action = recover_file(p, r, out)
    assert action == 'CLEAN'
    assert result_path is None


def test_recover_file_false_positive(tmp_path):
    data = bytearray(_make_jpeg())
    for i in range(len(data) - 1):
        if data[i] == 0xFF and data[i + 1] == 0xC0:
            data[i + 9] = 195
            break
    p = tmp_path / 'fp.jpg'
    p.write_bytes(bytes(data))
    out = tmp_path / 'out'
    out.mkdir()
    r = diagnose(p)
    result_path, action = recover_file(p, r, out)
    assert action == 'SKIP_FALSE_POSITIVE'
    assert result_path is None


def test_recover_file_marker_flip(tmp_path):
    data = bytearray(_make_jpeg(w=64, h=64))
    for i in range(len(data) - 1):
        if data[i] == 0xFF and data[i + 1] == 0xDB:
            data[i + 1] = 0xCB  # DQT -> SOF11
            break
    p = tmp_path / 'flip.jpg'
    p.write_bytes(bytes(data))
    out = tmp_path / 'out'
    out.mkdir()
    r = diagnose(p)
    result_path, action = recover_file(p, r, out)
    assert action in ('RECOVERED_PATCHED', 'RECOVERED_INTERPOLATED', 'SKIP_TOO_DAMAGED')


def test_recover_cli_smoke(tmp_path):
    src = tmp_path / 'jpeg'
    src.mkdir()
    out = tmp_path / 'jpeg_recovered'
    for i in range(3):
        (src / f'0x{i:08X}.jpg').write_bytes(_make_jpeg())
    result = subprocess.run(
        [sys.executable, str(_RECOVER_SCRIPT), str(src), '-o', str(out)],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    report = out / 'report.csv'
    assert report.exists()
    rows = list(csv.DictReader(report.read_text(encoding='utf-8').splitlines()))
    assert len(rows) == 3
    assert all(r['action'] == 'CLEAN' for r in rows)
    assert rows[0]['filename'].endswith('.jpg')
