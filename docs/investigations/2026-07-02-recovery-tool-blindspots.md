# 조사 기록 — 잔존 회색·SKIP의 도구 측 원인 3종: DHT 소실 66건, 소형 이미지 수락 임계 잠금 196건, 계수 경계 미보정

- **날짜:** 2026-07-02
- **한 줄:** report.csv 822건 전수 재질의로 시작 → (1) SKIP_UNDECODABLE 122건은 전부 헤더 손상(그중 DHT 완전 소실 66건 — 다수파 테이블 이식만으로 plain 디코드 복원 실증), (2) RECOVERED 중 undec 악화 66건의 주원인은 소형 이미지의 resync/edit 수락 임계 잠금(실제 MCU<450 196건 — 잔여 MCU 비례 임계로 4/5 복구 실증), (3) 제2 quant 계열에서 DC/AC 계수 경계(err 3) 오탐. 셋 다 "데이터 한계"가 아닌 도구 한계. 구현은 미착수(발견만 기록).
- **결론 문서:** 아직 없음(후속 작업이 ADR/spec으로 확정할 것). 후속 항목은 [백로그](../backlog.md), 포맷 사실은 [JPEG 엔트로피 코딩 레퍼런스 §Annex-K 전형 테이블](../reference/jpeg-entropy-coding.md) 참조.

> **시점 기록(랩 노트).** 사용자 요청("현 방향 분석 + 복구율 개선 여지/방향 오류 피드백")으로 수행한
> 전수 데이터 재질의·검증 실험의 기록. experiment-loop의 개선 루프가 아니라 **발견 단계**다 —
> 어떤 코드도 변경하지 않았고, 모든 실험은 monkeypatch/수동 구성으로 본체를 우회해 수행했다.
> 다음 세션이 이 문서만으로 재현하고 이어갈 수 있도록 수치·스니펫을 그대로 남긴다.

---

## 증상 (조사 동기)

버그 리포트가 아니라 체계적 재질의다. 시작 시점의 상태:

- 데이터: `output/jpeg/` 822건(carve-eoi 수정 이후), `output/jpeg_recovered/report.csv`(DC=0 리셋 전수 실행, `--time-budget 0`, [ADR 0004](../adr/0004-resync-dc-reset-recovery.md) 수치와 일치 — RECOVERED 557 / CLEAN 143 / SKIP_UNDECODABLE 122).
- RECOVERED 평균 undec 0.353→0.092로 개선됐으나, **undec_after 분포의 꼬리가 미질의 상태**였다: <1% 352건, 1–5% 55건, 5–15% 57건, 15–30% 37건, 30–60% 24건, ≥60% 32건.
- SKIP 122건(15%)은 "3-component baseline 아님"이라는 예외 메시지로만 분류돼 있었고 실제 원인 분포는 미확인.
- 기존 결론([skew 조사](2026-07-01-resync-skew-underconsumption.md))은 "잔존 회색 = 데이터 한계"였는데, 이 결론이 hole 1·ops 0인 70건 전부를 설명하는지 검증된 적이 없었다.

## 조사 과정 (가설 → 예측 → 증거)

### 1단계 — report.csv 전수 재질의: worst는 대형 중손상이 아니라 "소형 + 무행동"

- **가설 / 세운 이유:** 남은 개선 여지는 undec_after 상위(worst) 케이스에 있다. 기존 결론대로라면 worst는 대형·중손상 파일(데이터 소진 계열)일 것.
- **실험:** report.csv 파싱 — action 분포, undec_after 분포, worst 25 목록, `undec_after > undec_before + 0.01`(악화) 집계, `ops=0 & hole≥1`(무행동) 집계.
- **예측:** worst 25는 2816×2112급 대형에 ops(편집·재동기 수) 수십 회짜리가 주를 이룰 것.
- **증거:** 예측과 다름. worst 25 전원이 **ops 0 · resync 0 · hole 1**(편집·재동기 0회, 첫 디싱크 지점에서 hole로 종료)이고, 대부분 소형(96×72, 240×240, 324×243, 345×459, 320×240, …)이며 대형은 3건뿐(0x95AAD000 2816×2112 등). 특히 `undec 0.000 → 0.9xx` **악화** 조합이 다수:
  - 0xB164690C (96×72): undec 0.000→1.000, gray 0.125→1.000
  - 0xC93EC000 (324×243): undec 0.000→0.928, gray 0.080→0.928
  - 0xC93D0000 (240×240): undec 0.000→0.750, gray 0.021→0.768
  - 0xC8069000 (240×320): undec 0.000→0.843, gray 0.426→0.843
  - 집계: 악화 66건(악화폭 합 +23.40, 평균 +0.354), 그중 55건이 50만 픽셀 미만. 무행동(ops 0·hole≥1) 70건.
