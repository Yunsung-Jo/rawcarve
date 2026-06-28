# JPEG 마커 구조 레퍼런스

- **출처:** ITU-T T.81 (1992) — https://www.w3.org/Graphics/JPEG/itu-t81.pdf;
  Wikipedia "JPEG § Syntax and structure" — https://en.wikipedia.org/wiki/JPEG#Syntax_and_structure;
  Wikibooks "JPEG – Idea and Practice/The header part" — https://en.wikibooks.org/wiki/JPEG_-_Idea_and_Practice/The_header_part
- **최종 수정:** 2026-06-29

---

## 1. 세그먼트 구조

```
FF XX [길이 2바이트 big-endian] [데이터]
```

- **길이 필드**는 자신(2바이트)을 포함한다. 데이터 바이트 수 = 길이 − 2.
- **FF 필 바이트(fill byte):** 마커 직전에 `FF FF ...` 형태로 패딩이 올 수 있다 (§B.1.1.2 허용).
  파서는 `FF` 바이트를 만나도 다음 바이트가 또 `FF`이면 계속 읽어야 한다.

## 2. 마커 코드 표

| 마커 | 코드 | 길이 필드 | 설명 |
|------|------|-----------|------|
| SOI  | `FF D8` | 없음 | Start Of Image — JPEG 시작 시그니처 |
| EOI  | `FF D9` | 없음 | End Of Image — JPEG 종료 시그니처 |
| SOF0 | `FF C0` | 있음 | Start Of Frame (Baseline DCT) |
| SOF1 | `FF C1` | 있음 | Start Of Frame (Extended Sequential DCT) |
| SOF2 | `FF C2` | 있음 | Start Of Frame (Progressive DCT) |
| SOF3 | `FF C3` | 있음 | Start Of Frame (Lossless) |
| SOF5 | `FF C5` | 있음 | Start Of Frame (Differential Sequential DCT) |
| SOF6 | `FF C6` | 있음 | Start Of Frame (Differential Progressive DCT) |
| SOF7 | `FF C7` | 있음 | Start Of Frame (Differential Lossless) |
| SOF9 | `FF C9` | 있음 | Start Of Frame (Extended Sequential, Arithmetic) |
| SOF10 | `FF CA` | 있음 | Start Of Frame (Progressive, Arithmetic) |
| SOF11 | `FF CB` | 있음 | Start Of Frame (Lossless, Arithmetic) |
| SOF13 | `FF CD` | 있음 | Start Of Frame (Differential Sequential, Arithmetic) |
| SOF14 | `FF CE` | 있음 | Start Of Frame (Differential Progressive, Arithmetic) |
| SOF15 | `FF CF` | 있음 | Start Of Frame (Differential Lossless, Arithmetic) |
| DHT  | `FF C4` | 있음 | Define Huffman Table |
| DQT  | `FF DB` | 있음 | Define Quantization Table |
| DRI  | `FF DD` | 있음 | Define Restart Interval (페이로드 4바이트: 길이 2 + 간격 2) |
| SOS  | `FF DA` | 있음 | Start Of Scan — 이후 스캔 데이터가 따라옴 |
| RST0–RST7 | `FF D0`–`FF D7` | 없음 | Restart Marker (엔트로피 코딩 경계) |
| APP0 | `FF E0` | 있음 | Application (JFIF 헤더) |
| APP1 | `FF E1` | 있음 | Application (Exif / XMP) |
| APP2–APP15 | `FF E2`–`FF EF` | 있음 | Application (기타) |
| COM  | `FF FE` | 있음 | Comment |
| TEM  | `FF 01` | 없음 | Temporary (arithmetic coding 전용; 실무에서 거의 없음) |

> **길이 없는 마커 요약:** SOI(`D8`), EOI(`D9`), RST0–RST7(`D0`–`D7`), TEM(`01`)

## 3. SOS 이후 스캔 데이터 파싱

SOS 세그먼트 직후 스캔 데이터가 이어진다.

### 스캔 데이터 안에서 FF 처리 규칙

| 시퀀스 | 의미 | 처리 |
|--------|------|------|
| `FF 00` | Stuffed byte (엔코더가 삽입한 FF 이스케이프) | `FF` 데이터로 해석, 계속 읽기 |
| `FF D0`–`FF D7` | RST 마커 | 스캔 계속 (경계 아님) |
| `FF D9` | EOI | 스캔 종료, 파일 끝 |
| `FF FF` | Fill byte | 다음 바이트 다시 확인 |
| 그 외 `FF XX` | 유효 JPEG 마커 (또는 비트 플립) | 스캔 경계로 처리 |

