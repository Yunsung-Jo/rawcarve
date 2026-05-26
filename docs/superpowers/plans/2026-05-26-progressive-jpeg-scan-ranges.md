# Progressive JPEG 다중 스캔 지원 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `_parse_header`가 Progressive JPEG의 모든 SOS 스캔 범위를 파악하고, `_collect_violations`가 각 스캔 범위 안에서만 위반을 탐지하도록 수정하여 스캔 경계 마커(`FF DA` 등)가 BAD_STUFF로 오탐되어 패치되는 버그를 제거한다.

**Architecture:** `_find_scan_end`가 스캔 데이터의 끝을 식별하고, `_parse_header`가 이를 이용해 모든 SOS 스캔 범위를 `scan_ranges`로 반환한다. `DiagnosisResult.scan_ranges`에 저장되어 `_collect_violations`와 `diagnose()` BAD_STUFF 탐지 모두 이 범위 안에서만 동작하도록 바뀐다.

**Tech Stack:** Python 3.10+, pytest, Pillow, numpy

---

## 파일 구조

| 파일 | 변경 종류 | 내용 |
|---|---|---|
| `carver/diagnosis.py` | 수정 | `_SCAN_BOUNDARY_MARKERS`, `_find_scan_end`, `_parse_header` 다중 SOS, `DiagnosisResult.scan_ranges`, `diagnose()` BAD_STUFF 범위 제한 |
| `carver/recovery.py` | 수정 | `_collect_violations` 시그니처, `_recover_bad_stuff` 파라미터, `_recover_marker_flip`·`recover_file` 호출부 |
| `tests/test_diagnosis.py` | 수정 | `_find_scan_end` 테스트, Progressive JPEG `scan_ranges` 테스트, BAD_STUFF 오탐 방지 테스트 추가 |
| `tests/test_recovery.py` | 수정 | `_corrupt` 헬퍼 반환값 변경, `_collect_violations` 호출 시그니처 업데이트 |

---

## Task 1: `_find_scan_end` 구현

**Files:**
- Modify: `carver/diagnosis.py`
- Test: `tests/test_diagnosis.py`

### 설계 메모

`_find_scan_end(data, start)`는 `start`부터 순회하며 `FF XX`를 만날 때:
- XX == `0x00` 또는 `D0`–`D7`: 스터핑/RST → 계속 (`pos += 2`)
- XX == `0xFF`: fill 바이트 → 계속 (`pos += 1`)
- XX in `_SCAN_BOUNDARY_MARKERS` (`{0xC4, 0xD8, 0xD9, 0xDA, 0xDB, 0xDD, 0xFE}`): 다음 세그먼트 시작 → `ff` 반환
- 그 외 (비트 플립 등): 위반이지만 스캔 경계 아님 → 계속 (`pos += 2`)

없으면 `len(data)` 반환.

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_diagnosis.py` 끝에 추가:

```python
from carver.diagnosis import _find_scan_end


def test_find_scan_end_stops_at_sda():
    # FF 00 FF 00 FF DA ... 구조에서 FF DA 위치를 반환해야 한다
    data = bytes([0xFF, 0x00, 0xFF, 0x00, 0xFF, 0xDA, 0x00, 0x0C])
    assert _find_scan_end(data, 0) == 4


def test_find_scan_end_skips_violations():
    # FF EC (위반)는 경계가 아니므로 건너뛰고, 이후 FF D9에서 종료해야 한다
    data = bytes([0xFF, 0x00, 0xFF, 0xEC, 0xFF, 0xD9])
    assert _find_scan_end(data, 0) == 4


def test_find_scan_end_no_boundary():
    # 경계 마커 없으면 len(data) 반환
    data = bytes([0xFF, 0x00, 0xAB, 0xCD])
    assert _find_scan_end(data, 0) == len(data)


def test_find_scan_end_rst_continues():
    # FF D5 (RST5)는 스캔 데이터의 일부이므로 계속 진행해야 한다
    data = bytes([0xFF, 0xD5, 0xFF, 0xDA])
    assert _find_scan_end(data, 0) == 2
```

- [ ] **Step 2: 테스트 실행 — 실패 확인**

```
pytest tests/test_diagnosis.py::test_find_scan_end_stops_at_sda -v
```

Expected: `ImportError: cannot import name '_find_scan_end'` 또는 `AttributeError`

- [ ] **Step 3: `_SCAN_BOUNDARY_MARKERS`와 `_find_scan_end` 구현**

`carver/diagnosis.py`의 기존 상수 블록(`_NO_LEN`, `_SOF_MARKERS`, `CANDIDATE_FIXES`, `_GRAY_MCU_PATTERN`) 아래에 추가:

```python
_SCAN_BOUNDARY_MARKERS = frozenset([0xC4, 0xD8, 0xD9, 0xDA, 0xDB, 0xDD, 0xFE])


