# JPEG Recovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `recover.py` + `carver/diagnosis.py` + `carver/recovery.py` 를 구현해 rawcarve가 추출한 손상 JPEG 파일을 진단·복구하고 report.csv를 생성한다.

**Architecture:** 3모듈 파이프라인. `diagnosis.py` 가 파일을 6개 원인 범주로 분류하고, `recovery.py` 가 원인별 전략을 적용한다(BAD_STUFF: FF→00 바이트 교정 우선, 실패 시 강제 디코딩+보간 폴백 / GRAY_MCU·TRUNCATED: 강제 디코딩+보간 / MARKER_BYTE_FLIP: 헤더 마커 교정 후 동일 파이프라인). `recover.py` 가 CLI 진입점과 CSV 리포트를 담당한다.

**Tech Stack:** Python 3.11+, Pillow (LOAD_TRUNCATED_IMAGES), numpy (블록 감지·보간), tqdm, csv

---

## 파일 맵

| 파일 | 작업 | 책임 |
|------|------|------|
| `carver/diagnosis.py` | 신규 | DiagnosisResult, _parse_header(), diagnose() |
| `carver/recovery.py` | 신규 | 블록 감지·보간, 원인별 복구 함수, recover_file() |
| `recover.py` | 신규 | CLI 인자 파싱, 메인 루프, CSV 리포트 |
| `tests/test_diagnosis.py` | 신규 | 진단 모듈 단위 테스트 |
| `tests/test_recovery.py` | 신규 | 복구 모듈 단위·통합 테스트 |
| `requirements.txt` | 수정 | numpy, Pillow 추가 |

---

### Task 1: DiagnosisResult + _parse_header + FALSE_POSITIVE/CLEAN

**Files:**
- Create: `carver/diagnosis.py`
- Create: `tests/test_diagnosis.py`
- Modify: `requirements.txt`

- [ ] **Step 1: requirements.txt에 의존성 추가**

`requirements.txt` 를 다음으로 교체:

```
tqdm
numpy>=1.24
Pillow>=10.0
```

- [ ] **Step 2: 실패할 테스트 작성**

```python
# tests/test_diagnosis.py
import io
import struct
import pytest
from pathlib import Path
from PIL import Image
from carver.diagnosis import DiagnosisResult, diagnose


def _make_jpeg(w=64, h=64, color=(100, 150, 200)) -> bytes:
    img = Image.new('RGB', (w, h), color=color)
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
```

- [ ] **Step 3: 테스트 실패 확인**

```
python -m pytest tests/test_diagnosis.py -v
```
Expected: `ImportError` (모듈 없음)

- [ ] **Step 4: carver/diagnosis.py 기반 구현**

```python
# carver/diagnosis.py
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
        if mb in _SOF_MARKERS and out['sof'] is None and pos + 9 < size:
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

    # Task 2에서 나머지 우선순위 구현
    r.causes.append('CLEAN')
    return r
```

- [ ] **Step 5: 테스트 통과 확인**

```
python -m pytest tests/test_diagnosis.py -v
```
Expected: 3개 모두 PASS

- [ ] **Step 6: 커밋**

```bash
git add carver/diagnosis.py tests/test_diagnosis.py requirements.txt
git commit -m "feat: DiagnosisResult 데이터클래스 및 FALSE_POSITIVE 진단 구현"
```

---

### Task 2: 진단 완성 — MARKER_BYTE_FLIP / BAD_STUFF / GRAY_MCU / ZERO_FILL

**Files:**
- Modify: `carver/diagnosis.py` (diagnose() 완성)
- Modify: `tests/test_diagnosis.py` (4개 테스트 추가)

- [ ] **Step 1: 실패할 테스트 추가**

`tests/test_diagnosis.py` 하단에 추가:

```python
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
```

- [ ] **Step 2: 테스트 실패 확인**

```
python -m pytest tests/test_diagnosis.py::test_marker_byte_flip tests/test_diagnosis.py::test_bad_stuff tests/test_diagnosis.py::test_gray_mcu tests/test_diagnosis.py::test_zero_fill -v
```
Expected: 4개 모두 FAIL (diagnose가 CLEAN 반환)

- [ ] **Step 3: diagnose() 완성 — CLEAN 플레이스홀더를 전체 우선순위 체인으로 교체**

