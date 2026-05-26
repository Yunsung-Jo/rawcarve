# 세그먼트 유효성 검증 및 보간 제거 설계

**날짜:** 2026-05-26  
**브랜치:** fix/progressive-jpeg-scan-ranges  
**상태:** 승인됨

## 배경 및 문제

### 버그 1: `_find_scan_end`가 비트 플립으로 생성된 가짜 경계 마커를 실제 세그먼트 경계로 오인

`_SCAN_BOUNDARY_MARKERS = frozenset([0xC4, 0xD8, 0xD9, 0xDA, 0xDB, 0xDD, 0xFE])`에 속하는 마커 바이트가 스캔 데이터 내에 비트 플립으로 나타났을 때, `_find_scan_end`는 해당 위치를 스캔 끝으로 판단한다.

예시 (`0x17D30000.jpg`):
- 스캔 데이터 내 `FF C4` (비트 플립)
- `_find_scan_end`가 853210 위치에서 멈춤 → 파일 크기 989866 중 136,656 바이트가 스캔 범위 밖으로 잘림
- 잘린 위치의 `FF C4`는 스캔 범위 밖이므로 `_collect_violations`가 탐지 안 함 → 패치 안 됨
- libjpeg가 스캔 도중 `FF C4`를 만나면 DHT로 해석 시도 → 실패 → 회색 채움

이전 코드(`_collect_violations(data, scan_start: int)`)는 `scan_start`부터 파일 끝까지 탐색해 `FF C4`를 위반으로 탐지하고 패치했다. Progressive JPEG 지원을 위해 `_SCAN_BOUNDARY_MARKERS`를 도입하면서 이 동작이 깨졌다.

### 문제 2: 보간 로직이 비트 플립 피해를 확대

비트 플립이 근본 원인이므로 바이트 유실이 없다. 패치 후 정상 디코딩이 가능한데 보간을 적용하면:
- `interpolate_damaged_blocks`가 이웃 블록의 단색 평균으로 채움
- 단색 → DCT에서 동일한 허프만 코드 반복 → 4바이트 패턴이 반복되는 아티팩트 발생

---

## 설계

### 1. `_is_valid_segment` 헬퍼 추가 (`diagnosis.py`)

경계 마커 후보 위치가 진짜 JPEG 세그먼트인지 검증한다.

```python
def _is_valid_segment(data: bytes, ff_pos: int) -> bool:
    """FF XX 위치가 유효한 JPEG 세그먼트인지 검증한다.

    조건:
    - ff_pos + 4 이내 데이터 존재
    - 2바이트 길이 필드 >= 2
    - 세그먼트 끝(ff_pos + 2 + seg_len)이 파일 범위 내
    - 세그먼트 끝 바로 뒤에 0xFF 존재하거나 파일 끝
    """
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

### 2. `_find_scan_end` 분기 수정 (`diagnosis.py`)

```python
# 변경 전
elif nb in _SCAN_BOUNDARY_MARKERS:
    return ff

# 변경 후
elif nb in _SCAN_BOUNDARY_MARKERS:
    if _is_valid_segment(data, ff):
        return ff        # 진짜 경계 → 스캔 끝
    else:
        pos = ff + 2    # 가짜 (비트 플립) → 계속 스캔
```

**결과:**
- 진짜 `FF DA` (Progressive SOS): 유효한 길이 필드 + 뒤에 `FF` 존재 → 경계로 처리
- 가짜 `FF C4` (비트 플립): 길이 필드 이상 또는 뒤에 `FF` 없음 → 스캔 범위 내에 포함 → `_collect_violations`가 탐지 → `FF 00`으로 패치

### 3. `interpolate_damaged_blocks` 삭제 (`recovery.py`)

함수 자체를 삭제한다. `detect_damaged_blocks`는 gray% 임계값 체크(≥ 90% → SKIP_TOO_DAMAGED)에 여전히 사용하므로 유지한다.

`_recover_bad_stuff`에서 보간 조건 제거:

```python
# 변경 전
if pct >= 0.10:
    arr = interpolate_damaged_blocks(arr, damaged)
out_path.write_bytes(_arr_to_jpeg(arr))

# 변경 후
out_path.write_bytes(_arr_to_jpeg(arr))
```

`_recover_interpolate_only`에서 보간 제거:

```python
# 변경 전
arr = interpolate_damaged_blocks(arr, damaged)
out_path.write_bytes(_arr_to_jpeg(arr))

# 변경 후
out_path.write_bytes(_arr_to_jpeg(arr))
```

---

## 변경 파일 요약

| 파일 | 변경 내용 |
|---|---|
| `carver/diagnosis.py` | `_is_valid_segment` 추가, `_find_scan_end` 경계 마커 분기 수정 |
| `carver/recovery.py` | `interpolate_damaged_blocks` 함수 삭제, `_recover_bad_stuff` 및 `_recover_interpolate_only`에서 호출 제거 |
| `tests/test_diagnosis.py` | `_is_valid_segment` 단위 테스트, `_find_scan_end` 비트 플립 케이스 테스트 추가 |
| `tests/test_recovery.py` | 보간 관련 테스트 제거 또는 수정 |

## 테스트 포인트

- `_is_valid_segment`: 유효한 세그먼트 → True, 길이 이상 → False, 뒤에 `FF` 없음 → False
- `_find_scan_end`: 비트 플립으로 생성된 `FF C4`가 스캔 범위 내에 포함되어 탐지됨
- `_find_scan_end`: 진짜 Progressive `FF DA`는 여전히 경계로 처리됨
- `_collect_violations`: 비트 플립 `FF C4`가 스캔 범위 안에서 위반으로 탐지됨
- 보간 제거 후 `RECOVERED_INTERPOLATED` 액션 미발생, 90% 미만 gray 이미지는 그대로 저장