def _find_scan_end(data: bytes, start: int) -> int:
    """스캔 데이터의 끝 위치(다음 세그먼트 FF 바이트)를 반환한다.

    start부터 FF XX 시퀀스를 순회한다:
    - XX 00 또는 D0-D7: 스터핑/RST, 스캔의 일부 → 계속
    - XX FF: fill 바이트 → 계속
    - XX in _SCAN_BOUNDARY_MARKERS: 다음 세그먼트 → FF 위치 반환
    - 그 외: 비트 플립 등 위반, 스캔 경계 아님 → 계속
    경계 없으면 len(data) 반환.
    """
    size = len(data)
    pos = start
    while pos < size - 1:
        ff = data.find(b'\xff', pos)
        if ff == -1 or ff >= size - 1:
            break
        nb = data[ff + 1]
        if nb == 0xFF:
            pos = ff + 1
        elif nb == 0x00 or (0xD0 <= nb <= 0xD7):
            pos = ff + 2
        elif nb in _SCAN_BOUNDARY_MARKERS:
            return ff
        else:
            pos = ff + 2
    return len(data)
```

- [ ] **Step 4: 테스트 실행 — 통과 확인**

```
pytest tests/test_diagnosis.py::test_find_scan_end_stops_at_sda tests/test_diagnosis.py::test_find_scan_end_skips_violations tests/test_diagnosis.py::test_find_scan_end_no_boundary tests/test_diagnosis.py::test_find_scan_end_rst_continues -v
```

Expected: 4개 PASS

- [ ] **Step 5: 커밋**

```
git add carver/diagnosis.py tests/test_diagnosis.py
git commit -m "feat: _find_scan_end 구현 — 스캔 경계와 위반을 구분한다"
```

---

## Task 2: `_parse_header` 다중 SOS 파싱 + `DiagnosisResult.scan_ranges`

**Files:**
- Modify: `carver/diagnosis.py`
- Test: `tests/test_diagnosis.py`

### 설계 메모

`_parse_header`의 SOS 처리 블록에서 `break`를 제거하고 `_find_scan_end`로 스캔 끝을 구해 `scan_ranges`에 추가한다. 파싱은 `scan_data_end`부터 계속된다. `scan_start`는 첫 번째 SOS 스캔 시작으로 유지(하위 호환).

`DiagnosisResult`에 `scan_ranges: list[tuple[int, int]] = field(default_factory=list)` 추가.

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_diagnosis.py`에 추가:

```python
def _make_progressive_jpeg(w=128, h=128) -> bytes:
    import numpy as np
    rng = np.random.default_rng(seed=7)
    arr = rng.integers(0, 256, (h, w, 3), dtype=np.uint8)
    img = Image.fromarray(arr, mode='RGB')
    buf = io.BytesIO()
    img.save(buf, format='JPEG', progressive=True, quality=85)
    return buf.getvalue()


def test_parse_header_progressive_has_scan_ranges():
    from carver.diagnosis import _parse_header
    data = _make_progressive_jpeg()
    hdr = _parse_header(data)
    # Progressive JPEG는 여러 SOS를 가진다
    assert len(hdr['scan_ranges']) >= 2
    # 각 범위의 start < end 이어야 한다
    for start, end in hdr['scan_ranges']:
        assert start < end
    # scan_start는 여전히 첫 번째 스캔 시작을 가리켜야 한다
    assert hdr['scan_start'] == hdr['scan_ranges'][0][0]


def test_parse_header_baseline_has_one_scan_range():
    from carver.diagnosis import _parse_header
    data = _make_jpeg()  # 기존 헬퍼: baseline JPEG
    hdr = _parse_header(data)
    assert len(hdr['scan_ranges']) == 1
    assert hdr['scan_ranges'][0][0] == hdr['scan_start']


def test_diagnose_progressive_has_scan_ranges():
    from pathlib import Path
    import tempfile
    data = _make_progressive_jpeg()
    with tempfile.NamedTemporaryFile(suffix='.jpg', delete=False) as f:
        f.write(data)
        p = Path(f.name)
    try:
        r = diagnose(p)
        assert len(r.scan_ranges) >= 2
    finally:
        p.unlink()
```

- [ ] **Step 2: 테스트 실행 — 실패 확인**

```
pytest tests/test_diagnosis.py::test_parse_header_progressive_has_scan_ranges -v
```

