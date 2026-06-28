import struct
import mmap
from typing import Union

_Data = Union[bytes, bytearray, mmap.mmap]

JPEG_MAX_FALLBACK_SIZE = 10 * 1024 * 1024  # 10 MB
MAX_AVI_SIZE_DEFAULT = 500 * 1024 * 1024   # 500 MB

# 길이 필드 없는 마커: TEM(01), RST0-RST7(D0-D7)
# SOI(D8), EOI(D9)는 루프에서 별도 처리
_MARKER_NO_LENGTH = frozenset([0x01] + list(range(0xD0, 0xD8)))

# EOI 검증: 손상 스트림에서 stuffing이 깨져 생긴 가짜 FF D9를 진짜 EOI로
# 오인하지 않기 위한 파라미터. EOI 직후 윈도우의 "FF 다음 00/RST" 비율이
# 임계 이상이면 엔트로피 연속(=가짜 EOI)으로 보고 다음 후보를 찾는다.
_EOI_PROBE_WINDOW = 4096
_EOI_STUFF_THRESHOLD = 0.3


def _stuffing_ratio(seg: bytes) -> float:
    """seg에서 FF 다음 바이트가 stuffing(00) 또는 RST(D0–D7)인 비율.
    JPEG 엔트로피 스트림이면 1에 가깝고, 헤더/패딩/타 파일이면 낮다."""
    ff = stuff = 0
    for i in range(len(seg) - 1):
        if seg[i] == 0xFF:
            ff += 1
            nb = seg[i + 1]
            if nb == 0x00 or 0xD0 <= nb <= 0xD7:
                stuff += 1
    return stuff / ff if ff else 0.0


def _is_genuine_eoi(data: _Data, eoi_end: int, upper: int) -> bool:
    """EOI 직후가 엔트로피 연속이 아니면 진짜 EOI로 판단한다.
    검사할 데이터가 부족하면(상한·파일끝 근처) 진짜로 간주한다."""
    seg = data[eoi_end:min(eoi_end + _EOI_PROBE_WINDOW, upper)]
    if len(seg) < 128:
        return True
    return _stuffing_ratio(seg) < _EOI_STUFF_THRESHOLD


def _next_header(data: _Data, start: int, size: int) -> int:
    """start 이후 첫 '진짜 JPEG 헤더'(FF D8 FF E0–EF = SOI+APPn) 오프셋. 없으면 size.
    엔트로피 시작 이후를 탐색하므로 헤더 내 EXIF 썸네일이 아닌 실제 다음 파일
    경계를 찾는다(엔트로피 중 우연한 FF D8 FF E0–EF 4바이트 매칭은 매우 드묾)."""
    p = start
    while True:
        i = data.find(b'\xff\xd8\xff', p)
        if i < 0 or i >= size:
            return size
        if i + 3 < size and 0xE0 <= data[i + 3] <= 0xEF:
            return i
        p = i + 1


def jpeg_end(
    data: _Data,
    offset: int,
    next_sig_offset: int | None = None,
) -> tuple[int, bool]:
    """
    JPEG 세그먼트 파싱으로 파일 끝 오프셋 반환.

    스캔 데이터의 FF D9 후보는 즉시 채택하지 않고, 직후가 엔트로피 연속인지
    검사해 손상으로 생긴 가짜 EOI를 건너뛴다(_is_genuine_eoi). 탐색 상한은
    엔트로피 시작 이후의 다음 JPEG 헤더(_next_header)로, 다음 파일을 침범하지
    않는다. next_sig_offset은 SOS를 찾지 못한 경우의 fallback에만 쓴다.

    Returns:
        (end_offset, is_complete)
        end_offset: 파일 마지막 바이트 다음 위치 (exclusive)
        is_complete: True면 진짜 EOI 발견, False면 fallback 사용
    """
    pos = offset
    size = len(data)

    if data[pos:pos + 2] != b'\xff\xd8':
        raise ValueError(f'SOI 없음: {offset:#x}')
    pos += 2

    while pos < size - 1:
        if data[pos] != 0xFF:
            pos += 1
            continue

        mb = data[pos + 1]

        if mb == 0xD9:  # EOI
            return pos + 2, True

        if mb == 0xDA:  # SOS — 이후는 스캔 데이터
            pos += 2
            if pos + 2 > size:
                break
            sos_len = struct.unpack('>H', data[pos:pos + 2])[0]
            if sos_len < 2 or pos + sos_len > size:
                break
            pos += sos_len  # SOS 헤더 건너뜀

            # 상한: 엔트로피 시작 이후 다음 JPEG 헤더(=다음 파일 경계)와 MAX_FALLBACK
            # 중 작은 쪽. 정확한 경계로 제한해야 _is_genuine_eoi 검사가 다음 파일을
            # 섞어 보지 않고, carve가 다음 파일을 삼키지도 않는다.
            upper = min(_next_header(data, pos, size), offset + JPEG_MAX_FALLBACK_SIZE, size)

            # 스캔 데이터: FF D9 후보를 검증하며 진짜 EOI를 탐색한다.
            while pos < size - 1 and pos < upper:
                ff = data.find(b'\xff', pos)
                if ff == -1 or ff >= size - 1 or ff >= upper:
                    break
                nb = data[ff + 1]
                if nb == 0xD9:  # EOI 후보
                    if _is_genuine_eoi(data, ff + 2, upper):
                        return ff + 2, True
                    pos = ff + 2   # 가짜 EOI(엔트로피 연속) → 다음 후보로
                elif nb == 0x00 or 0xD0 <= nb <= 0xD7:  # stuffed byte or RST
                    pos = ff + 2
                else:
                    pos = ff + 1
            # 상한까지 진짜 EOI를 못 찾음 → 상한에서 fallback
            return upper, False

        if mb == 0xD8:  # SOI mid-stream — 손상된 파일
            break

        if mb == 0xFF:  # 필 바이트 (JPEG 스펙 §B.1.1.2 허용)
            pos += 1
            continue

        if mb in _MARKER_NO_LENGTH:
            pos += 2
            continue

        # 길이 있는 세그먼트
        if pos + 4 > size:
            break
        seg_len = struct.unpack('>H', data[pos + 2:pos + 4])[0]
        if seg_len < 2 or pos + 2 + seg_len > size:
            break  # 비정상 길이 → fallback
        pos = pos + 2 + seg_len

    # Fallback
    if next_sig_offset is not None:
        return next_sig_offset, False
    return min(offset + JPEG_MAX_FALLBACK_SIZE, size), False


def avi_end(
    data: _Data,
    offset: int,
    max_size: int = MAX_AVI_SIZE_DEFAULT,
    next_sig_offset: int | None = None,
) -> tuple[int, bool]:
    """
    AVI (RIFF) 파일 끝 오프셋 반환.

    Returns:
        (end_offset, used_header)
        used_header: True면 RIFF chunk_size 기반, False면 fallback 사용
    """
    size = len(data)

    if data[offset:offset + 4] != b'RIFF':
        raise ValueError(f'RIFF 없음: {offset:#x}')

    if offset + 8 > size:
        fallback = next_sig_offset if next_sig_offset is not None else offset + max_size
        return min(fallback, size), False

    chunk_size = struct.unpack('<I', data[offset + 4:offset + 8])[0]
    end_from_header = offset + 8 + chunk_size

    if 0 < chunk_size <= max_size and end_from_header <= size:
        return end_from_header, True

    # Fallback: next signature 또는 max_size 상한
    if next_sig_offset is not None:
        return min(next_sig_offset, offset + max_size, size), False
    return min(offset + max_size, size), False
