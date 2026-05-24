# rawcarve

ddrescue 등으로 복구한 손상된 디스크 이미지(`.img`)에서 **JPEG 이미지**와 **AVI 영상** 파일을 추출하고, 손상된 JPEG를 복구하는 파일 카빙 도구.

`mmap` 기반 시그니처 탐색으로 3 GB 이상의 대용량 이미지를 효율적으로 처리한다.

## 특징

- **JPEG 세그먼트 파싱** — APP1/EXIF 내 내장 썸네일의 `FF D9`를 부모 파일의 끝으로 오판하지 않도록 세그먼트 길이 필드를 직접 파싱해 정확한 파일 경계를 계산
- **AVI RIFF 헤더 파싱** — `RIFF` 청크 크기 필드를 읽어 AVI 파일 크기를 결정; WAV 등 다른 RIFF 포맷은 자동으로 제외
- **범위 기반 썸네일 감지** — 이미 추출한 파일 범위 안에 포함된 JPEG 히트는 내장 썸네일로 분류
- **손상 대응** — 파싱 실패 시 다음 시그니처 위치를 폴백 경계로 사용; 개별 오류는 건너뛰고 계속 진행
- **tqdm 진행률 표시** + 파일별 추출 로그
- **JPEG 복구** — 추출된 손상 JPEG를 원인별로 진단·복구하고 `report.csv` 리포트 생성

## 설치

```bash
pip install -r requirements.txt
```

Python 3.10 이상 권장.

## 사용법

```bash
python carve.py <이미지 파일> [옵션]
```

### 옵션

| 옵션 | 설명 | 기본값 |
|------|------|--------|
| `-o, --output DIR` | 출력 디렉토리 | `./output` |
| `--max-avi-size MB` | AVI 최대 크기 (MB) | `500` |
| `--save-thumbnails` | 썸네일을 `jpeg_thumbnails/`에 저장 | 건너뜀 |

### 예시

```bash
# 기본 실행
python carve.py usb.img -o output/

# AVI 크기 제한 + 썸네일 저장
python carve.py usb.img -o output/ --max-avi-size 200 --save-thumbnails
```

### 출력 예시

```
Scanning usb.img (3354.19 MB)...
시그니처 탐색 중...
시그니처 발견: 1874개
추출 중: 100%|████████████| 1874/1874 [02:13<00:00, 14.0파일/s]
[FOUND] JPEG at 0x01A3F000 → output/jpeg/0x01A3F000.jpg (45.2 KB)
[FOUND] AVI  at 0x03B20000 → output/avi/0x03B20000.avi (128.4 MB)
[THUMB] JPEG at 0x01A3F210 → skipped (embedded thumbnail)

Scan complete. JPEG: 42, AVI: 3, Thumbnails: 38, Errors: 1
```

## JPEG 복구

`carve.py`로 추출한 JPEG 파일을 진단·복구한다. 손상 원인을 자동으로 분류하고 원인별 전략을 적용한다.

```bash
python recover.py output/jpeg/ -o output/jpeg_recovered/
```

### 옵션

| 옵션 | 설명 | 기본값 |
|------|------|--------|
| `input` | 입력 디렉토리 (`output/jpeg/`) | — |
| `-o, --output DIR` | 출력 디렉토리 | `<input>_recovered` |

### 복구 전략

| 진단 원인 | 전략 |
|-----------|------|
| `BAD_STUFF` | 스캔 데이터 내 `FF XX` → `FF 00` 바이트 교정 후 디코딩 |
| `MARKER_BYTE_FLIP` | 헤더 마커 바이트 교정 후 동일 파이프라인 적용 |
| `GRAY_MCU` / 기타 손상 | 강제 디코딩 + 손상 블록 보간 |
| `FALSE_POSITIVE` / `ZERO_FILL` | 건너뜀 |

### 출력

복구된 파일은 출력 디렉토리에 저장되고, `report.csv`에 각 파일의 진단 결과와 처리 내역이 기록된다.

| CSV 컬럼 | 설명 |
|----------|------|
| `filename` | 원본 파일명 |
| `causes` | 진단된 손상 원인 (`;` 구분) |
| `action` | 처리 결과 (`RECOVERED_PATCHED` / `RECOVERED_INTERPOLATED` / `SKIP_*` / `CLEAN` / `ERROR`) |
| `damaged_block_pct` | 복구 전 손상 블록 비율 |
| `recovered_block_pct` | 복구 후 손상 블록 비율 |
| `cut_offset_kb` | 첫 번째 BAD_STUFF 위치 (KB) |
| `image_size` | 이미지 크기 (`{w}x{h}`) |

## 출력 구조

```
output/
├── jpeg/               # 추출된 JPEG 파일 (0x{오프셋}.jpg)
├── jpeg_thumbnails/    # 내장 썸네일 (--save-thumbnails 사용 시)
├── jpeg_recovered/     # 복구된 JPEG 파일
│   └── report.csv      # 진단·복구 리포트
├── avi/                # 추출된 AVI 파일 (0x{오프셋}.avi)
└── errors.log          # 추출 실패 오프셋 및 오류 내역
```

파일명에 포함된 16진수 오프셋은 디스크 이미지 내 원본 위치를 나타낸다.

## 에러 처리

| 상황 | 처리 방식 |
|------|-----------|
| JPEG 세그먼트 파싱 실패 | 다음 시그니처 위치까지 폴백, 경고 표시 |
| JPEG EOI 없음 | 최대 10 MB 추출 후 경고 |
| AVI 청크 크기 이상 | 다음 시그니처 위치까지 폴백 |
| 파일 추출 중 예외 | 해당 오프셋 건너뜀, `errors.log`에 기록 |

모든 오류는 프로그램을 중단시키지 않고 계속 진행한다.

## 파일 구조

```
rawcarve/
├── carve.py              # 추출 CLI 진입점
├── recover.py            # 복구 CLI 진입점
├── carver/
│   ├── models.py         # FileHit 데이터 클래스
│   ├── extractors.py     # JPEG/AVI 파일 경계 계산
│   ├── scanner.py        # mmap 기반 시그니처 탐색
│   ├── diagnosis.py      # JPEG 손상 원인 진단
│   └── recovery.py       # 손상 블록 감지·보간·복구
├── tests/
│   ├── test_models.py
│   ├── test_extractors.py
│   ├── test_scanner.py
│   ├── test_carve.py
│   ├── test_diagnosis.py
│   └── test_recovery.py
├── requirements.txt
└── requirements-dev.txt
```

## 테스트

```bash
pip install -r requirements-dev.txt
python -m pytest tests/ -v
```
