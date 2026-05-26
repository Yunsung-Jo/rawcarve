# 세그먼트 유효성 검증 및 보간 제거 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `_find_scan_end`에 세그먼트 유효성 검증을 추가해 비트 플립으로 생성된 가짜 경계 마커를 올바르게 처리하고, 아티팩트를 유발하는 보간 로직을 제거한다.

**Architecture:** `_is_valid_segment` 헬퍼가 `FF XX` 위치에서 JPEG 세그먼트 구조(길이 필드 유효성, 세그먼트 끝 뒤 `FF` 존재)를 검증한다. `_find_scan_end`는 `_SCAN_BOUNDARY_MARKERS`에 속하는 마커를 만나면 이 검증을 거쳐 진짜 경계와 비트 플립을 구분한다. `interpolate_damaged_blocks`는 삭제하고 복구 함수들에서 호출을 제거한다.

**Tech Stack:** Python 3.13, pytest, PIL/Pillow, numpy

---

## 파일 구조

| 파일 | 변경 |
|---|---|
| `carver/diagnosis.py` | `_NO_LEN_BOUNDARY` 상수 추가, `_is_valid_segment` 추가, `_find_scan_end` 분기 수정 |
| `carver/recovery.py` | `interpolate_damaged_blocks` 삭제, `_recover_bad_stuff`·`_recover_interpolate_only` 보간 호출 제거 |
| `tests/test_diagnosis.py` | `_is_valid_segment` 단위 테스트 추가, `test_find_scan_end_stops_at_sda`·`test_find_scan_end_rst_continues` 업데이트, 새 `_find_scan_end` 케이스 추가 |
| `tests/test_recovery.py` | `interpolate_damaged_blocks` 임포트 제거, 보간 테스트 2개 삭제 |

---

## Task 1: `_is_valid_segment` 헬퍼 및 `_find_scan_end` 세그먼트 검증

**Files:**
- Modify: `carver/diagnosis.py:13-41`
- Modify: `tests/test_diagnosis.py`

- [ ] **Step 1: 실패 테스트 작성 — `_is_valid_segment` 단위 테스트**

`tests/test_diagnosis.py` 파일 끝에 다음을 추가한다:

```python
from carver.diagnosis import _is_valid_segment


def test_is_valid_segment_valid():
    # FF C4 00 04 AB CD FF DA — length=4, 2바이트 페이로드, 뒤에 FF
    data = bytes([0xFF, 0xC4, 0x00, 0x04, 0xAB, 0xCD, 0xFF, 0xDA])
    assert _is_valid_segment(data, 0) is True


def test_is_valid_segment_length_too_small():
    # length=1 은 유효하지 않다 (< 2)
    data = bytes([0xFF, 0xC4, 0x00, 0x01, 0xAB, 0xFF, 0xDA])
    assert _is_valid_segment(data, 0) is False


def test_is_valid_segment_length_exceeds_data():
    # length=100 이지만 데이터가 너무 짧다
    data = bytes([0xFF, 0xC4, 0x00, 0x64, 0xAB])
    assert _is_valid_segment(data, 0) is False


def test_is_valid_segment_not_followed_by_ff():
    # 유효한 길이지만 세그먼트 끝 뒤가 FF가 아니다
    data = bytes([0xFF, 0xC4, 0x00, 0x04, 0xAB, 0xCD, 0x00, 0xDA])
    assert _is_valid_segment(data, 0) is False


def test_is_valid_segment_at_file_end():
    # 세그먼트 끝이 정확히 파일 끝 (seg_end == size) → 유효
    data = bytes([0xFF, 0xC4, 0x00, 0x04, 0xAB, 0xCD])
    assert _is_valid_segment(data, 0) is True


def test_is_valid_segment_too_short_for_length_field():
    # ff_pos + 4 > size → 길이 필드를 읽을 수 없다
    data = bytes([0xFF, 0xC4, 0x00])
    assert _is_valid_segment(data, 0) is False


def test_is_valid_segment_eoi_no_length():
    # EOI (FF D9)는 길이 필드 없이 항상 유효
    data = bytes([0xFF, 0xD9])
    assert _is_valid_segment(data, 0) is True


def test_is_valid_segment_soi_no_length():
    # SOI (FF D8)는 길이 필드 없이 항상 유효
    data = bytes([0xFF, 0xD8])
    assert _is_valid_segment(data, 0) is True


def test_find_scan_end_fake_boundary_not_stopped():
    # FF C4 with length=1 (invalid) → 경계 아님, 이후 FF D9에서 멈춘다
    data = bytes([0xFF, 0xC4, 0x00, 0x01, 0xFF, 0xD9])
    assert _find_scan_end(data, 0) == 4


def test_find_scan_end_real_c4_is_boundary():
    # FF C4 with length=4, 2바이트 payload, 뒤에 FF → 진짜 경계
    data = bytes([0xFF, 0xC4, 0x00, 0x04, 0xAB, 0xCD, 0xFF, 0xDA])
    assert _find_scan_end(data, 0) == 0
```

