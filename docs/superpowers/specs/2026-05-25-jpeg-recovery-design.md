# JPEG 복구 도구 설계 문서

**날짜**: 2026-05-25  
**브랜치**: feat/jpeg-recovery  
**대상**: rawcarve로 추출된 손상 JPEG 파일 복구

---

## 1. 배경 및 문제 정의

`rawcarve`가 추출한 `output/jpeg/` 내 JPEG 파일 812개를 분석한 결과,
상당수가 이미지 뷰어에서 회색(또는 검정)으로 표시된다.
HxD로 확인하면 스캔 데이터 자체는 살아있으나, 손상 방식에 따라
JPEG 디코더가 올바르게 디코딩하지 못하는 것이 원인이다.

**복구 원칙**: 손상된 바이트만 제외하고, 살아있는 데이터는 모두 살린다.
손상 이전 구간과 이후 구간 모두 디코딩하여 이미지 전체 크기를 유지한다.

---

## 2. 확인된 원인 5가지

분석 대상: 812개 파일 중 150개 무작위 샘플 + 추가 정밀 조사.

### 원인 1 — BAD_STUFF (Byte-Stuffing 위반)

**발생 비율**: 단독 32%, 복합 포함 ~47%  
**위치**: 스캔 데이터(엔트로피 코딩 영역)

JPEG 스캔 데이터 규칙: `0xFF` 다음에 반드시 `0x00`이 와야 한다.
디스크 손상으로 해당 `0x00`이 임의의 바이트로 교체되면,
libjpeg 디코더가 그 지점을 마커로 오해하고 sync를 잃는다.

```
정상: ... e4 ff 00 9c ...   <- FF 00 = stuffed byte
손상: ... e4 ff ec 9c ...   <- FF EC = 불법 시퀀스 -> 디코더 sync 상실
```

**결과**: 첫 위반 지점 이후 모든 MCU 블록이 128(중간 회색)로 채워짐.  
**핵심 사실**: 첫 위반 이후 데이터는 **96~99% 다양성으로 살아있음**.

---

### 원인 2 — GRAY_MCU_INJECTION (회색 MCU 패턴 주입)

**발생 비율**: BAD_STUFF와 복합 발생  
**특징 패턴**: `01 45 00 14 50` 반복 (20~425바이트)

JPEG에서 "DC 계수=0(변화 없음), AC 계수 전부 0(EOB)"을 인코딩하면
`01 45 00 14 50`이 반복되는 패턴이 된다.
이 패턴이 스캔 데이터에 삽입되면 두 가지 피해가 발생한다.

1. **직접 피해**: 해당 MCU 블록들이 단색 회색으로 렌더링됨
2. **연쇄 피해**: DC 예측기(DC predictor) 값이 0으로 리셋되어,
   패턴 이후의 **원본 데이터도 엉뚱한 밝기로 디코딩**됨

```
[정상 스캔] [01 45 00 14 50 x N] [원본 데이터 -- 살아있지만 DC 상태 파괴]
```

---

### 원인 3 — FALSE_POSITIVE (가짜 시그니처)

**발생 비율**: 비정렬 파일의 ~57%

`\xff\xd8\xff` 패턴이 JPEG가 아닌 이진 데이터(AVI 프레임 경계,
파일 시스템 메타데이터 등) 내부에서 검출된 경우.
SOF 마커가 없거나, 컴포넌트 수 195·208 같은 불가능한 값을 가진다.  
**복구 불가** — 원본 데이터 자체가 JPEG가 아님.

---

### 원인 4 — TRUNCATED_SCAN (스캔 데이터 조기 종료)

**발생 비율**: 소수

헤더는 정상이고 BAD_STUFF도 없지만, 선언된 이미지 크기(예: 2816x2112)에
필요한 스캔 데이터보다 파일이 일찍 끝난다.
디코더가 EOF를 만나면 나머지 MCU 행을 회색으로 채운다.
EOI(`FF D9`)가 없는 경우가 많다.

---

### 원인 5 — MARKER_BYTE_FLIP (헤더 마커 1바이트 손상)

**발생 비율**: 미측정 (10개 샘플 중 1건 확인)

헤더 마커 바이트 1개가 단일 비트 오류로 다른 마커로 변경된 경우.

```
확인된 사례: FF DB (DQT) -> FF CB (SOF11 -- 산술 부호화)
  DB = 1101 1011
  CB = 1100 1011  <- 4번 비트 1개 플립
```

libjpeg는 SOF11을 지원하지 않으므로
`cannot identify image file`로 완전히 열기 실패한다.
스캔 데이터는 멀쩡하지만 마커 1바이트 때문에 전체가 막힘.

---

### 오탐 범주 (복구 불필요)