- **판단:** 가설 기각. worst의 주류는 "중손상 대형"이 아니라 "편집·재동기가 한 번도 수락되지 않은 소형"이다. gray_before 0.080~0.426(plain 디코드가 대부분을 비회색으로 채움)인데 복구본이 0.75~1.00 회색이라는 것은, 디코드 가능한 영역을 폐기하는 경로가 있다는 뜻. 수락 임계와 이미지 크기의 관계를 대조한다(2단계).

### 2단계 — 소형 이미지 수락 임계 잠금: 코드 상수 대조 + 전수 실측

- **가설 / 세운 이유:** 1단계 worst가 전부 소형+무행동. 코드의 수락 임계는 절대 MCU 수 기준이다 — `_resync_skip` 수락 `best[1] >= max(250, maxW//2)`(maxW=900이므로 **450**, `carver/resync.py:182`), 편집 수락 `run > 120`(`carver/resync.py:232`). 한편 probe의 clean run은 maxW와 잔여 MCU 수에서 캡된다. **총 MCU가 450 미만이면 resync 수락이 산술적으로 불가능**하지 않은가.
- **실험:** ① 전 RECOVERED의 헤더를 파싱해 실제 MCU 수(`mcus_x×mcus_y`)를 계산, 임계와 대조. ② 잠금 의심 파일 4건을 plain full 디코드(경계 비활성, `decode_full`)와 엔진 첫 정지점(`_decode_traj` stop=True의 frontier)으로 비교.
- **예측:** MCU<450인 파일은 report에서 resync=0일 것. plain 디코드는 에러 없이 끝까지 가는 파일이 있을 것(= 엔트로피가 형식적으로는 온전).
- **증거:**
  - 전수: RECOVERED 557 중 **실제 MCU<450 = 196건**(재동기 수락 원천 불가), **MCU≤120 = 42건**(편집 수락도 불가). 잠금군 중 undec_after>0.15 = **46건**(undec_after 합 27.1 — 46개 이미지 분량의 미복구 면적).
  - 파일별 (plain 디코드 vs 엔진 정지점):

    | 파일 | MCU 총수 | plain 디코드 | 엔진 frontier(첫 정지) | rate |
    |------|---------|-------------|----------------------|------|
    | 0xB164690C | 30 | 30/30 err 0 | 0 | 2499 |
    | 0xC93EC000 | 336 | 336/336 err 0 | 23 | 3114 |
    | 0xC93D0000 | 225 | 225/225 err 0 | 56 | 2602 |
    | 0xC8069000 | 300 | 300/300 err 0 | — | — |

  - 인과 사슬: 첫 디싱크(plausibility 경계 발동) → `_best_edit` run>120 불가(0xB164690C: 총 30 MCU) 또는 미달 → `_resync_skip` 수락 450 불가(잔여 MCU < 450) → hole → 최종 렌더가 stop=True(`carver/resync.py:245`)라 frontier 이후 전량 회색.
- **판단:** 지지. 소형 이미지는 임계 구조상 편집도 재동기도 수락될 수 없고, 첫 디싱크 지점 이후를 전부 버린다. 1단계의 악화 66건 중 소형 55건이 이 부류. 주의: plain 디코드 err 0이 콘텐츠 **진위**를 보장하지는 않는다(디싱크 상태에서도 유효 코드가 우연히 이어질 수 있음) — 진위는 4단계(독립 재동기 지점 발견)와 7단계(이식 후 undec 0.000)에서 별도로 확인된다.

### 3단계 — maxW만 축소 → 실패 (파생 임계의 바닥 상수)

