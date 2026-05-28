# recover.py

- **날짜:** 2026-05-28
- **상태:** Accepted

---

## 개요

`carve.py`가 추출한 JPEG 파일을 진단하고 복구하는 도구.
각 파일의 손상 원인을 분류한 뒤 원인에 맞는 복구 전략을 적용한다.
복구 불가 파일은 스킵하고, 전체 결과를 `report.csv`로 저장한다.

## 인터페이스

| 이름 | 설명 | 타입 | 기본값 |
|------|------|------|--------|
| `input` | 입력 디렉토리 (`output/jpeg/`) | positional | — |
| `-o, --output` | 출력 디렉토리 | str | `<input>_recovered` |

## 출력

```
<output>/
  *.jpg          # 복구된 JPEG 파일 (원본 파일명 유지)
  report.csv     # 파일별 진단·복구 결과
```

`report.csv` 컬럼:

| 컬럼 | 설명 |
|------|------|
| `filename` | 원본 파일명 |
| `causes` | 진단 원인 (`;` 구분, 복수 가능) |
| `action` | 복구 결과 코드 |
| `damaged_block_pct` | 복구 전 손상 블록 비율 (0.0–1.0) |
| `recovered_block_pct` | 복구 후 손상 블록 비율 |
| `cut_offset_kb` | 첫 번째 BAD_STUFF 위치 (KB) |
| `image_size` | SOF에서 읽은 이미지 해상도 (`WxH`) |

## 파이프라인

1. **JPEG 목록 수집** (`recover.py`) — 입력 디렉토리에서 `*.jpg`를 오프셋 순으로 정렬한다.
2. **진단** (`carver/diagnosis.py`) — 파일을 파싱해 손상 원인을 `DiagnosisResult`에 기록한다. 원인 우선순위: `FALSE_POSITIVE` → `MARKER_BYTE_FLIP` → `BAD_STUFF` → `GRAY_MCU` → `ZERO_FILL` → `CLEAN`.
3. **복구** (`carver/recovery.py`) — 원인에 맞는 전략을 실행하고 `action` 코드를 반환한다.
4. **report.csv 작성** (`recover.py`) — 파일별 진단·복구 결과를 행으로 기록한다.

## 사용하는 모듈

- `carver/diagnosis.py` — JPEG 파싱 및 손상 원인 분류
- `carver/recovery.py` — 원인별 복구 전략 실행

## 의존하는 포맷 / 스펙

- [JPEG 마커 구조](../reference/jpeg-markers.md)

## 엣지 케이스

| 상황 | 동작 (`action`) |
|------|-----------------|
| SOF 없음 또는 해상도·채널 수가 비정상 | `SKIP_FALSE_POSITIVE` — 파일 저장 안 함 |
| 스캔 데이터 50% 이상이 `0x00` | `SKIP_ZERO_FILL` — 파일 저장 안 함 |
| 헤더에 `0xCB`/`0xC3`/`0xC5` 마커 (비트 플립) | 마커 교정 후 BAD_STUFF 파이프라인 적용 |
| 스캔 데이터에 `FF XX` 위반 (`XX` ≠ `00`, `D0–D9`) | 위반 바이트를 `00`으로 패치 → 디코딩 시도 → `RECOVERED_PATCHED` |
| 패치 후에도 디코딩 실패 또는 손상 블록 90% 이상 | 강제 디코딩(libjpeg truncated 허용) → `RECOVERED_DECODED` 또는 `SKIP_TOO_DAMAGED` |
| 회색 MCU 패턴(`01 45 00 14 50`) 4회 이상 반복 | 강제 디코딩 → `RECOVERED_DECODED` 또는 `SKIP_TOO_DAMAGED` |
| 손상 없음 | `CLEAN` — 출력 디렉토리에 파일 저장 안 함, report에만 기록 |
| 입력 디렉토리 없음 | 오류 메시지 출력 후 exit code 1로 종료 |