- **진짜 어두운 이미지**: (0,0,0) 픽셀 → 어두운 장면 촬영본. 손상 아님.
- **자연스러운 저채도 피사체**: 콘크리트, 흐린 하늘 등. chroma < 15이지만 합법적 이미지.
- 복구 도구가 이들을 처리 대상으로 삼지 않도록 판별 로직이 필요하다.

---

## 3. 복구 도구 설계

### 3.1 개요

```
입력: output/jpeg/           (rawcarve가 추출한 원본)
출력: output/jpeg_recovered/ (복구된 파일)
      output/jpeg_recovered/report.csv (진단 리포트)
```

별도 스크립트 `recover.py`로 구현. `carve.py`와 독립 실행.

```
python recover.py output/jpeg/ [-o output/jpeg_recovered/]
```

---

### 3.2 처리 파이프라인

```
파일 하나에 대해:

1. DIAGNOSE  -- 원인 분류 (5가지 + CLEAN + FALSE_POSITIVE)
2. RECOVER   -- 원인별 전략 적용
3. VALIDATE  -- 복구 결과 픽셀 검증 (손상 블록 비율 재측정)
4. SAVE      -- 복구 파일 저장 + 리포트 행 기록
```

---

### 3.3 진단 모듈 (`carver/diagnosis.py`)

각 파일을 분석해 `DiagnosisResult` 반환.

```python
@dataclass
class DiagnosisResult:
    causes: list[str]              # ["BAD_STUFF", "GRAY_MCU"] 등
    first_bad_offset: int | None   # 스캔 내 첫 BAD_STUFF 위치
    gray_run_offset: int | None    # GRAY_MCU 패턴 시작 위치
    gray_run_len: int              # 패턴 바이트 수
    scan_start: int                # 파일 내 스캔 데이터 절대 오프셋
    has_eoi: bool
    sof: tuple | None              # (w, h, ncomp)
    broken_marker: int | None      # MARKER_BYTE_FLIP 대상 마커 값
```

**판별 로직 우선순위**:
1. SOF 없음 또는 불가능한 값 → `FALSE_POSITIVE`
2. 헤더 마커 바이트 이상 → `MARKER_BYTE_FLIP`
3. 스캔 데이터 내 `FF XX` (XX != 00, D0-D9) → `BAD_STUFF`
4. `01 45 00 14 50` x 4 이상 반복 → `GRAY_MCU`
5. 스캔 데이터 50%+ 제로 → `ZERO_FILL`
6. 이상 없음 → `CLEAN`

---

### 3.4 복구 전략

**기본 원칙**: 손상된 바이트만 제외하고 살아있는 데이터는 모두 살린다.
이미지 전체 크기(원본 선언 w×h)를 유지한다.

#### BAD_STUFF — 바이트 교정 우선, 실패 시 강제 디코딩 + 보간

RST 마커가 없어도 BAD_STUFF의 주요 손상 형태(`FF 00`의 `00`이 다른 바이트로 교체)는
직접 패치로 원본 비트스트림을 복원할 수 있다.

**1차 시도: FF→00 바이트 교정 (원본 픽셀 복원 가능)**

```
손상: ... e4 ff ec 9c ...   <- FF EC = 불법 시퀀스
패치: ... e4 ff 00 9c ...   <- FF 00 = 정상 stuffed byte

패치 후 이후 비트스트림이 복원되어 원본 픽셀 그대로 디코딩 가능.
```

```
1단계: 스캔 데이터에서 FF XX (XX != 00, D0-D9) 위치 전체 수집
2단계: 각 위치의 XX를 00으로 교체한 바이트열을 메모리에서 구성
3단계: 교정된 바이트열을 LOAD_TRUNCATED_IMAGES=True 로 디코딩 시도
4단계: 손상 블록 비율 측정
       - 10% 미만 -> 교정 성공 -> 보간 없이 JPEG(quality=85) 저장
       - 10% 이상 -> 교정 부분 성공 -> 손상 블록에 보간 적용 후 저장
```

**2차 시도 폴백: 강제 디코딩 + 보간 (추정값)**

바이트 교정 후에도 손상 블록이 과도하게 남는 경우(바이트 교정 실패):

```
1단계: 원본 파일을 LOAD_TRUNCATED_IMAGES=True 로 강제 디코딩
       (손상 구간: 디코더 오류 복구로 정확히 (128,128,128)으로 채워짐)

2단계: 손상 블록 감지 (8x8 픽셀 블록 단위)
       판정: 블록 내 모든 픽셀이 (128+-2, 128+-2, 128+-2) 이면 손상 블록
       근거: libjpeg 오류 복구값은 정확히 128 / 자연 회색은 근방의 다양한 값

3단계: 손상 블록 보간
       각 손상 블록에서 상하좌우로 최대 16블록 반경 내
       유효(비손상) 블록을 탐색, 거리 역수 가중 평균으로 대체

4단계: JPEG(quality=85)로 재저장
```

