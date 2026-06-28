# 아키텍처

## 폴더 구조

```
rawcarve/
├── carve.py
├── recover.py
├── carver/
│   ├── models.py
│   ├── extractors.py
│   ├── scanner.py
│   ├── jpegdecode.py
│   └── resync.py
├── output/
│   ├── jpeg/
│   ├── jpeg_thumbnails/
│   ├── jpeg_recovered/
│   └── avi/
└── tests/
```

## 모듈 책임

| 모듈 | 책임 |
|------|------|
| `carve.py` | 디스크 이미지에서 JPEG/AVI 추출 진입점 |
| `recover.py` | 추출된 JPEG를 resync 엔진으로 복구하는 진입점 |
| `carver/models.py` | 파일 탐색 결과를 담는 `FileHit` 데이터 클래스 |
| `carver/scanner.py` | 디스크 이미지에서 파일 시그니처 탐색 |
| `carver/extractors.py` | 탐색 결과로부터 JPEG/AVI 파일 경계 계산. JPEG는 가짜 EOI를 건너뛰어 진짜 끝을 찾는다([ADR 0002](adr/0002-carve-eoi-validation.md)) |
| `carver/jpegdecode.py` | 비트 단위 제어가 가능한 baseline JPEG 디코더(numba). 임의 시작 비트위치/DC에서 재개, 디싱크 탐지 |
| `carver/resync.py` | 바이트 오라클(치환/삭제/삽입) + 세그먼트 resync로 디싱크를 복원하는 복구 엔진 |

## 복구 파이프라인 (recover.py)

`recover.py` → `carver/resync.py::recover_file` → `carver/jpegdecode.py::Decoder`.
손상 지점마다 바이트 편집 또는 비트위치 재동기를 적용해 정렬을 복원하고,
복구 불가 영역은 회색으로 남긴다. 근거는 [ADR 0001](adr/0001-resync-recovery.md).
