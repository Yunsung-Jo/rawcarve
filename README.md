# rawcarve

ddrescue 등으로 복구한 손상된 디스크 이미지(`.img`)에서 **JPEG 이미지**와 **AVI 영상** 파일을 추출하고, 손상된 JPEG를 복구하는 파일 카빙 도구.

`mmap` 기반 시그니처 탐색으로 대용량 이미지를 효율적으로 처리한다.

## 설치

```bash
pip install -r requirements.txt
```

Python 3.10 이상 권장.

## 사용법

### 1단계: 디스크 이미지에서 파일 추출

```bash
python carve.py <이미지 파일> [옵션]
```

| 옵션 | 설명 | 기본값 |
|------|------|--------|
| `-o, --output DIR` | 출력 디렉토리 | `./output` |
| `--max-avi-size MB` | AVI 최대 크기 (MB) | `500` |
| `--save-thumbnails` | 썸네일을 `jpeg_thumbnails/`에 저장 | 건너뜀 |

```bash
python carve.py usb.img -o output/
python carve.py usb.img -o output/ --max-avi-size 200 --save-thumbnails
```

### 2단계: 추출된 JPEG 복구 (선택)

```bash
python recover.py <입력 디렉토리> [옵션]
```

| 옵션 | 설명 | 기본값 |
|------|------|--------|
| `-o, --output DIR` | 출력 디렉토리 | `<input>_recovered` |

```bash
python recover.py output/jpeg/ -o output/jpeg_recovered/
```

## 출력 구조

```
output/
├── jpeg/               # 추출된 JPEG 파일 (0x{오프셋}.jpg)
├── jpeg_thumbnails/    # 내장 썸네일 (--save-thumbnails 사용 시)
├── avi/                # 추출된 AVI 파일 (0x{오프셋}.avi)
├── errors.log          # 추출 실패 오프셋 및 오류 내역
└── jpeg_recovered/     # 복구된 JPEG 및 report.csv
```

파일명의 16진수 오프셋은 디스크 이미지 내 원본 위치를 나타낸다.

## 복구 전략

| 진단 원인 | 전략 |
|-----------|------|
| `BAD_STUFF` | 스캔 데이터 내 `FF XX` → `FF 00` 패치 후 디코딩 |
| `MARKER_BYTE_FLIP` | 헤더 마커 바이트 교정 후 동일 파이프라인 적용 |
| `GRAY_MCU` / 기타 손상 | 강제 디코딩 (libjpeg truncated 허용) |
| `FALSE_POSITIVE` / `ZERO_FILL` | 건너뜀 |

## 테스트

```bash
pip install -r requirements-dev.txt
python -m pytest tests/ -v
```