**위반(violation):** 스캔 데이터 안에서 `FF 00`, RST, fill byte, EOI 이외의 `FF XX` 시퀀스는
스펙 위반(손상)이다. 이런 가짜 마커는 디코더를 멈춰 회색을 만든다. 손상이 마커를 안 만들면
대신 비트 정렬이 어긋나(디싱크) 깨진 출력이 된다. 원인·복구는
[JPEG 엔트로피 코딩과 디싱크 원리](jpeg-entropy-coding.md)와 `carver/resync.py` 참조.

**가짜 EOI:** 반대로 손상이 stuffing(`FF`→`FF 00`)을 깨 엔트로피 중간에 `FF D9`를 만들면,
카버가 이를 진짜 EOI로 오인해 파일을 일찍 자를 수 있다(누락 데이터 발생). 진짜 EOI는 직후가
다른 것(다음 파일 헤더·패딩 → 저엔트로피)이고, 가짜는 직후가 엔트로피 연속(`FF` 다음 `00`/RST
비율이 높음)이라는 차이로 구분한다. 근거: [ADR 0002](../adr/0002-carve-eoi-validation.md).

## 4. SOF 세그먼트 레이아웃 (SOF0 기준)

```
FF C0 [길이] [정밀도 1B] [높이 2B big-endian] [너비 2B big-endian]
             [컴포넌트 수 1B] [컴포넌트 정보 × N]
```

- 오프셋: `FF C0` + 2(길이) + 1(정밀도) + 2(높이) + 2(너비) + 1(컴포넌트 수) → 총 9바이트
- 코드 기준: `pos+5`–`pos+6` = 높이, `pos+7`–`pos+8` = 너비, `pos+9` = 컴포넌트 수
- 소비자 카메라 JPEG은 대부분 Baseline DCT(SOF0)만 사용한다.

## 5. 헤더 마커 비트 플립 패턴 (실측, 참고)

손상된 디스크 이미지에서 관측된 *헤더* 마커 바이트 플립:

| 손상된 마커 | 원래 마커 | 설명 |
|------------|----------|------|
| `FF CB` (SOF11) | `FF DB` (DQT) | 0xCB → 0xDB: 비트 4 플립 |
| `FF C3` (SOF3) | `FF C0` (SOF0) | 0xC3 → 0xC0: 비트 1,0 플립; 소비자 JPEG에서 SOF3는 비현실적 |
| `FF C5` (SOF5) | `FF C4` (DHT) | 0xC5 → 0xC4: 비트 0 플립; 소비자 JPEG에서 SOF5는 비현실적 |

> **현재 범위:** resync 복구 엔진은 *엔트로피* 디싱크에 집중한다. 헤더 마커가 손상돼 파싱이
> 불가능한 파일은 `SKIP_UNDECODABLE`로 처리한다(헤더 마커 교정은 현재 미구현). 위 표는
> 향후 헤더 복구를 다룰 때를 위한 참고 자료다.

## 6. JPEG 시그니처

```
FF D8 FF
```

- 디스크 이미지 스캔 시 3바이트 시퀀스 `FF D8 FF`를 탐색한다.
- `FF D8`만으로는 오탐 가능성이 있어 세 번째 바이트 `FF`(다음 세그먼트 시작)까지 포함한다.
- **EXIF 썸네일 주의:** APP1(`FF E1`) Exif 세그먼트 안에는 축소판 **썸네일 JPEG**가 통째로 내장될 수 있다(`FF D8 FF … FF D9`). 따라서 한 파일의 **엔트로피 시작(SOS) 이전 헤더 안에서도 `FF D8 FF`가 나타난다**(실측: 메인 SOI로부터 +844, +41970 등). 카버는 이를 별도 파일로 오인하면 안 된다 — 메인 파일 범위 안의 시그니처는 임베디드로 처리하고([spec 0001-carve](../specs/0001-carve.md) 엣지 케이스), 파일 끝(다음 파일 경계)을 찾을 때는 엔트로피 시작 **이후**의 `FF D8 FF E0–EF`만 다음 파일 헤더로 본다(`extractors.py::_next_header`).