- [ ] **Step 2: 실패 확인**

```
python -m pytest tests/test_diagnosis.py::test_is_valid_segment_valid -v
```

Expected: `FAILED` — `ImportError: cannot import name '_is_valid_segment'`

- [ ] **Step 3: `_is_valid_segment` 구현 — `carver/diagnosis.py`**

`_SCAN_BOUNDARY_MARKERS` 라인(13) 뒤에 다음을 추가한다:

```python
_NO_LEN_BOUNDARY = frozenset([0xD8, 0xD9])  # SOI/EOI: 길이 필드 없음


def _is_valid_segment(data: bytes, ff_pos: int) -> bool:
    """FF XX 위치가 유효한 JPEG 세그먼트인지 검증한다."""
    nb = data[ff_pos + 1]
    if nb in _NO_LEN_BOUNDARY:
        return True
    size = len(data)
    if ff_pos + 4 > size:
        return False
    seg_len = struct.unpack('>H', data[ff_pos + 2:ff_pos + 4])[0]
    if seg_len < 2:
        return False
    seg_end = ff_pos + 2 + seg_len
    if seg_end > size:
        return False
    return seg_end == size or data[seg_end] == 0xFF
```

- [ ] **Step 4: 새 테스트 통과 확인**

```
python -m pytest tests/test_diagnosis.py::test_is_valid_segment_valid tests/test_diagnosis.py::test_is_valid_segment_eoi_no_length tests/test_diagnosis.py::test_find_scan_end_fake_boundary_not_stopped tests/test_diagnosis.py::test_find_scan_end_real_c4_is_boundary -v
```

Expected: `4 passed`

- [ ] **Step 5: `_find_scan_end` 경계 마커 분기 수정**

`carver/diagnosis.py`의 `elif nb in _SCAN_BOUNDARY_MARKERS:` 블록을 수정한다:

```python
# 변경 전 (37-38번 줄)
        elif nb in _SCAN_BOUNDARY_MARKERS:
            return ff

# 변경 후
        elif nb in _SCAN_BOUNDARY_MARKERS:
            if _is_valid_segment(data, ff):
                return ff
            else:
                pos = ff + 2
```

- [ ] **Step 6: 기존 `_find_scan_end` 테스트 2개 업데이트**

두 테스트에서 합성 데이터가 유효성 검증을 통과할 수 있도록 SOS 픽스처를 교체한다.

`tests/test_diagnosis.py`에서 다음 두 함수를 교체한다:

```python
def test_find_scan_end_stops_at_sda():
    # 유효한 SOS 앞에서 스캔이 멈춰야 한다
    # FF DA 00 04 AB CD FF: length=4, 2바이트 payload, 뒤에 FF
    sos = bytes([0xFF, 0xDA, 0x00, 0x04, 0xAB, 0xCD, 0xFF])
    data = bytes([0xFF, 0x00, 0xFF, 0x00]) + sos
    assert _find_scan_end(data, 0) == 4


def test_find_scan_end_rst_continues():
    # FF D5 (RST5)는 계속 진행, 이후 유효한 FF DA에서 멈춰야 한다
    sos = bytes([0xFF, 0xDA, 0x00, 0x04, 0xAB, 0xCD, 0xFF])
    data = bytes([0xFF, 0xD5]) + sos
    assert _find_scan_end(data, 0) == 2
```

- [ ] **Step 7: 전체 테스트 통과 확인**

```
python -m pytest tests/test_diagnosis.py -v
```

Expected: 모든 테스트 통과

- [ ] **Step 8: 커밋**

```bash
git add carver/diagnosis.py tests/test_diagnosis.py
git commit -m "fix: _find_scan_end에 세그먼트 유효성 검증 추가 — 비트 플립 가짜 마커 처리"
```

---

## Task 2: `interpolate_damaged_blocks` 삭제 및 보간 호출 제거