- **가설 / 세운 이유:** 2단계에서 수락 임계가 maxW 파생(`max(250, maxW//2)`)이므로, `recover(dec, maxW=총MCU//2)`로 maxW만 줄이면 잠금이 풀릴 것.
- **실험:** 0xC93EC000·0xC8069000·0xC93D0000에 `rs.recover(dec, maxW=max(60, total//2), time_budget=60)` (maxW 168/150/112).
- **예측:** 세 파일 모두 resync가 수락돼 undec 대폭 감소.
- **증거:** 세 파일 모두 불변(hole 1 · ops 0, undec 0.928/0.843/0.750 유지).
- **판단:** 기각. 수락식의 **250 바닥**이 살아 있는 채 probe 캡(maxW)만 168 이하로 줄면, run은 168을 넘을 수 없는데 수락은 250을 요구 — 오히려 수락 불가가 확정된다. 임계 체계 전체(캡·수락·편집 수락)를 잔여 MCU에 비례시켜야 한다(4단계).

### 4단계 — 잔여 MCU 비례 임계 → 5건 중 4건 복구 실증

- **가설 / 세운 이유:** 3단계 기각 근거에서 도출: probe 캡 `W = min(900, 잔여MCU)`, resync 수락 `max(30, 0.55·W)`, 편집 수락 `min(120, max(20, 0.4·잔여MCU))`, 편집 개선폭 `min(30, 잔여//4)`로 전면 비례화하면 소형에서도 수락 가능.
- **실험:** `recover`/`_resync_skip`를 위 파라미터로 복제한 함수(본체 미변경, 스니펫은 '사용한 방법' 절)로 잠금군 5건 재복구. masking 가드(`|db|≥24`)와 나머지 로직은 동일 유지.
- **예측:** 5건 모두 undec 감소, 특히 frontier가 앞쪽(MCU 23)인 0xC93EC000이 크게.
- **증거:**

  | 파일 | MCU | undec_after 현행 → 스케일 | stats |
  |------|-----|--------------------------|-------|
  | 0xC91AF000 | 336 | 0.961 → **0.004** | resync 1 |
  | 0xC93EC000 | 336 | 0.928 → **0.181** | resync 1 |
  | 0xC8BC4000 | 540 | 0.799 → **0.087** | resync 1 |
  | 0xC93D0000 | 225 | 0.750 → **0.316** | resync 1 |
  | 0xC8069000 | 300 | 0.843 → 0.843 (불변) | hole 1 |

  육안 검증(지표·결함 패턴): 재동기 세그먼트가 고주파 비반복 텍스처로 채워짐 — masking형 주기 반복·평탄 단색 패턴 아님. 0xC93EC000은 세그먼트 경계에서 수평 밀림 결함 존재(기지 보류 항목: 이미지 밀림).
- **판단:** 지지(4/5). 단 **수락 임계 완화는 masking 위험을 키운다** — 소형에서 수락 run이 최소 30 MCU까지 내려가므로, 본 적용 시 `|db|≥24` 가드 유지 + 파일별 undec 회귀 가드(현행 엔진 출력과 비교) + 육안 표본 검증이 전제 조건. 0xC8069000은 스케일 임계로도 재동기 지점이 없음(원인 미조사 — 후속 항목).

### 5단계 — SKIP 122건 원인 전수 분류: 전부 헤더 손상, progressive는 1건

- **가설 / 세운 이유:** 1단계에서 SKIP이 122건(전체 15%)인데 원인 미분류. 예외 메시지("3-component baseline JPEG만 지원")대로라면 progressive 등 exotic 포맷이 주류일 것.
- **실험:** 전 SKIP에 `parse_header`/`Decoder` 재시도, 예외 메시지를 그룹화. 별도로 마커 워크로 SOF 계열 마커 존재를 스캔.
- **예측:** SOF2(progressive) 다수.
- **증거:**

  | 건수 | 원인 그룹 |
  |------|----------|
  | 60 | comps=쓰레기값 (SOF는 있으나 필드 깨짐 — comps=6, 9, 739, 1006 등) |
  | 42 | comps=0 (SOF 마커 자체 미발견) |
  | 8 | SOS 미발견 (w/h는 정상 파싱 — 예: 96×72, sos=-1) |
  | 6 | 허프만 테이블 인덱스 범위 초과 (SOF/SOS 필드 손상) |
  | 3 | 비정상 샘플링 계수 |
  | 3 | 기타 KeyError (SOF-SOS 컴포넌트 ID 불일치) |

  SOF 마커 스캔: 마커 없음 76 / SOF0 43 / SOF2 1 / SOF7 1 / SOFB 1 (합 122). **진짜 비-baseline은 SOF2 1건뿐**, SOF7·SOFB는 손상 바이트가 마커처럼 보이는 것으로 추정(비현실적 포맷).
