from __future__ import annotations
import struct
from dataclasses import dataclass, field
from pathlib import Path

_NO_LEN = frozenset([0x01] + list(range(0xD0, 0xD8)))
_SOF_MARKERS = frozenset([
    0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7,
    0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF,
])
CANDIDATE_FIXES: dict[int, int] = {0xCB: 0xDB, 0xC3: 0xC0, 0xC5: 0xC4}
_GRAY_MCU_PATTERN = bytes([0x01, 0x45, 0x00, 0x14, 0x50])


@dataclass
class DiagnosisResult:
    causes: list[str] = field(default_factory=list)
    first_bad_offset: int | None = None  # scan 내 상대 오프셋 (첫 번째 BAD_STUFF)
    gray_run_offset: int | None = None   # scan 내 상대 오프셋 (GRAY_MCU 시작)
    gray_run_len: int = 0
    scan_start: int = -1                 # 파일 내 스캔 데이터 절대 오프셋
    has_eoi: bool = False
    sof: tuple[int, int, int] | None = None  # (width, height, ncomp)
    broken_marker: int | None = None         # MARKER_BYTE_FLIP 대상 마커


def _parse_header(data: bytes) -> dict:
    """SOS 이전 JPEG 세그먼트를 파싱한다.

    Returns dict: sof, scan_start, has_eoi, markers_seen
    """
    out: dict = {
        'sof': None,
        'scan_start': -1,
        'has_eoi': False,
        'markers_seen': [],
    }
    size = len(data)
    if size < 4 or data[:2] != b'\xff\xd8':
        return out

    pos = 2
    while pos < size - 1:
        if data[pos] != 0xFF:
            pos += 1
            continue
        mb = data[pos + 1]

        if mb == 0xD9:  # EOI
            out['has_eoi'] = True
            break
        if mb == 0xD8:  # 내장 SOI
            break
        if mb == 0xFF:  # 필 바이트
            pos += 1
            continue
        if mb in _NO_LEN:
            pos += 2
            continue

        out['markers_seen'].append(mb)

        if mb == 0xDA:  # SOS
            pos += 2
            if pos + 2 > size:
                break
            sos_len = struct.unpack('>H', data[pos:pos + 2])[0]
            out['scan_start'] = pos + sos_len
            # 스캔 데이터에서 EOI 탐색
            sp = out['scan_start']
            while sp < size - 1:
                ff = data.find(b'\xff', sp)
                if ff == -1 or ff >= size - 1:
                    break
                nb = data[ff + 1]
                if nb == 0xD9:
                    out['has_eoi'] = True
                    break
                elif nb == 0x00 or 0xD0 <= nb <= 0xD7:
                    sp = ff + 2
                else:
                    sp = ff + 1
            break

        if pos + 4 > size:
            break
        seg_len = struct.unpack('>H', data[pos + 2:pos + 4])[0]
        if seg_len < 2 or pos + 2 + seg_len > size:
            break

        # SOF 세그먼트에서 이미지 크기 추출
        if mb in _SOF_MARKERS and mb not in CANDIDATE_FIXES and out['sof'] is None and pos + 9 < size:
            h = struct.unpack('>H', data[pos + 5:pos + 7])[0]
            w = struct.unpack('>H', data[pos + 7:pos + 9])[0]
            ncomp = data[pos + 9]
            out['sof'] = (w, h, ncomp)

        pos = pos + 2 + seg_len

    return out


def diagnose(path: Path) -> DiagnosisResult:
    """JPEG 파일을 분류해 DiagnosisResult 반환."""
    data = path.read_bytes()
    r = DiagnosisResult()
    hdr = _parse_header(data)
    r.scan_start = hdr['scan_start']
    r.has_eoi = hdr['has_eoi']
    r.sof = hdr['sof']

    # Priority 1: FALSE_POSITIVE
    sof = r.sof
    if sof is None or sof[0] == 0 or sof[1] == 0 or sof[2] == 0 or sof[2] > 4:
        r.causes.append('FALSE_POSITIVE')
        return r

    # Priority 2: MARKER_BYTE_FLIP
    # CANDIDATE_FIXES = {0xCB: 0xDB, 0xC3: 0xC0, 0xC5: 0xC4}
    # 0xCB(SOF11)은 DQT(0xDB)의 비트 플립으로 흔히 발생한다.
    # 0xC3(SOF3)과 0xC5(SOF5)는 이론적으로 유효한 JPEG 마커이지만,
    # 이 도구의 대상인 소비자 카메라 JPEG은 Baseline DCT(SOF0)만 사용하므로
    # 이를 MARKER_BYTE_FLIP으로 처리하는 것이 설계 결정이다.
    for mb in hdr['markers_seen']:
        if mb in CANDIDATE_FIXES:
            r.causes.append('MARKER_BYTE_FLIP')
            r.broken_marker = mb
            break

    if r.scan_start == -1:
        r.causes = ['FALSE_POSITIVE']
        return r

    scan = data[r.scan_start:]

    # Priority 3: BAD_STUFF
    # 스캔 데이터 내 0xFF 다음 바이트가 0x00(스터핑) 또는 RST(0xD0-0xD7),
    # EOI(0xD9)가 아닌 경우 손상된 스터핑 바이트로 간주한다.
    pos = 0
    while pos < len(scan) - 1:
        ff = scan.find(b'\xff', pos)
        if ff == -1 or ff >= len(scan) - 1:
            break
        nb = scan[ff + 1]
        if nb != 0x00 and not (0xD0 <= nb <= 0xD9):
            if r.first_bad_offset is None:
                r.first_bad_offset = ff
            if 'BAD_STUFF' not in r.causes:
                r.causes.append('BAD_STUFF')
        pos = ff + 2

    # Priority 4: GRAY_MCU — 01 45 00 14 50 4회 이상 반복
    # 회색 MCU 블록이 반복되는 패턴은 디코딩 오류나 데이터 손상을 나타낸다.
    repeat = _GRAY_MCU_PATTERN * 4
    idx = scan.find(repeat)
    if idx != -1:
        if 'GRAY_MCU' not in r.causes:
            r.causes.append('GRAY_MCU')
        r.gray_run_offset = idx
        end = idx + len(_GRAY_MCU_PATTERN)
        while (end + len(_GRAY_MCU_PATTERN) <= len(scan) and
               scan[end:end + len(_GRAY_MCU_PATTERN)] == _GRAY_MCU_PATTERN):
            end += len(_GRAY_MCU_PATTERN)
        r.gray_run_len = end - idx

    # Priority 5: ZERO_FILL
    # 스캔 데이터의 50% 이상이 0x00인 경우 의미 있는 데이터가 없는 것으로 판단한다.
    if not r.causes and len(scan) > 0:
        if scan.count(0) > len(scan) * 0.5:
            r.causes.append('ZERO_FILL')

    # Priority 6: CLEAN
    if not r.causes:
        r.causes.append('CLEAN')

    return r
