# Progressive JPEG 다중 스캔 지원 설계

**날짜:** 2026-05-26  
**브랜치:** fix/progressive-jpeg-scan-ranges  
**상태:** 승인됨

## 배경 및 문제

손상된 디스크 이미지에서 추출한 JPEG 파일 중 다수가 Progressive JPEG (FF DA 마커 3개)임이 확인됐다. 현재 복구 파이프라인에는 두 가지 치명적 버그가 있다.

### 버그 1: `_collect_violations`가 Progressive JPEG 마커를 위반으로 오탐

```python
# recovery.py
if nb != 0x00 and not (0xD0 <= nb <= 0xD9):  # 0xDA = 218 > 0xD9 = 217
    violations.append(ff)
```

`scan_start`(스캔1 시작)부터 파일 끝까지를 하나의 스캔 데이터로 간주하므로, 스캔2·3의 `FF DA` 헤더가 위반으로 탐지된다. `_patch_bad_stuff`가 이를 `FF 00`으로 교체하면 스캔2·3 헤더가 파괴되고, libjpeg는 스캔1만 복호화해 나머지를 회색으로 채운다 — 원본보다 더 나쁜 결과.

### 버그 2: `_parse_header`가 첫 번째 SOS에서 파싱 중단

Progressive JPEG의 스캔2·3 존재 자체를 인식하지 못해, 이후 모든 처리가 스캔1 기준으로만 동작한다.

---

## 설계

### 핵심 원칙

스캔 데이터의 범위를 명시적으로 알고 처리한다. `FF XX` 위반 탐지는 각 스캔의 데이터 구간 안에서만 수행한다.

---

### `diagnosis.py` 변경

#### 1. `_find_scan_end(data, start) → int` 추가

스캔 데이터 시작 위치부터 바이트를 순회하며, `FF XX`에서 XX가 스터핑(`00`)도 RST(`D0`–`D7`)도 아닌 첫 위치를 반환한다. 이 위치가 다음 JPEG 세그먼트의 시작이자 현재 스캔 데이터의 끝이다.

```
입력: data, start=N
출력: 첫 번째 "비-스터핑 비-RST FF 바이트"의 위치 (없으면 len(data))
```

#### 2. `_parse_header` 다중 SOS 파싱

- SOS 발견 시 `break` 제거
- `_find_scan_end`로 현재 스캔 데이터의 끝을 구함
- `(scan_data_start, scan_data_end)` 튜플을 `scan_ranges` 리스트에 추가
- 스캔 끝 위치부터 다음 세그먼트 파싱을 계속
- 반환 dict에 `scan_ranges: list[tuple[int, int]]` 추가
- `scan_start`는 하위 호환을 위해 첫 번째 스캔 시작으로 유지

#### 3. `DiagnosisResult` 필드 추가

```python
scan_ranges: list[tuple[int, int]] = field(default_factory=list)
```

#### 4. `diagnose()` BAD_STUFF 탐지 범위 제한

`data[r.scan_start:]` 전체가 아닌, `r.scan_ranges` 각 구간 안에서만 `FF XX` 위반을 탐지한다. `first_bad_offset`도 동일하게 범위 제한.

---

### `recovery.py` 변경

#### 5. `_collect_violations` 시그니처 변경

```python
# 변경 전
def _collect_violations(data: bytes, scan_start: int) -> list[int]:

# 변경 후
def _collect_violations(data: bytes, scan_ranges: list[tuple[int, int]]) -> list[int]:
```

각 `(start, end)` 구간 안에서만 `FF XX` 위반을 탐색한다. 구간 경계를 넘지 않으므로 다음 스캔 헤더의 `FF DA`는 절대 탐지되지 않는다.

#### 6. `_recover_bad_stuff` 및 `recover_file` 호출부 수정

`scan_start` 대신 `diagnosis.scan_ranges`를 `_collect_violations`에 넘기도록 수정한다.

---

## 변경 파일 요약

| 파일 | 변경 내용 |
|---|---|
| `carver/diagnosis.py` | `_find_scan_end` 추가, `_parse_header` SOS 루프 전환, `DiagnosisResult.scan_ranges` 필드, `diagnose()` BAD_STUFF 범위 제한 |
| `carver/recovery.py` | `_collect_violations` 시그니처, `_recover_bad_stuff` 호출 수정 |

## 보간 로직

변경 없음. 버그 수정 후 gray% < 10% 케이스가 대부분이 되어 자연스럽게 실행 빈도가 줄어들 것으로 예상. 이후 실측 후 판단.

## 테스트 포인트

- `_find_scan_end`: 스터핑/RST 포함 바이트열에서 올바른 종료 위치 반환
- `_parse_header`: Progressive JPEG에서 `scan_ranges` 3개 반환, `scan_start` 하위 호환
- `_collect_violations`: 스캔 경계를 넘는 `FF DA`를 위반으로 탐지하지 않음
- 통합: Progressive JPEG + 스캔3 비트 플립 → 스캔1·2 온전히 복호화
