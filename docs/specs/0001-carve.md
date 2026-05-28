# carve.py

- **날짜:** 2026-05-28
- **상태:** Accepted

---

## 개요

손상된 디스크 이미지(`.img` 등)에서 JPEG와 AVI 파일을 추출하는 도구.
파일 시스템 메타데이터 없이 시그니처 기반으로 파일 경계를 탐지하고, 해당 바이트 범위를 그대로 저장한다.
ddrescue 등으로 복구한 이미지처럼 디렉토리 구조가 유실된 경우에 사용한다.

## 인터페이스

| 이름 | 설명 | 타입 | 기본값 |
|------|------|------|--------|
| `image` | 디스크 이미지 파일 경로 | positional | — |
| `-o, --output` | 출력 디렉토리 | str | `./output` |
| `--max-avi-size` | AVI 최대 크기 (MB) | int | `500` |
| `--save-thumbnails` | AVI 내 임베디드 JPEG를 `jpeg_thumbnails/`에 저장 | flag | 생략 시 스킵 |

## 출력

출력 디렉토리 구조:

```
<output>/
  jpeg/               # 추출된 JPEG 파일
  avi/                # 추출된 AVI 파일
  jpeg_thumbnails/    # --save-thumbnails 사용 시에만 생성
  errors.log          # 추출 중 예외가 발생한 항목 기록
```

파일명은 이미지 내 발견 오프셋을 그대로 사용한다: `0x{오프셋:08X}.jpg` / `0x{오프셋:08X}.avi`.

## 파이프라인

1. **mmap 로드** (`carve.py`) — 이미지 파일을 읽기 전용 메모리 맵으로 연다.
2. **시그니처 탐색** (`carver/scanner.py`) — `FF D8 FF`(JPEG)와 `RIFF...AVI `(AVI) 시그니처를 전체 이미지에서 탐색해 오프셋 순으로 정렬된 `FileHit` 목록을 반환한다.
3. **임베디드 판별** (`carve.py`) — 이미 추출된 범위 안에 속하는 오프셋은 임베디드 파일(AVI 내 JPEG 썸네일 등)로 간주한다.
4. **끝 오프셋 계산** (`carver/extractors.py`) — JPEG는 세그먼트 파싱으로 EOI를 찾고, AVI는 RIFF chunk_size 헤더를 읽는다. 정상 파싱이 불가능하면 다음 시그니처 오프셋 또는 크기 상한으로 fallback한다.
5. **파일 저장** (`carve.py`) — 계산된 바이트 범위를 출력 디렉토리에 기록한다. 예외 발생 시 `errors.log`에 남기고 다음 항목으로 넘어간다.

## 사용하는 모듈

- `carver/scanner.py` — 전체 이미지 시그니처 탐색
- `carver/extractors.py` — JPEG/AVI 파일 경계(끝 오프셋) 계산
- `carver/models.py` — `FileHit` 데이터 클래스

## 의존하는 포맷 / 스펙

- [JPEG 마커 구조](../reference/jpeg-markers.md)
- [AVI RIFF 청크 구조](../reference/avi-riff.md)

## 엣지 케이스

| 상황 | 동작 |
|------|------|
| AVI 내 JPEG 썸네일 (임베디드) | `--save-thumbnails` 있으면 `jpeg_thumbnails/`에 저장, 없으면 스킵. `jpeg/`에는 저장하지 않는다. |
| JPEG에 EOI 없음 (truncated) | 다음 시그니처 오프셋까지 추출. 다음 시그니처 없으면 현재 오프셋 + 10 MB 상한 적용. 파일명 옆에 `[불완전, fallback 사용]` 표시. |
| AVI RIFF chunk_size가 0이거나 max_avi_size 초과 | 다음 시그니처 오프셋 또는 max_avi_size 상한으로 fallback. `[fallback 사용]` 표시. |
| 이미지 파일 없음 | 오류 메시지 출력 후 exit code 1로 종료. |