Expected: `KeyError: 'scan_ranges'` 또는 `AssertionError`

- [ ] **Step 3: `DiagnosisResult`에 `scan_ranges` 필드 추가**

`carver/diagnosis.py`의 `DiagnosisResult` 데이터클래스에 추가:

```python
@dataclass
class DiagnosisResult:
    causes: list[str] = field(default_factory=list)
    first_bad_offset: int | None = None
    gray_run_offset: int | None = None
    gray_run_len: int = 0
    scan_start: int = -1
    has_eoi: bool = False
    sof: tuple[int, int, int] | None = None
    broken_marker: int | None = None
    scan_ranges: list[tuple[int, int]] = field(default_factory=list)  # 추가
```

- [ ] **Step 4: `_parse_header` 반환 dict에 `scan_ranges` 초기화**

`_parse_header`의 `out` 초기화 블록 수정:

```python
out: dict = {
    'sof': None,
    'scan_start': -1,
    'scan_ranges': [],      # 추가
    'has_eoi': False,
    'markers_seen': [],
}
```

- [ ] **Step 5: `_parse_header`의 SOS 처리 블록 교체**

기존 SOS 처리 블록 전체(`if mb == 0xDA:` 부터 `break`까지)를 다음으로 교체:

```python
        if mb == 0xDA:  # SOS
            pos += 2
            if pos + 2 > size:
                break
            sos_len = struct.unpack('>H', data[pos:pos + 2])[0]
            scan_data_start = pos + sos_len
            if out['scan_start'] == -1:
                out['scan_start'] = scan_data_start
            scan_data_end = _find_scan_end(data, scan_data_start)
            out['scan_ranges'].append((scan_data_start, scan_data_end))
            pos = scan_data_end
            continue
```

- [ ] **Step 6: `diagnose()`에서 `scan_ranges` 저장**

`diagnose()`의 `hdr = _parse_header(data)` 이후 블록에 추가:

```python
    hdr = _parse_header(data)
    r.scan_start = hdr['scan_start']
    r.has_eoi = hdr['has_eoi']
    r.sof = hdr['sof']
    r.scan_ranges = hdr['scan_ranges']   # 추가
```

- [ ] **Step 7: 테스트 실행 — 통과 확인**

```
pytest tests/test_diagnosis.py::test_parse_header_progressive_has_scan_ranges tests/test_diagnosis.py::test_parse_header_baseline_has_one_scan_range tests/test_diagnosis.py::test_diagnose_progressive_has_scan_ranges -v
```

Expected: 3개 PASS

- [ ] **Step 8: 전체 기존 테스트 통과 확인**

```
pytest tests/test_diagnosis.py -v
```

Expected: 전체 PASS

- [ ] **Step 9: 커밋**

```
git add carver/diagnosis.py tests/test_diagnosis.py
git commit -m "feat: _parse_header 다중 SOS 파싱 및 DiagnosisResult.scan_ranges 추가"
```

---

## Task 3: `diagnose()` BAD_STUFF 탐지 범위 제한

**Files:**
- Modify: `carver/diagnosis.py`
- Test: `tests/test_diagnosis.py`

### 설계 메모

현재 `diagnose()`의 BAD_STUFF 탐지는 `data[r.scan_start:]` 전체에서 `FF XX`를 찾는다. Progressive JPEG에서는 `FF DA` 등 스캔 경계 마커가 이 범위에 포함되어 BAD_STUFF로 오탐된다. 이를 `r.scan_ranges` 각 범위 안에서만 탐지하도록 교체한다.

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_diagnosis.py`에 추가:

```python
def test_diagnose_progressive_scan_boundary_not_bad_stuff(tmp_path):
    """Progressive JPEG의 스캔 경계 마커(FF DA)가 BAD_STUFF로 탐지되면 안 된다."""
    data = _make_progressive_jpeg()
    # 원본 Progressive JPEG은 스캔 경계에 FF DA가 있지만 BAD_STUFF가 아니어야 한다
    p = tmp_path / 'prog.jpg'
    p.write_bytes(data)
    r = diagnose(p)
    assert 'BAD_STUFF' not in r.causes
    assert r.causes == ['CLEAN']
