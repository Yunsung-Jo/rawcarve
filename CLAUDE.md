# rawcarve

ddrescue 등으로 복구한 손상된 디스크 이미지(.img)에서
JPEG 이미지와 AVI 영상 파일을 추출하고, 손상된 JPEG를 복구하는 파일 카빙 도구.

## 실행 방법

```bash
pip install -r requirements.txt

# 1단계: 디스크 이미지에서 JPEG/AVI 추출
python carve.py <이미지 파일> [옵션]

# 2단계: 추출된 JPEG 복구 (선택)
python recover.py output/jpeg/ -o output/jpeg_recovered/
```

### carve.py 옵션

| 옵션 | 설명 | 기본값 |
|------|------|--------|
| `-o, --output DIR` | 출력 디렉토리 | `./output` |
| `--max-avi-size MB` | AVI 최대 크기 (MB) | `500` |
| `--save-thumbnails` | 썸네일을 `jpeg_thumbnails/`에 저장 | 건너뜀 |

### recover.py 옵션

| 옵션 | 설명 | 기본값 |
|------|------|--------|
| `input` | 입력 디렉토리 | — |
| `-o, --output DIR` | 출력 디렉토리 | `<input>_recovered` |

### 예시

```bash
python carve.py usb.img -o output/
python carve.py usb.img -o output/ --max-avi-size 200 --save-thumbnails
python recover.py output/jpeg/ -o output/jpeg_recovered/
```

## 파일 구조

```
rawcarve/
├── carve.py              # 추출 CLI 진입점
├── recover.py            # 복구 CLI 진입점
├── carver/
│   ├── models.py         # FileHit 데이터 클래스
│   ├── extractors.py     # JPEG/AVI 경계 계산
│   ├── scanner.py        # 시그니처 탐색
│   ├── diagnosis.py      # JPEG 손상 원인 진단
│   └── recovery.py       # 손상 블록 감지·보간·복구
├── output/               # 추출 결과 (gitignore)
│   ├── jpeg/
│   ├── jpeg_thumbnails/
│   ├── jpeg_recovered/
│   └── avi/
└── tests/
```

## 커밋 메시지 규칙

Conventional Commits 형식, 한글로 작성:

```
<타입>: <제목> (50자 이내)

<본문> — 변경 이유와 맥락 서술

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
```

타입: `feat`, `fix`, `chore`, `docs`, `refactor`, `test`

## 테스트 실행

```bash
pip install -r requirements-dev.txt
python -m pytest tests/ -v
```