- **판단:** 예측 기각, 더 큰 발견 — SKIP은 포맷 비지원 문제가 아니라 **전부 헤더 손상**이다. 현행 엔진은 설계상 엔트로피 스트림만 편집하므로(`recover`는 `dec.buf`만 다룸) 헤더 손상 축이 통째로 복구 범위 밖이었다. 헤더의 어떤 세그먼트가 깨지는지 정량화한다(6단계).

### 6단계 — DHT 지문 집계: 66건은 DHT 완전 소실 + Decoder 빈 huff 미검증 버그

- **가설 / 세운 이유:** 5단계에서 헤더 손상이 SKIP의 전부. 같은 카메라 파일들은 테이블이 같을 것이므로, DHT를 md5 지문으로 전수 집계하면 다수파(정상)와 이탈(손상/소실)이 갈릴 것. 또 RECOVERED인데 undec 1.000·hole 1인 0x95AAD000(2816×2112, 엔트로피 3,025,554바이트, plain 디코드 0/46464 err 1 — 데이터가 있는데 첫 MCU부터 무효 코드)의 원인 후보다.
- **실험:** 822건 전수 `parse_header` 후 `huff` dict를 정렬-repr-md5로 지문화.
- **예측:** 다수파 지문 1종 + 소수 이탈. 0x95AAD000은 이탈군일 것.
- **증거:**
  - 지문 53종 / 822건: **다수파 `332c3e17` 704건**, **`d7517139` 66건**, 2건짜리 1종, 단일 50종.
  - `d7517139` = **빈 dict의 지문**(`hashlib.md5(repr(sorted([])))`로 확인) — 즉 66건은 DHT 세그먼트가 0개다. 분해: SKIP 64 + RECOVERED 2(0x95AAD000, 0xCA9AA000 — 둘 다 undec_after 1.000).
  - RECOVERED 2건이 통과한 경위 = **버그**: `Decoder.__init__`은 `hl/hs`를 0으로 초기화한 뒤 `h.huff` 항목만 채우는데(`carver/jpegdecode.py:380-385`) 빈 huff에 대한 검증이 없어 all-zero LUT로 진행 → 모든 코드가 무효(err 1) → MCU 0 정지 → 전량 회색인 채 RECOVERED로 분류·재인코딩 저장.
  - 단일 지문 50종은 두 부류가 섞여 있다: (a) **손상** — 96×72 SKIP·고회색군(0xB164690C, 0x92E6CB4C, 0xB164344C, 0xB164250C, 0xB15DD14C 등 각자 다른 지문), (b) **정상 이탈(다른 인코더)** — 480×270 계열 등 undec_after 0.008~0.019로 정상 복구되는 파일. **지문 이탈만으로 손상이라 단정할 수 없고, 판별은 이식 probe가 확정적**(7단계).
  - 다수파 `332c3e17`의 정체: counts·symbols를 int 정규화 후 대조하면 **ITU T.81 Annex K 전형 테이블과 완전 일치**(4클래스 전부). → [레퍼런스 §Annex-K](../reference/jpeg-entropy-coding.md)에 기록.
- **판단:** DHT 소실 66건 + DHT 바이트 손상 수 건 확인. 이 파일들은 엔트로피가 남아 있다면 **테이블 이식**으로 디코드를 복원할 수 있을 것(7단계). Decoder 빈 huff 미검증은 즉시 고칠 수 있는 분류 버그(후속).

### 7단계 — DHT 이식 실험: plain 디코드만으로 5건 undec ≤0.26 복원