```

- [ ] **Step 2: 테스트 실행 — 실패 확인**

```
pytest tests/test_diagnosis.py::test_diagnose_progressive_scan_boundary_not_bad_stuff -v
```

Expected: `AssertionError` — 현재 코드는 `FF DA`를 BAD_STUFF로 탐지한다.

- [ ] **Step 3: `diagnose()`의 BAD_STUFF 탐지 블록 교체**

기존 BAD_STUFF 탐지 블록 전체를:

```python
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
```

다음으로 교체:

```python
    # Priority 3: BAD_STUFF — 각 스캔 범위 안에서만 FF XX 위반을 탐지한다.
    for scan_s, scan_e in r.scan_ranges:
        pos = scan_s
        while pos < scan_e - 1:
            ff = data.find(b'\xff', pos, scan_e)
            if ff == -1:
                break
            nb = data[ff + 1]
            if nb != 0x00 and not (0xD0 <= nb <= 0xD9):
                if r.first_bad_offset is None:
                    r.first_bad_offset = ff - r.scan_start
                if 'BAD_STUFF' not in r.causes:
                    r.causes.append('BAD_STUFF')
            pos = ff + 2
```

- [ ] **Step 4: 테스트 실행 — 통과 확인**

```
pytest tests/test_diagnosis.py::test_diagnose_progressive_scan_boundary_not_bad_stuff -v
```

Expected: PASS

- [ ] **Step 5: 전체 `test_diagnosis.py` 통과 확인**

```
pytest tests/test_diagnosis.py -v
```

Expected: 전체 PASS

- [ ] **Step 6: 커밋**

```
git add carver/diagnosis.py tests/test_diagnosis.py
git commit -m "fix: diagnose() BAD_STUFF 탐지를 scan_ranges 범위 내로 제한한다"
```

---

## Task 4: `_collect_violations` 시그니처 변경 + 호출부 수정

**Files:**
- Modify: `carver/recovery.py`
- Modify: `tests/test_recovery.py`

### 설계 메모

`_collect_violations(data, scan_start: int)` → `_collect_violations(data, scan_ranges: list[tuple[int, int]])`.

`_recover_bad_stuff`와 `_recover_marker_flip`, `recover_file`도 함께 수정.

기존 테스트 `test_collect_violations`, `test_patch_removes_all_violations`의 `_corrupt` 헬퍼 반환값을 `(data, scan_ranges)` 형태로 변경.

- [ ] **Step 1: 실패하는 새 테스트 작성**

`tests/test_recovery.py`에 추가:

```python
import io
from PIL import Image


def _make_progressive_jpeg_recovery(w=128, h=128) -> bytes:
    rng = np.random.default_rng(seed=9)
    arr = rng.integers(0, 256, (w, h, 3), dtype=np.uint8)
    img = Image.fromarray(arr, mode='RGB')
    buf = io.BytesIO()
    img.save(buf, format='JPEG', progressive=True, quality=85)
    return buf.getvalue()


def test_collect_violations_progressive_skips_scan_boundary():
    """Progressive JPEG의 스캔 경계 FF DA는 위반으로 탐지되면 안 된다."""
    from carver.diagnosis import _parse_header
    data = _make_progressive_jpeg_recovery()
    hdr = _parse_header(data)
    scan_ranges = hdr['scan_ranges']
    assert len(scan_ranges) >= 2  # 최소 2개 스캔 확인
    viols = _collect_violations(data, scan_ranges)
    # 정상 Progressive JPEG에는 위반이 없어야 한다
    assert len(viols) == 0


def test_collect_violations_detects_bitflip_in_scan():
    """스캔 범위 내 FF EC 위반은 탐지되어야 한다."""
    from carver.diagnosis import _parse_header
    data = _make_progressive_jpeg_recovery()
    hdr = _parse_header(data)
    scan_ranges = hdr['scan_ranges']
    # 마지막 스캔의 FF 00 하나를 FF EC로 교체
    arr = bytearray(data)
    last_s, last_e = scan_ranges[-1]
    for i in range(last_s, last_e - 1):
        if arr[i] == 0xFF and arr[i + 1] == 0x00:
            arr[i + 1] = 0xEC
            break
    corrupted = bytes(arr)
    new_ranges = _parse_header(corrupted)['scan_ranges']
    viols = _collect_violations(corrupted, new_ranges)
    assert len(viols) >= 1
```

- [ ] **Step 2: 테스트 실행 — 실패 확인**

```
pytest tests/test_recovery.py::test_collect_violations_progressive_skips_scan_boundary -v
```

Expected: `TypeError: _collect_violations() argument 2 must be int, not list` (시그니처 변경 전)

- [ ] **Step 3: `tests/test_recovery.py`의 `_corrupt` 헬퍼 반환값 변경**

`_corrupt` 함수를 다음으로 교체:

```python
def _corrupt(data: bytes, count: int = 1) -> tuple[bytes, list[tuple[int, int]]]:
    """스캔 데이터 내 FF 00 을 count개 FF EC 로 교체. (patched_data, scan_ranges) 반환."""
    from carver.diagnosis import _parse_header
    hdr = _parse_header(data)
    scan_ranges = hdr['scan_ranges']
    ss = hdr['scan_start']
    arr = bytearray(data)
    found = 0
    for i in range(ss, len(arr) - 1):
        if arr[i] == 0xFF and arr[i + 1] == 0x00:
            arr[i + 1] = 0xEC
            found += 1
            if found >= count:
                break
    return bytes(arr), scan_ranges
