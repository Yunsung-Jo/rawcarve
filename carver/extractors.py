import struct
import mmap
from typing import Union

_Data = Union[bytes, bytearray, mmap.mmap]

JPEG_MAX_FALLBACK_SIZE = 10 * 1024 * 1024  # 10 MB
MAX_AVI_SIZE_DEFAULT = 500 * 1024 * 1024   # 500 MB

# 길이 필드 없는 마커: TEM(01), RST0-RST7(D0-D7)
# SOI(D8), EOI(D9)는 루프에서 별도 처리
_MARKER_NO_LENGTH = frozenset([0x01] + list(range(0xD0, 0xD8)))


def jpeg_end(
    data: _Data,
    offset: int,
    next_sig_offset: int | None = None,
) -> tuple[int, bool]:
    """
    JPEG 세그먼트 파싱으로 파일 끝 오프셋 반환.

    Returns:
        (end_offset, is_complete)
        end_offset: 파일 마지막 바이트 다음 위치 (exclusive)
        is_complete: True면 EOI 정상 발견, False면 fallback 사용
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

            # 스캔 데이터: 0xFF 바이트를 빠르게 탐색
            while pos < size - 1:
                ff = data.find(b'\xff', pos)
                if ff == -1 or ff >= size - 1:
                    pos = size
                    break
                nb = data[ff + 1]
                if nb == 0xD9:  # EOI
                    return ff + 2, True
                elif nb == 0x00 or 0xD0 <= nb <= 0xD7:  # stuffed byte or RST
                    pos = ff + 2
                else:
                    pos = ff + 1
            break

        if mb == 0xD8:  # SOI mid-stream — 손상된 파일
            break

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