- **가설 / 세운 이유:** 6단계에서 다수파 테이블 = Annex-K 전형 = 이 카메라의 테이블. DHT 소실/손상 파일에 다수파 테이블을 이식하면 엔트로피가 살아있는 한 디코드될 것.
- **실험:** `parse_header` 후 `h.huff = donor.huff`(기증자: 0xC93D0000, 다수파)로 교체한 Decoder를 수동 구성(스니펫은 '사용한 방법' 절), **resync 없이** `decode_full`만 실행.
- **예측:** DHT 소실 2건(0x95AAD000·0xCA9AA000)과 단일 지문 96×72군이 MCU 0부터 디코드 시작. 엔트로피 손상이 있는 파일은 도중 정지.
- **증거:**

  | 파일 | 현행 undec_after | 이식 후 plain 디코드 | 이식 후 undec |
  |------|------------------|---------------------|---------------|
  | 0x92E6CB4C (96×72) | 0.991 | 30/30 err 0 | **0.000** |
  | 0xB164250C (96×72) | 0.963 | 30/30 err 0 | **0.000** |
  | 0xB15DD14C (96×72) | 1.000 | 30/30 err 0 | **0.000** |
  | 0xB164344C (96×72) | 0.963 | 24/30 err 2 | **0.102** |
  | 0xB164690C (96×72) | 1.000 | 20/30 err 1 | **0.259** |
  | 0xCA9AA000 (240×240) | 1.000 | 89/225 err 1 | **0.602** |
  | 0x95AAD000 (2816×2112) | 1.000 | 88/46464 err 1 | 0.998 (디코드 시작은 성공) |

  육안 검증(지표): 복원 파일들의 채움 영역은 고주파 비반복 텍스처(masking형 반복·단색 아님).
- **판단:** 지지. **DHT 이식은 실효** — resync 없이도 96×72군 3건이 undec 0.000, 2건이 0.1~0.26. 도중 정지 파일(0xCA9AA000 89/225, 0x95AAD000 88/46464)은 추가 엔트로피 손상으로, resync 엔진을 얹으면 이어갈 후보. 그러나 얹어 보니 다른 문제가 드러났다(8단계).

### 8단계 — 이식 + recover가 성과를 무효화: DC/AC 계수 경계 미보정

- **가설 / 세운 이유:** 7단계에서 0xCA9AA000이 plain으로 89/225까지 감. 기존 `recover()`를 얹으면 89 이후를 재동기해 undec 0.602보다 개선될 것.
- **실험:** 이식 Decoder에 ① 기존 `recover()`, ② 4단계 스케일 임계 recover 실행. 결과가 이상해 ③ 경계 조합 분리(`decode_range`를 dc/ac/rate 경계 조합별로 호출).
- **예측:** ①·② 모두 undec < 0.602.
- **증거:**
  - ① 기존 recover: hole 1 · ops 0, **undec 0.996** — plain(0.602)보다 나쁨. ② 스케일 recover도 0.996.
  - ③ 경계 분리(이식 후, MCU 0부터): 전부 켬 → done 1, err 3 / rate만 끔 → done 1, err 3 / DC만 끔 → done 2, err 3 / AC만 끔 → done 1, err 3. 경계 전부 끄면 done 89. 즉 **DC·AC 계수 경계(err 3) 둘 다 MCU 0~2에서 발동** — 유효한 스트림을 디싱크로 오판.
  - 원인: 경계는 dequant 도메인이다 — DC `dc*qmat[comp,0] > DC_BOUND`(`carver/jpegdecode.py:234`), AC도 동일(`:259`). 상수 `DC_BOUND, AC_BOUND = 1400, 6000`(`carver/resync.py:23`)은 다수파 quant 스케일 기준인데, 이 파일의 DQT max는 Y 49 / Cb·Cr **94**로 커서 정상 계수의 dequant 값이 경계를 넘는다.
  - 오판 후 인과: frontier 0 → 제자리 재개는 masking 가드(`|db|<24` 제외)에 걸림 → 편집·재동기 모두 불가 → hole → 전량 회색. **이식 성과(89 MCU)를 recover가 무효화하는 구조.**
  - 영향 범위(RECOVERED, DQT max 대역별): ≤40 522건 평균 undec 0.092 / 41–60 17건 0.037 / 61–100 10건 0.101 / **>100 8건 0.195(undec>0.15 비율 25%)**. 소수지만 헤더 이식 pass의 전제 조건.
- **판단:** 세 번째 사각지대 — plausibility 경계가 quant 테이블에 비례하지 않는다. quant-비례 경계(또는 파일별 보정)가 필요하며, 이것 없이는 DHT 이식 pass도 recover 단계에서 무효화된다.

