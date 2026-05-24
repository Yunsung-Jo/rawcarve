# rawcarve 설계 문서

**날짜:** 2026-05-24  
**상태:** 승인됨

---

## 개요

ddrescue 등으로 복구한 손상된 디스크 이미지(`.img`)에서 JPEG 이미지 및 AVI 영상 파일을 추출하는 파일 카빙 도구. `mmap` 기반 시그니처 탐색으로 대용량 이미지(3 GB 이상)를 효율적으로 처리한다.

---

## 아키텍처

### 파일 구조

```
rawcarve/
├── carve.py              # CLI 진입점 (argparse)
├── carver/
│   ├── __init__.py
│   ├── scanner.py        # mmap 기반 시그니처 스캔 엔진
│   ├── extractors.py     # JPEG / AVI 추출 로직
│   └── models.py         # 데이터 클래스 (FileHit)
├── output/               # 기본 출력 디렉토리 (gitignore)
│   ├── jpeg/
│   └── avi/
├── docs/
│   └── superpowers/
│       └── specs/
├── requirements.txt
├── .gitignore
└── CLAUDE.md
```

### 모듈 책임

| 모듈 | 책임 |
|------|------|
| `carve.py` | CLI 파싱, tqdm 진행률 출력, 파일 저장 조율 |
| `carver/scanner.py` | mmap 매핑, 시그니처 탐색, FileHit yield |
| `carver/extractors.py` | FileHit → 파일 경계 결정 → 바이트 추출 |
| `carver/models.py` | `FileHit` 데이터 클래스 정의 |

---

## 데이터 흐름

```
디스크 이미지(.img)
    │
    ▼
scanner.py (mmap + bytes.find)
    │ FileHit(type, offset)
    ▼
extractors.py (경계 결정)
    │ (offset, bytes)
    ▼
carve.py (파일 저장)
    │
    ▼
output/jpeg/0x{offset:08X}.jpg
output/avi/0x{offset:08X}.avi
```

---

## 핵심 컴포넌트

### FileHit (models.py)

```python
@dataclass
class FileHit:
    file_type: str   # "jpeg" | "avi"
    offset: int      # 디스크 이미지 내 바이트 오프셋
```

### scanner.py

- 디스크 이미지를 `mmap.mmap`으로 매핑 (읽기 전용)
- `bytes.find()`로 JPEG(`\xFF\xD8\xFF`) 및 AVI(`RIFF`) 시그니처를 순서대로 탐색
- AVI는 `RIFF` 발견 후 offset+8~11이 `AVI `인지 추가 검증 (WAV 등 다른 RIFF 포맷 제외)
- 발견된 위치마다 `FileHit`을 yield
- tqdm 업데이트를 위해 현재 스캔 위치를 콜백으로 전달

### extractors.py

**JPEG 추출:**
1. 오프셋부터 엔드 마커(`\xFF\xD9`) 탐색
2. 엔드 마커 발견 시 해당 위치까지 추출
3. 엔드 마커 없으면 최대 10 MB까지 추출 후 경고 로그 기록
4. `--min-jpeg-size` 미만이면 무시 (기본 1,024 bytes)

**AVI 추출:**
1. RIFF 헤더의 chunk size 필드(오프셋 4~7 바이트, little-endian uint32) 읽기
2. chunk size가 유효하면 (0 초과 && `--max-avi-size` 이하) 해당 크기만큼 추출
3. 비정상이면 다음 JPEG/AVI 시그니처 위치까지 추출 (fallback)
4. fallback도 `--max-avi-size`를 상한으로 적용

---

## CLI 인터페이스

```
python carve.py <image> [옵션]

필수:
  image                   디스크 이미지 파일 경로

옵션:
  -o, --output DIR        출력 디렉토리 (기본: ./output)
  --max-avi-size MB       AVI 최대 크기 MB (기본: 500)
  --min-jpeg-size BYTES   이 크기 미만 JPEG 무시 (기본: 1024)
```

**실행 예시:**
```bash
python carve.py usb.img -o output/ --max-avi-size 200 --min-jpeg-size 2048
```

**출력 예시:**
```
Scanning usb.img (3354.19 MB)...
[FOUND] JPEG at 0x01A3F000 → output/jpeg/0x01A3F000.jpg (45.2 KB)
[FOUND] AVI  at 0x03B20000 → output/avi/0x03B20000.avi (128.4 MB)
[WARN]  JPEG at 0x0FF10000 → no end marker, saved 10 MB (may be incomplete)
Scan complete. JPEG: 42, AVI: 3, Errors: 1
```

---

## 에러 처리 및 손상 대응

| 상황 | 처리 방식 |
|------|-----------|
| 파일 추출 중 예외 발생 | 해당 오프셋 건너뜀, `output/errors.log`에 기록 |
| JPEG 엔드 마커 없음 | 최대 10 MB 추출 후 경고 로그 |
| AVI chunk size = 0 또는 초과 | 다음 시그니처까지 fallback |
| AVI fallback도 `--max-avi-size` 초과 | 상한으로 잘라서 저장 |
| 출력 디렉토리 없음 | 자동 생성 |

모든 에러는 프로그램을 중단시키지 않고 계속 진행한다.

---

## 프로젝트 초기 설정

### .gitignore

```
*.img
output/
*.pyc
__pycache__/
.venv/
*.egg-info/
dist/
```

### requirements.txt

```
tqdm
```

### 커밋 메시지 규칙

Conventional Commits 형식, **한글**로 작성:

```
<타입>: <제목> (50자 이내)

<본문> — 변경 이유와 맥락을 한글로 서술.
무엇을 바꿨는지보다 왜 바꿨는지 중심으로 작성.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
```

**타입:**
- `feat` — 새 기능
- `fix` — 버그 수정
- `chore` — 빌드/설정 변경
- `docs` — 문서 수정
- `refactor` — 기능 변경 없는 코드 개선
- `test` — 테스트 추가/수정

**예시:**
```
feat: JPEG 파일 카빙 기능 추가

손상된 디스크 이미지에서 FF D8 FF 시그니처를 탐색해
JPEG 파일을 추출한다. 엔드 마커(FF D9)가 없는 경우
최대 10MB까지 추출 후 경고를 남긴다.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
```

### CLAUDE.md

프로젝트 개요, 실행 방법, 파일 구조, 커밋 규칙을 포함한다.

---

## 성공 기준

- 3.35 GB `usb.img`를 끝까지 스캔 완료
- 손상/쓰레기 값 구간에서 프로그램이 중단되지 않음
- 추출된 JPEG는 이미지 뷰어로 열리고, AVI는 영상 플레이어로 재생 가능 (손상 정도에 따라 일부 제한)
- `output/errors.log`로 추출 실패 오프셋 추적 가능