`carver/diagnosis.py` 의 `diagnose()` 함수 전체를 다음으로 교체:

```python
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
    for mb in hdr['markers_seen']:
        if mb in CANDIDATE_FIXES:
            r.causes.append('MARKER_BYTE_FLIP')
            r.broken_marker = mb
            break

    if r.scan_start == -1:
        r.causes.append('FALSE_POSITIVE')
        return r

    scan = data[r.scan_start:]

    # Priority 3: BAD_STUFF
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
    if not r.causes and len(scan) > 0:
        if scan.count(0) > len(scan) * 0.5:
            r.causes.append('ZERO_FILL')

    # Priority 6: CLEAN
    if not r.causes:
        r.causes.append('CLEAN')

    return r
```

- [ ] **Step 4: 전체 테스트 통과 확인**

```
python -m pytest tests/test_diagnosis.py -v
```
Expected: 7개 모두 PASS

- [ ] **Step 5: 커밋**

```bash
git add carver/diagnosis.py tests/test_diagnosis.py
git commit -m "feat: 진단 모듈 완성 (BAD_STUFF, GRAY_MCU, MARKER_BYTE_FLIP, ZERO_FILL)"
```

---

### Task 3: 복구 유틸리티 — 손상 블록 감지 + 보간

**Files:**
- Create: `carver/recovery.py`
- Create: `tests/test_recovery.py`

- [ ] **Step 1: 실패할 테스트 작성**

```python
# tests/test_recovery.py
import io
import numpy as np
import pytest
from PIL import Image
from carver.recovery import detect_damaged_blocks, interpolate_damaged_blocks


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
```

- [ ] **Step 2: 테스트 실패 확인**

```
python -m pytest tests/test_recovery.py -v
```
Expected: `ImportError`

- [ ] **Step 3: carver/recovery.py 구현**

```python
# carver/recovery.py
from __future__ import annotations
import io
from pathlib import Path

import numpy as np
from PIL import Image, ImageFile

ImageFile.LOAD_TRUNCATED_IMAGES = True

_MAX_RADIUS = 16


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


def interpolate_damaged_blocks(arr: np.ndarray, damaged: np.ndarray) -> np.ndarray:
    """손상 블록을 유효 이웃 블록의 거리 역수 가중 평균으로 채운다."""
    result = arr.copy()
    bh, bw = damaged.shape
    is_rgb = arr.ndim == 3
    channels = arr.shape[2] if is_rgb else 1

    for by, bx in zip(*np.where(damaged)):
        by, bx = int(by), int(bx)
        r1, r2 = max(0, by - _MAX_RADIUS), min(bh, by + _MAX_RADIUS + 1)
        c1, c2 = max(0, bx - _MAX_RADIUS), min(bw, bx + _MAX_RADIUS + 1)

        total_w = 0.0
        weighted = np.zeros(channels, dtype=np.float64)

        for ny in range(r1, r2):
            for nx in range(c1, c2):
                if damaged[ny, nx]:
                    continue
                dist = ((ny - by) ** 2 + (nx - bx) ** 2) ** 0.5
                if dist == 0:
                    continue
                w = 1.0 / dist
                block = arr[ny * 8:(ny + 1) * 8, nx * 8:(nx + 1) * 8]
                weighted += w * (block.mean(axis=(0, 1)) if is_rgb else [block.mean()])
                total_w += w

        if total_w > 0:
            fill = np.clip(weighted / total_w, 0, 255).astype(np.uint8)
            if is_rgb:
                result[by * 8:(by + 1) * 8, bx * 8:(bx + 1) * 8] = fill
            else:
                result[by * 8:(by + 1) * 8, bx * 8:(bx + 1) * 8] = fill[0]

    return result
```

- [ ] **Step 4: 테스트 통과 확인**

```
python -m pytest tests/test_recovery.py -v
```
Expected: 5개 모두 PASS

- [ ] **Step 5: 커밋**

```bash
git add carver/recovery.py tests/test_recovery.py
git commit -m "feat: 손상 블록 감지 및 보간 유틸리티 구현"
```

---

### Task 4: BAD_STUFF 복구 보조 함수

**Files:**
- Modify: `carver/recovery.py` (_collect_violations, _patch_bad_stuff, _force_decode_arr 추가)
- Modify: `tests/test_recovery.py` (4개 테스트 추가)

- [ ] **Step 1: 실패할 테스트 추가**