### 9단계 — 단편화 가설 1차 검사(0x95AAD000): 해당 지점은 단편 경계 아님

- **가설 / 세운 이유:** 7단계에서 0x95AAD000이 이식 후 88 MCU에서 err 1로 재정지. 대형 파일 "데이터 소진" 회색의 대안 가설로, carve의 연속 추출 가정이 깨진 **단편화**(파일 나머지가 디스크 다른 위치에 존재)라면 정지점이 클러스터/섹터 경계에 정렬될 것.
- **실험:** 정지 MCU의 엔트로피 바이트 → `raw_of_clean` 매핑으로 raw 파일 오프셋 → 파일명(디스크 오프셋 0x95AAD000) 기준 디스크 오프셋 → 정렬 검사.
- **예측:** 단편 경계라면 디스크 오프셋 % 512 == 0(FAT 단편은 최소 섹터 정렬).
- **증거:** 정지 MCU 88, clean_byte 4385, raw 오프셋 0xC6C7, 디스크 오프셋 **0x95AB96C7**, % 512 = 199 ≠ 0. scan_start 46489, 정지 시 DC 상태 [29, -367, 86].
- **판단:** 이 지점은 단편 경계가 아니다(섹터 비정렬 — 단편 절단은 섹터 경계에서만 발생하므로 확정 반증). 0x95AAD000의 재정지는 엔트로피 내 추가 손상으로 보이며 resync 엔진(+경계 보정)의 영역. **단편화 가설 일반은 미검증으로 남는다** — `usb.img`(3,517,120,512바이트)가 리포 루트에 있으므로, 데이터 소진형 파일(BYTE 100%·MCU<100%)의 frontier 상태(비트·DC)로 디스크 전 클러스터 후보를 `decode_probe`하는 전수 탐색(32KB 정렬 시 ~107K 후보)이 실행 가능한 후속 실험이다.

## 기각된 가설 / 막다른 길

- **"worst = 대형 중손상(데이터 한계)" → 기각(1단계).** worst 25는 소형 + ops 0. 교훈: **평균 지표가 개선됐을 때 "악화 방향" 질의를 루틴으로 함께 돌릴 것** — report.csv에 undec 열이 생긴 뒤로 worse-than-before(66건)를 아무도 질의하지 않아 한 달 가까이 보이지 않았다.
- **"SKIP = exotic 포맷(progressive 등)" → 기각(5단계).** progressive는 1건, 나머지 전부 헤더 손상. 교훈: **예외 메시지는 검사 지점을 말할 뿐 원인 분류가 아니다** — "~만 지원" 메시지를 원인 통계로 쓰지 말고 원인을 별도 분류할 것.
- **"maxW만 줄이면 소형 잠금이 풀린다" → 기각(3단계).** `max(250, maxW//2)`의 250 바닥 + probe 캡의 상호작용으로 오히려 수락 불가 확정. 교훈: **파생 임계 체계는 한 항만 스케일하면 다른 바닥 상수가 지배한다** — 캡·수락·부속 임계를 한 세트로 스케일해야 한다.
- **"다수파 DHT는 Annex-K 표준이 아니다" → 오판 후 정정(6단계).** 최초 지문 대조에서 불일치(050df0dc vs 332c3e17)로 "카메라 고유 테이블"이라 판단했으나, 원인은 `repr(np.int32(1))`('np.int32(1)') vs `repr(1)`('1')의 타입 repr 차이였다. int 정규화 후 값 대조로 **완전 일치** 확인. 교훈: **md5(repr(...)) 지문을 이질 소스 간 교차 비교할 때는 타입 정규화가 선행돼야 한다** — 동일 파서를 거친 코퍼스 내부 비교는 유효하지만, 손으로 만든 기준값과의 비교는 캐스팅 없이는 위양성 불일치를 낸다.
- **"0x95AAD000의 재정지 = 단편 경계" → 반증(9단계).** 정지점이 섹터 비정렬(% 512 = 199). 교훈: **단편화 후보 선별에는 % 512 정렬 검사가 싸고 확정적인 1차 필터다** — 비정렬이면 그 지점은 단편 경계가 아니라고 단정할 수 있다(정렬이면 후보일 뿐 확정은 아님).

## 사용한 방법·도구