**Files:**
- Modify: `carver/recovery.py:32-66, 111-158`
- Modify: `tests/test_recovery.py:10, 44-59`

- [ ] **Step 1: `test_recovery.py`에서 보간 관련 항목 제거**

`tests/test_recovery.py` 10번 줄에서 `interpolate_damaged_blocks` 임포트를 제거한다:

```python
# 변경 전
from carver.recovery import detect_damaged_blocks, interpolate_damaged_blocks

# 변경 후
from carver.recovery import detect_damaged_blocks
```

`test_interpolate_fills_gray_block` 함수 전체를 삭제한다 (현재 44-51번 줄):

```python
# 삭제할 함수
def test_interpolate_fills_gray_block():
    arr = _solid()
    arr[:8, :8] = 128
    damaged = detect_damaged_blocks(arr)
    result = interpolate_damaged_blocks(arr, damaged)
    block = result[:8, :8]
    assert not np.all(np.abs(block.astype(int) - 128) <= 2)
```

`test_interpolate_preserves_valid_blocks` 함수 전체를 삭제한다 (현재 54-59번 줄):

```python
# 삭제할 함수
def test_interpolate_preserves_valid_blocks():
    arr = _solid()
    arr[:8, :8] = 128
    damaged = detect_damaged_blocks(arr)
    result = interpolate_damaged_blocks(arr, damaged)
    assert np.array_equal(result[8:, 8:], arr[8:, 8:])
```

- [ ] **Step 2: 테스트 통과 확인 (아직 함수 삭제 전)**

```
python -m pytest tests/test_recovery.py -v
```

Expected: 임포트 오류 없이 보간 테스트 2개가 사라진 나머지 통과

- [ ] **Step 3: `recovery.py`에서 `interpolate_damaged_blocks` 함수 삭제**

`carver/recovery.py` 32-66번 줄의 `interpolate_damaged_blocks` 함수 전체를 삭제한다:

```python
# 삭제할 함수 (32-66번 줄)
def interpolate_damaged_blocks(arr: np.ndarray, damaged: np.ndarray) -> np.ndarray:
    """손상 블록을 유효 이웃 블록의 거리 역수 가중 평균으로 채운다."""
    result = arr.copy()
    ...  # 전체 함수 삭제
    return result
```

또한 11번 줄의 `_MAX_RADIUS = 16`도 삭제한다 (이제 사용하지 않음).

- [ ] **Step 4: `_recover_bad_stuff`에서 보간 호출 제거**

`carver/recovery.py`의 `_recover_bad_stuff` 함수를 다음으로 교체한다 (현재 111-145번 줄):

```python
def _recover_bad_stuff(
    data: bytes,
    scan_ranges: list[tuple[int, int]],
    out_path: Path,
) -> str:
    """FF->00 교정 시도. 실패 시 강제 디코딩으로 폴백.

    Returns: RECOVERED_PATCHED | RECOVERED_INTERPOLATED | SKIP_TOO_DAMAGED
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

    arr = _force_decode_arr(data)
    if arr is None:
        return 'SKIP_TOO_DAMAGED'
    if float(detect_damaged_blocks(arr).mean()) >= 0.90:
        return 'SKIP_TOO_DAMAGED'
    out_path.write_bytes(_arr_to_jpeg(arr))
    return 'RECOVERED_INTERPOLATED'
```

- [ ] **Step 5: `_recover_interpolate_only`에서 보간 호출 제거**

`carver/recovery.py`의 `_recover_interpolate_only` 함수를 다음으로 교체한다 (현재 148-158번 줄):

```python
def _recover_interpolate_only(data: bytes, out_path: Path) -> str:
    """강제 디코딩. GRAY_MCU / TRUNCATED_SCAN 용."""
    arr = _force_decode_arr(data)
    if arr is None:
        return 'SKIP_TOO_DAMAGED'
    if float(detect_damaged_blocks(arr).mean()) >= 0.90:
        return 'SKIP_TOO_DAMAGED'
    out_path.write_bytes(_arr_to_jpeg(arr))
    return 'RECOVERED_INTERPOLATED'
```

- [ ] **Step 6: 전체 테스트 통과 확인**

```
python -m pytest tests/ -v
```

Expected: 전체 테스트 통과 (기존 64개에서 보간 테스트 2개 제거된 62개)

- [ ] **Step 7: 커밋**

```bash
git add carver/recovery.py tests/test_recovery.py
git commit -m "fix: interpolate_damaged_blocks 제거 및 복구 함수 보간 호출 삭제"
```