`tests/test_recovery.py` 하단에 추가:

```python
from carver.recovery import _collect_violations, _patch_bad_stuff, _force_decode_arr


def _make_jpeg(w=64, h=64, color=(100, 150, 200)) -> bytes:
    img = Image.new('RGB', (w, h), color=color)
    buf = io.BytesIO()
    img.save(buf, format='JPEG', quality=85)
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
```

- [ ] **Step 2: 테스트 실패 확인**

```
python -m pytest tests/test_recovery.py::test_collect_violations tests/test_recovery.py::test_patch_removes_all_violations tests/test_recovery.py::test_force_decode_clean tests/test_recovery.py::test_force_decode_corrupted -v
```
Expected: `ImportError`

- [ ] **Step 3: carver/recovery.py 에 보조 함수 추가**

`interpolate_damaged_blocks` 함수 아래에 추가:

```python
def _collect_violations(data: bytes, scan_start: int) -> list[int]:
    """스캔 데이터에서 FF XX (XX != 00, D0-D9) 위치 목록을 반환 (절대 오프셋)."""
    violations: list[int] = []
    pos = scan_start
    size = len(data)
    while pos < size - 1:
        ff = data.find(b'\xff', pos)
        if ff == -1 or ff >= size - 1:
            break
        nb = data[ff + 1]
        if nb != 0x00 and not (0xD0 <= nb <= 0xD9):
            violations.append(ff)
            pos = ff + 2
        else:
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
    buf = io.BytesIO()
    Image.fromarray(arr).save(buf, format='JPEG', quality=quality)
    return buf.getvalue()
```

- [ ] **Step 4: 테스트 통과 확인**

```
python -m pytest tests/test_recovery.py -v
```
Expected: 9개 모두 PASS

- [ ] **Step 5: 커밋**

```bash
git add carver/recovery.py tests/test_recovery.py
git commit -m "feat: BAD_STUFF 교정 보조 함수 구현 (collect, patch, force_decode)"
```

---

### Task 5: 원인별 복구 함수 + recover_file() 오케스트레이터

**Files:**
- Modify: `carver/recovery.py` (_recover_bad_stuff, _recover_interpolate_only, _recover_marker_flip, recover_file 추가)
- Modify: `tests/test_recovery.py` (4개 테스트 추가)

- [ ] **Step 1: 실패할 테스트 추가**

`tests/test_recovery.py` 하단에 추가:

```python
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
```

- [ ] **Step 2: 테스트 실패 확인**

```
python -m pytest tests/test_recovery.py::test_recover_file_bad_stuff tests/test_recovery.py::test_recover_file_clean tests/test_recovery.py::test_recover_file_false_positive tests/test_recovery.py::test_recover_file_marker_flip -v
```
Expected: `ImportError`

- [ ] **Step 3: 복구 함수들 + recover_file() 구현**

`_arr_to_jpeg` 함수 아래에 추가:

```python
from carver.diagnosis import CANDIDATE_FIXES as _FIXES


def _recover_bad_stuff(data: bytes, scan_start: int, out_path: Path) -> str:
    """FF->00 교정 시도 후 실패 시 강제 디코딩+보간으로 폴백.

    Returns: RECOVERED_PATCHED | RECOVERED_INTERPOLATED | SKIP_TOO_DAMAGED
    """
    if scan_start == -1:
        return 'SKIP_TOO_DAMAGED'

    violations = _collect_violations(data, scan_start)

    if violations:
        patched = _patch_bad_stuff(data, violations)
        arr = _force_decode_arr(patched)
        if arr is not None:
            damaged = detect_damaged_blocks(arr)
            pct = float(damaged.mean())
            if pct < 0.90:
                if pct >= 0.10:
                    arr = interpolate_damaged_blocks(arr, damaged)
                out_path.write_bytes(_arr_to_jpeg(arr))
                return 'RECOVERED_PATCHED'

    arr = _force_decode_arr(data)
    if arr is None:
        return 'SKIP_TOO_DAMAGED'
    damaged = detect_damaged_blocks(arr)
    if float(damaged.mean()) >= 0.90:
        return 'SKIP_TOO_DAMAGED'
    arr = interpolate_damaged_blocks(arr, damaged)
    out_path.write_bytes(_arr_to_jpeg(arr))
    return 'RECOVERED_INTERPOLATED'


def _recover_interpolate_only(data: bytes, out_path: Path) -> str:
    """강제 디코딩 후 보간. GRAY_MCU / TRUNCATED_SCAN 용."""
    arr = _force_decode_arr(data)
    if arr is None:
        return 'SKIP_TOO_DAMAGED'
    damaged = detect_damaged_blocks(arr)
    if float(damaged.mean()) >= 0.90:
        return 'SKIP_TOO_DAMAGED'
    arr = interpolate_damaged_blocks(arr, damaged)
    out_path.write_bytes(_arr_to_jpeg(arr))
    return 'RECOVERED_INTERPOLATED'


def _recover_marker_flip(data: bytes, diagnosis, out_path: Path) -> str:
    """헤더 마커 바이트 교정 후 BAD_STUFF 파이프라인 적용."""
    fix = _FIXES.get(diagnosis.broken_marker)
    if fix is None:
        return 'SKIP_TOO_DAMAGED'
    patched = bytearray(data)
    for i in range(len(patched) - 1):
        if patched[i] == 0xFF and patched[i + 1] == diagnosis.broken_marker:
            patched[i + 1] = fix
            break
    from carver.diagnosis import _parse_header
    new_scan = _parse_header(bytes(patched))['scan_start']
    return _recover_bad_stuff(bytes(patched), new_scan, out_path)


def recover_file(
    src_path: Path,
    diagnosis,
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
        elif 'BAD_STUFF' in causes:
            action = _recover_bad_stuff(data, diagnosis.scan_start, out_path)
        else:
            action = _recover_interpolate_only(data, out_path)
    except Exception:
        return None, 'ERROR'

    if action.startswith('SKIP'):
        return None, action
    return out_path, action
```

- [ ] **Step 4: 전체 테스트 통과 확인**

```
python -m pytest tests/test_recovery.py -v
```
Expected: 13개 모두 PASS

- [ ] **Step 5: 커밋**

```bash
git add carver/recovery.py tests/test_recovery.py
git commit -m "feat: 원인별 복구 함수 및 recover_file() 오케스트레이터 구현"
```

---

### Task 6: recover.py CLI 진입점

**Files:**
- Create: `recover.py`
- Modify: `tests/test_recovery.py` (CLI 스모크 테스트 추가)

- [ ] **Step 1: 실패할 스모크 테스트 추가**

`tests/test_recovery.py` 하단에 추가:

```python
import csv
import subprocess
import sys


def test_recover_cli_smoke(tmp_path):
    src = tmp_path / 'jpeg'
    src.mkdir()
    out = tmp_path / 'jpeg_recovered'
    for i in range(3):
        (src / f'0x{i:08X}.jpg').write_bytes(_make_jpeg())
    result = subprocess.run(
        [sys.executable, 'recover.py', str(src), '-o', str(out)],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    report = out / 'report.csv'
    assert report.exists()
    rows = list(csv.DictReader(report.read_text(encoding='utf-8').splitlines()))
    assert len(rows) == 3
    assert all(r['action'] == 'CLEAN' for r in rows)
    assert rows[0]['filename'].endswith('.jpg')
```

- [ ] **Step 2: 테스트 실패 확인**

```
python -m pytest tests/test_recovery.py::test_recover_cli_smoke -v
```
Expected: `FileNotFoundError` (recover.py 없음)

- [ ] **Step 3: recover.py 구현**

