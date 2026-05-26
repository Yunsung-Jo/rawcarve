from __future__ import annotations
import io
from pathlib import Path

import numpy as np
from PIL import Image, ImageFile
from carver.diagnosis import CANDIDATE_FIXES as _FIXES, DiagnosisResult, _parse_header

ImageFile.LOAD_TRUNCATED_IMAGES = True


def detect_damaged_blocks(arr: np.ndarray) -> np.ndarray:
    """8x8 블록 단위로 libjpeg 회색 채움(128+-2) 여부를 반환한다.

    Returns bool ndarray (bh, bw).
    """
    h, w = arr.shape[:2]
    bh, bw = h // 8, w // 8
    if bh == 0 or bw == 0:
        return np.zeros((bh, bw), dtype=bool)

    crop = arr[:bh * 8, :bw * 8]
    if arr.ndim == 3:
        blocks = crop.reshape(bh, 8, bw, 8, arr.shape[2]).astype(np.int16)
        return (np.abs(blocks - 128) <= 2).all(axis=(1, 3, 4))
    blocks = crop.reshape(bh, 8, bw, 8).astype(np.int16)
    return (np.abs(blocks - 128) <= 2).all(axis=(1, 3))



def _collect_violations(data: bytes, scan_ranges: list[tuple[int, int]]) -> list[int]:
    """각 스캔 범위 안에서 FF XX (XX != 00, D0-D9) 위치 목록을 반환 (절대 오프셋)."""
    violations: list[int] = []
    for start, end in scan_ranges:
        pos = start
        while pos < end - 1:
            ff = data.find(b'\xff', pos, end)
            if ff == -1:
                break
            nb = data[ff + 1]
            if nb != 0x00 and not (0xD0 <= nb <= 0xD9):
                violations.append(ff)
            pos = ff + 2
    return violations


def _patch_bad_stuff(data: bytes, violations: list[int]) -> bytes:
    """각 위반 위치의 두 번째 바이트를 0x00 으로 교체한 복사본 반환."""
    arr = bytearray(data)
    for pos in violations:
        if pos + 1 < len(arr):
            arr[pos + 1] = 0x00
    return bytes(arr)


def _force_decode_arr(data: bytes) -> np.ndarray | None:
    """JPEG 바이트를 numpy 배열로 강제 디코딩. 완전 실패 시 None."""
    try:
        img = Image.open(io.BytesIO(data))
        img.load()
        return np.array(img)
    except Exception:
        return None


def _arr_to_jpeg(arr: np.ndarray, quality: int = 85) -> bytes:
    """numpy 배열을 JPEG 바이트로 인코딩한다."""
    buf = io.BytesIO()
    Image.fromarray(arr).save(buf, format='JPEG', quality=quality)
    return buf.getvalue()


def _recover_bad_stuff(
    data: bytes,
    scan_ranges: list[tuple[int, int]],
    out_path: Path,
) -> str:
    """FF->00 교정 시도. 실패 시 강제 디코딩으로 폴백.

    Returns: RECOVERED_PATCHED | RECOVERED_DECODED | SKIP_TOO_DAMAGED
    """
    if not scan_ranges:
        return 'SKIP_TOO_DAMAGED'

    violations = _collect_violations(data, scan_ranges)

    if violations:
        patched = _patch_bad_stuff(data, violations)
        arr = _force_decode_arr(patched)
        if arr is not None:
            if float(detect_damaged_blocks(arr).mean()) < 0.90:
                out_path.write_bytes(_arr_to_jpeg(arr))
                return 'RECOVERED_PATCHED'

    return _recover_force_decode(data, out_path)


def _recover_force_decode(data: bytes, out_path: Path) -> str:
    """강제 디코딩. GRAY_MCU / TRUNCATED_SCAN 용."""
    arr = _force_decode_arr(data)
    if arr is None:
        return 'SKIP_TOO_DAMAGED'
    if float(detect_damaged_blocks(arr).mean()) >= 0.90:
        return 'SKIP_TOO_DAMAGED'
    out_path.write_bytes(_arr_to_jpeg(arr))
    return 'RECOVERED_DECODED'


def _recover_marker_flip(data: bytes, diagnosis: DiagnosisResult, out_path: Path) -> str:
    """헤더 마커 바이트 교정 후 BAD_STUFF 파이프라인 적용."""
    fix = _FIXES.get(diagnosis.broken_marker)
    if fix is None:
        return 'SKIP_TOO_DAMAGED'
    patched = bytearray(data)
    for i in range(len(patched) - 1):
        if patched[i] == 0xFF and patched[i + 1] == diagnosis.broken_marker:
            patched[i + 1] = fix
            break
    fixed = bytes(patched)
    new_hdr = _parse_header(fixed)
    return _recover_bad_stuff(fixed, new_hdr['scan_ranges'], out_path)


def recover_file(
    src_path: Path,
    diagnosis: DiagnosisResult,
    out_dir: Path,
) -> tuple[Path | None, str]:
    """원인에 따라 복구 전략을 선택해 실행한다.

    Returns (저장된 파일 경로 또는 None, action 문자열).
    """
    causes = diagnosis.causes
    out_path = out_dir / src_path.name

    if 'FALSE_POSITIVE' in causes:
        return None, 'SKIP_FALSE_POSITIVE'
    if 'ZERO_FILL' in causes:
        return None, 'SKIP_ZERO_FILL'
    if 'CLEAN' in causes:
        return None, 'CLEAN'

    data = src_path.read_bytes()
    try:
        if 'MARKER_BYTE_FLIP' in causes:
            action = _recover_marker_flip(data, diagnosis, out_path)
            if action == 'SKIP_TOO_DAMAGED' and 'BAD_STUFF' in causes:
                action = _recover_bad_stuff(data, diagnosis.scan_ranges, out_path)
        elif 'BAD_STUFF' in causes:
            action = _recover_bad_stuff(data, diagnosis.scan_ranges, out_path)
        else:
            action = _recover_force_decode(data, out_path)
    except Exception:
        return None, 'ERROR'

    if action.startswith('SKIP'):
        return None, action
    return out_path, action