```

- [ ] **Step 4: 기존 테스트의 `_collect_violations` 호출 업데이트**

`tests/test_recovery.py`에서 다음 두 테스트를 수정:

```python
def test_collect_violations():
    data, scan_ranges = _corrupt(_make_jpeg(), count=3)
    viols = _collect_violations(data, scan_ranges)
    assert len(viols) >= 3


def test_patch_removes_all_violations():
    data, scan_ranges = _corrupt(_make_jpeg(), count=2)
    viols = _collect_violations(data, scan_ranges)
    patched = _patch_bad_stuff(data, viols)
    new_ranges = scan_ranges  # 패치 후 범위는 동일
    assert len(_collect_violations(patched, new_ranges)) == 0
```

- [ ] **Step 5: `_collect_violations` 시그니처 변경**

`carver/recovery.py`의 `_collect_violations`를 다음으로 교체:

```python
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
```

- [ ] **Step 6: `_recover_bad_stuff` 시그니처 변경**

`carver/recovery.py`의 `_recover_bad_stuff`를 다음으로 교체:

```python
def _recover_bad_stuff(
    data: bytes,
    scan_ranges: list[tuple[int, int]],
    out_path: Path,
) -> str:
    """FF->00 교정 시도 후 실패 시 강제 디코딩+보간으로 폴백.

    Returns: RECOVERED_PATCHED | RECOVERED_INTERPOLATED | SKIP_TOO_DAMAGED
    """
    if not scan_ranges:
        return 'SKIP_TOO_DAMAGED'

    violations = _collect_violations(data, scan_ranges)

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
```

- [ ] **Step 7: `_recover_marker_flip` 호출부 수정**

`carver/recovery.py`의 `_recover_marker_flip`에서:

```python
    fixed = bytes(patched)
    new_scan = _parse_header(fixed)['scan_start']
    return _recover_bad_stuff(fixed, new_scan, out_path)
```

를:

```python
    fixed = bytes(patched)
    new_hdr = _parse_header(fixed)
    return _recover_bad_stuff(fixed, new_hdr['scan_ranges'], out_path)
```

로 교체.

- [ ] **Step 8: `recover_file` 호출부 수정**

`carver/recovery.py`의 `recover_file` 함수에서 `_recover_bad_stuff` 호출 두 곳을 수정:

```python
    try:
        if 'MARKER_BYTE_FLIP' in causes:
            action = _recover_marker_flip(data, diagnosis, out_path)
            if action == 'SKIP_TOO_DAMAGED' and 'BAD_STUFF' in causes:
                action = _recover_bad_stuff(data, diagnosis.scan_ranges, out_path)
        elif 'BAD_STUFF' in causes:
            action = _recover_bad_stuff(data, diagnosis.scan_ranges, out_path)
        else:
            action = _recover_interpolate_only(data, out_path)
```

- [ ] **Step 9: 테스트 실행 — 전체 통과 확인**

```
pytest tests/ -v
```

Expected: 전체 PASS

- [ ] **Step 10: 커밋**

```
git add carver/recovery.py tests/test_recovery.py
git commit -m "fix: _collect_violations를 scan_ranges 기반으로 전환하고 호출부를 수정한다"
```

---

## 자가 검토 결과

1. **스펙 커버리지:** `_find_scan_end` ✓, `_parse_header` 다중 SOS ✓, `DiagnosisResult.scan_ranges` ✓, `diagnose()` BAD_STUFF 범위 제한 ✓, `_collect_violations` 시그니처 ✓, 호출부 수정 ✓
2. **플레이스홀더:** 없음. 모든 스텝에 실제 코드 포함.
3. **타입 일관성:** `scan_ranges: list[tuple[int, int]]`이 `_parse_header` 반환 → `DiagnosisResult` → `_collect_violations` → `_recover_bad_stuff`까지 일관되게 전달됨.
4. **`_recover_bad_stuff` scan_start 파라미터 제거 확인:** 기존 `scan_start: int` 파라미터가 `scan_ranges`로 완전히 교체됨. `if scan_start == -1:` 가드는 `if not scan_ranges:`로 교체됨.