> **손상 블록 비율이 90% 이상**이면 보간 기준점이 없으므로
> `SKIP_TOO_DAMAGED`로 기록하고 파일을 생성하지 않는다.

#### GRAY_MCU / TRUNCATED_SCAN — 강제 디코딩 + 손상 블록 보간

바이트 교정이 적용 불가한 원인 유형. 강제 디코딩 후 손상 블록을 보간으로 채운다.

```
예시:
원본 디코딩: [정상] [정상] [128,128,128] [128,128,128] [정상] [정상]
보간 후:     [정상] [정상] [보간값]       [보간값]       [정상] [정상]
```

> **손상 블록 비율이 90% 이상**이면 `SKIP_TOO_DAMAGED`로 기록하고 파일을 생성하지 않는다.

#### MARKER_BYTE_FLIP — 마커 바이트 교정 후 보간

알려진 단일 비트 플립 후보를 시도한다.

```python
CANDIDATE_FIXES = {
    0xCB: 0xDB,  # SOF11 -> DQT
    0xC3: 0xC0,  # SOF3  -> SOF0
    0xC5: 0xC4,  # SOF5  -> DHT
    # ... 필요 시 추가
}
```

교정된 바이트로 파일을 메모리에서 패치 → 강제 디코딩 시도.
성공하면 BAD_STUFF와 동일한 손상 블록 보간 단계 적용 후 저장.

#### FALSE_POSITIVE — 건너뜀

SOF 자체가 없거나 불가능한 값이라 디코딩 기준점이 없다.
리포트에 `SKIP_FALSE_POSITIVE` 기록.

#### ZERO_FILL — 건너뜀

스캔 데이터가 대부분 제로인 파일은 보간할 유효 블록이 없다.
`SKIP_ZERO_FILL` 기록.

---

### 3.5 출력 파일명 규칙

```
원본:   output/jpeg/0x17349000.jpg
복구:   output/jpeg_recovered/0x17349000.jpg
리포트: output/jpeg_recovered/report.csv
```

복구가 불가능하거나 이미 CLEAN인 경우 `jpeg_recovered/`에 파일 생성 안 함.

---

### 3.6 리포트 CSV 컬럼

| 컬럼 | 설명 |
|------|------|
| `filename` | 원본 파일명 |
| `causes` | 감지된 원인 목록 (`;` 구분) |
| `action` | RECOVERED_PATCHED / RECOVERED_INTERPOLATED / SKIP_FALSE_POSITIVE / SKIP_ZERO_FILL / SKIP_TOO_DAMAGED / CLEAN / ERROR |
| `damaged_block_pct` | 원본 손상 블록 비율 (보간 전) |
| `recovered_block_pct` | 복구 후 잔여 손상 블록 비율 |
| `cut_offset_kb` | 첫 손상 감지 위치 (KB) |
| `image_size` | 복구된 이미지 w×h |

---

## 4. 모듈 구조

```
rawcarve/
├── recover.py                  # CLI 진입점
└── carver/
    ├── diagnosis.py            # DiagnosisResult, diagnose(path)
    └── recovery.py             # recover_file(path, diagnosis) -> Path | None
```

기존 `carver/extractors.py`, `carver/scanner.py`는 수정하지 않는다.

---

## 5. 한계 및 제외 범위

- **RST 마커 기반 재동기화**: 현재 추출 파일에 RST 마커가 거의 없어 구현 제외.
  향후 개선 시 추가 고려.
- **DCT 도메인 보간**: 복잡도 대비 효과 불확실. 픽셀 도메인 보간으로 대체.
- **OpenCV inpainting**: 외부 의존성 증가. Pillow + numpy만으로 처리.
- **BAD_STUFF 이후 비트 오프셋 탐색**: 비트 오프셋 완전 탐색(0~7)이 필요하며
  성공 보장 없음. FF→00 바이트 교정으로 대부분 커버되므로 1차 구현에서 제외.
- **손상 블록 감지 오탐**: 정확히 (128,128,128)인 자연 피사체(특정 중간 회색 표면)를
  손상으로 오판할 수 있다. 허용 오차(±2)를 좁게 유지해 오탐을 최소화한다.

---

## 6. 성공 기준

- 원인 분류 정확도: 10개 수동 검증 파일 기준 5/5 원인 정확 식별
- 복구 성공: BAD_STUFF 파일에서 손상 블록이 보간 후 육안으로 개선됨
- 이미지 크기 유지: 복구된 파일의 w×h가 원본 SOF 선언과 동일
- MARKER_BYTE_FLIP 파일 1개 이상 열기 성공 후 보간 적용
- FALSE_POSITIVE 파일은 `output/jpeg_recovered/`에 생성되지 않음
- 기존 `carve.py` 동작에 영향 없음