```python
# recover.py
from __future__ import annotations
import argparse
import csv
import sys
from pathlib import Path

from tqdm import tqdm

from carver.diagnosis import diagnose
from carver.recovery import detect_damaged_blocks, recover_file, _force_decode_arr


def _damage_pct(data: bytes) -> float:
    arr = _force_decode_arr(data)
    if arr is None:
        return 0.0
    return float(detect_damaged_blocks(arr).mean())


def main() -> None:
    parser = argparse.ArgumentParser(
        description='rawcarve가 추출한 JPEG 파일을 복구합니다.'
    )
    parser.add_argument('input', help='입력 디렉토리 (output/jpeg/)')
    parser.add_argument('-o', '--output', default=None,
                        help='출력 디렉토리 (기본: <input>_recovered)')
    args = parser.parse_args()

    in_dir = Path(args.input)
    if not in_dir.is_dir():
        print(f'오류: 디렉토리를 찾을 수 없습니다: {in_dir}', file=sys.stderr)
        sys.exit(1)

    out_dir = (Path(args.output) if args.output
               else in_dir.parent / (in_dir.name + '_recovered'))
    out_dir.mkdir(parents=True, exist_ok=True)

    jpeg_files = sorted(in_dir.glob('*.jpg'))
    if not jpeg_files:
        print('JPEG 파일을 찾을 수 없습니다.')
        return

    fieldnames = [
        'filename', 'causes', 'action',
        'damaged_block_pct', 'recovered_block_pct',
        'cut_offset_kb', 'image_size',
    ]
    counts: dict[str, int] = {}

    with open(out_dir / 'report.csv', 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()

        for path in tqdm(jpeg_files, desc='복구 중', unit='파일'):
            row: dict = {k: '' for k in fieldnames}
            row['filename'] = path.name
            try:
                dr = diagnose(path)
                row['causes'] = ';'.join(dr.causes)

                before_pct = _damage_pct(path.read_bytes())
                result_path, action = recover_file(path, dr, out_dir)
                row['action'] = action

                after_pct = 0.0
                if result_path is not None and result_path.exists():
                    after_pct = _damage_pct(result_path.read_bytes())

                row['damaged_block_pct'] = f'{before_pct:.3f}'
                row['recovered_block_pct'] = f'{after_pct:.3f}'

                if dr.sof:
                    row['image_size'] = f'{dr.sof[0]}x{dr.sof[1]}'
                if dr.first_bad_offset is not None and dr.scan_start >= 0:
                    kb = (dr.scan_start + dr.first_bad_offset) / 1024
                    row['cut_offset_kb'] = f'{kb:.1f}'

            except Exception as e:
                row['action'] = 'ERROR'
                row['causes'] = 'ERROR'
                tqdm.write(f'[ERROR] {path.name}: {e}')

            writer.writerow(row)
            counts[row['action']] = counts.get(row['action'], 0) + 1
            if row['action'] not in ('CLEAN',):
                tqdm.write(f"[{row['action']}] {path.name}")

    print(f"\n완료. 리포트: {out_dir / 'report.csv'}")
    for action, cnt in sorted(counts.items()):
        print(f'  {action}: {cnt}개')


if __name__ == '__main__':
    main()
```

- [ ] **Step 4: 전체 테스트 통과 확인**

```
python -m pytest tests/test_recovery.py tests/test_diagnosis.py -v
```
Expected: 전체 PASS

- [ ] **Step 5: 실제 데이터로 수동 검증 (output/jpeg/ 디렉토리가 있을 때)**

```
python recover.py output/jpeg/ -o output/jpeg_recovered/
```

확인 항목:
- `output/jpeg_recovered/report.csv` 생성 여부
- RECOVERED_PATCHED / RECOVERED_INTERPOLATED 파일이 이미지 뷰어에서 정상 표시되는지
- FALSE_POSITIVE 파일이 `jpeg_recovered/` 에 생성되지 않는지

- [ ] **Step 6: 커밋**

```bash
git add recover.py tests/test_recovery.py
git commit -m "feat: recover.py CLI 진입점 및 CSV 리포트 구현"
```

---

## 자기 검토 결과

**스펙 커버리지:**
- [x] FALSE_POSITIVE 건너뜀 → Task 1, 5
- [x] MARKER_BYTE_FLIP 교정 → Task 2, 5
- [x] BAD_STUFF FF→00 패치 우선 → Task 4, 5
- [x] GRAY_MCU / TRUNCATED_SCAN 강제 디코딩+보간 → Task 5
- [x] ZERO_FILL 건너뜀 → Task 2, 5
- [x] 손상 블록 90% 이상 → SKIP_TOO_DAMAGED → Task 5
- [x] RECOVERED_PATCHED / RECOVERED_INTERPOLATED 구분 → Task 5, 6
- [x] report.csv 7개 컬럼 → Task 6
- [x] carve.py 미수정 → 별도 모듈로 분리

**타입 일관성:**
- `DiagnosisResult.scan_start`: `int` (기본값 -1)
- `_recover_bad_stuff(data, scan_start: int, out_path)` — Task 5 내 모두 `diagnosis.scan_start` 전달
- `recover_file` 반환: `tuple[Path | None, str]`

**플레이스홀더 없음:** 모든 스텝에 실제 코드 포함.