일회성 스크립트는 세션 스크래치패드에서 실행해 **리포에 남아 있지 않다**. 재현에 필요한 핵심을 아래에 남긴다(모두 리포 루트에서 `python -X utf8`로 실행, 데이터는 `output/jpeg/`·`output/jpeg_recovered/report.csv`).

**① DHT 지문 집계** (6단계):

```python
import csv, hashlib, collections
from pathlib import Path
from carver import jpegdecode as jd

def dht_fp(h):
    return hashlib.md5(repr(sorted(
        [(k, (tuple(v[0]), tuple(v[1]))) for k, v in h.huff.items()]
    )).encode()).hexdigest()[:8]
# 빈 DHT의 지문: hashlib.md5(repr(sorted([])).encode()).hexdigest()[:8] == 'd7517139'
rows = list(csv.DictReader(open('output/jpeg_recovered/report.csv')))
cnt = collections.Counter(
    dht_fp(jd.parse_header((Path('output/jpeg')/r['filename']).read_bytes()))
    for r in rows)
# 기대값: {'332c3e17': 704, 'd7517139': 66, ...} — 다수파는 Annex-K 전형과 일치(int 캐스팅 후 값 대조)
```

**② DHT 이식 디코더 구성** (7·8단계). `Decoder.__init__`이 data를 재파싱하므로 `__new__`로 우회해 교체된 huff로 수동 구성한다:

```python
import numpy as np
from carver import jpegdecode as jd

def make_transplant_decoder(data: bytes, donor_huff) -> jd.Decoder:
    h = jd.parse_header(data)
    h.huff = donor_huff                      # DHT 이식
    dec = jd.Decoder.__new__(jd.Decoder)
    dec.data = data; dec.h = h; H = h
    dec.hl = np.zeros((4, 1 << 16), np.uint8); dec.hs = np.zeros((4, 1 << 16), np.int32)
    for (cls, tid), (counts, syms) in H.huff.items():
        l, s = jd.build_huff_lut(counts, syms)
        dec.hl[cls*2+tid] = l; dec.hs[cls*2+tid] = s
    dec.hmax = max(c[1] for c in H.comps); dec.vmax = max(c[2] for c in H.comps)
    dec.hsamp = np.array([c[1] for c in H.comps], np.int64)
    dec.vsamp = np.array([c[2] for c in H.comps], np.int64)
    scan_map = {cs: (td, ta) for cs, td, ta in H.scan}
    dec.dc_idx = np.zeros(3, np.int64); dec.ac_idx = np.zeros(3, np.int64)
    dec.qmat = np.zeros((3, 64), np.int64)
    for ci, (cid, _a, _b, qid) in enumerate(H.comps):
        td, ta = scan_map[cid]
        dec.dc_idx[ci] = td; dec.ac_idx[ci] = 2 + ta
        qn = np.zeros(64, np.int64)
        for k in range(64): qn[jd.ZIGZAG[k]] = H.qt[qid][k]
        dec.qmat[ci] = qn
    dec.mcus_x = (H.width + 8*dec.hmax - 1) // (8*dec.hmax)
    dec.mcus_y = (H.height + 8*dec.vmax - 1) // (8*dec.vmax)
    dec.cy = np.zeros((dec.mcus_y*dec.vsamp[0], dec.mcus_x*dec.hsamp[0], 8, 8))
    dec.cb = np.zeros((dec.mcus_y*dec.vsamp[1], dec.mcus_x*dec.hsamp[1], 8, 8))
    dec.cr = np.zeros((dec.mcus_y*dec.vsamp[2], dec.mcus_x*dec.hsamp[2], 8, 8))
    buf, roc = jd.destuff(data, H.scan_start)
    dec.buf = buf; dec.nbits = buf.size * 8; dec.raw_of_clean = roc
    return dec

# 기증자: donor_huff = jd.parse_header(open('output/jpeg/0xC93D0000.jpg','rb').read()).huff
# 검증: dec.decode_full() → (done, end_bit, err); rs.undecoded_fraction(dec.to_rgb())
```

**③ 스케일 임계 recover** (4단계) — 본체 `recover`/`_resync_skip`를 복제하고 다음만 변경:

```
probe 캡:      maxW → W = int(min(900, 총MCU - m_d))
resync 수락:   max(250, maxW//2) → max(30, int(W * 0.55))
편집 수락:     run > 120 → run > min(120, max(20, int(잔여 * 0.4)))
편집 개선폭:   base + 30 → base + min(30, 잔여 // 4)
(masking 가드 |db|≥24, 나머지 로직 동일)
```

**④ 경계 분리** (8단계): `jd.decode_range(..., dcb, acb, rt)`를 `(DC_BOUND|DISABLE, AC_BOUND|DISABLE, rate|DISABLE)` 조합으로 호출해 done/err 대조. err 의미는 `carver/jpegdecode.py:199` — 0=완료, 1=무효코드, 2=버퍼끝, 3=계수오버플로, 4=비트레이트.

**⑤ 단편 경계 검사** (9단계): 정지 MCU의 `mcu_bit[done]//8` → `raw_of_clean[clean_byte]` → `int(파일명, 16) + raw_off` → `% 512`.

## 결론

확정 사실 (전부 이 세션에서 실측·재현 가능, **코드 변경 없음**):

1. **SKIP_UNDECODABLE 122건은 전부 헤더 손상이다.** SOF 소실 42 / SOF 필드 깨짐 60 / SOS 소실 8 / 기타 필드 손상 12. 진짜 비-baseline은 1건. 그중 **66건은 DHT 완전 소실**(지문 d7517139 = 빈 dict; SKIP 64 + RECOVERED 2)이며, 다수파 테이블(704/822, **ITU T.81 Annex-K 전형과 일치** — [레퍼런스](../reference/jpeg-entropy-coding.md)) 이식만으로 plain 디코드가 96×72군 3건 undec 0.000, 총 7건 중 5건 undec ≤0.26으로 복원된다. 헤더 복구는 현행 엔진이 다루지 않는 **미개척 축**이다.
2. **RECOVERED 557 중 196건(실제 MCU<450)은 resync 수락이 산술적으로 불가능**하고(42건은 편집 수락도 불가), 이로 인해 undec 악화 66건(평균 +0.354)·무행동 70건이 발생한다. 잔여 MCU 비례 임계로 5건 중 4건 복구를 실증했다(0xC91AF000 0.961→0.004 등). 본 적용에는 masking 가드·회귀 가드·육안 표본이 전제다.
3. **DC/AC 계수 경계(1400/6000, dequant 도메인)는 quant 테이블에 비례하지 않아** DQT가 큰 파일(Cb/Cr max 94 등)에서 정상 스트림을 MCU 0~2에서 디싱크로 오판한다(err 3). 이 오판은 DHT 이식 성과도 recover 단계에서 무효화한다(0xCA9AA000: plain 89/225 vs recover 1). 헤더 이식 pass의 전제 조건.
4. **버그 2건:** ① `Decoder`가 빈 huff를 검증하지 않아 DHT 소실 파일이 SKIP이 아닌 RECOVERED(전량 회색)로 분류된다(`carver/jpegdecode.py:380-385`). ② 무행동(ops 0·hole 1) 파일이 RECOVERED로 분류되어 입력보다 회색이 많은 재인코딩본이 저장된다 — 별도 action(예: FAILED)이 필요하다.
5. **기존 "잔존 회색 = 데이터 한계" 결론([skew 조사](2026-07-01-resync-skew-underconsumption.md))은 대형·데이터 소진 계열에 한해 유효**하다 — undec_after>0.15 93건 중 임계 잠금 46건과 DHT 소실 2건(1건은 잠금과 중복, 합집합 47건)을 제외한 46건. 이 46건에도 단일 지문 DHT 이탈 파일이 일부 섞여 있을 수 있다. hole 1·ops 0 전부에 일반화한 것은 과대적용이었다.
6. **단편화 가설은 미검증으로 열려 있다.** 0x95AAD000의 재정지점은 단편 경계가 아님을 확인(섹터 비정렬). `usb.img`가 있으므로 frontier 상태 기반 전 클러스터 probe 탐색이 실행 가능한 후속 실험.

후속 작업 항목(우선순위 제안)은 [백로그](../backlog.md)에 등록: ① 헤더 복구 pass(빈 huff 검증 → DHT 이식 → SOS/SOF 재구성), ② 계수 경계 quant-비례 보정, ③ 수락 임계 잔여 MCU 비례화, ④ report 악화 플래그·FAILED 분류, ⑤ 단편화 probe 탐색.
