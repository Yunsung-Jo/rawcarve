# 조사 기록 — resync DC=0 리셋으로 hole 잔존 회색 복구

- **날짜:** 2026-07-01
- **한 줄:** resync가 hole에서 멈춰 남긴 회색을, resync-skip의 DC 예측 캐리(resync.py:127)를 DC 리셋 후보로 확장해 복구. 전체 DC 리셋(zero)이 회색 최대 감소(0xB70AC000 gray 0.571→0.077 등), 단 무조건 적용은 잘 되던 케이스(0xA24B2000 0.107→0.184) 회귀 → 조건부 적용 필요.
- **결론 문서:** [ADR 0004 DC=0 리셋 복구](../adr/0004-resync-dc-reset-recovery.md). 잔존 회색 원인은 [skew·회색 원인 조사](2026-07-01-resync-skew-underconsumption.md). 선행 [resync-limit 조사](2026-06-29-resync-limit.md)의 DC 캐리 한계를 이 조사가 해결.

> **랩 노트(스냅샷).** experiment-loop `feat/resync-dc-reset` 브랜치의 DC 리셋 실험 5사이클 + optdc 막다른 길 기록. [resync-limit 조사](2026-06-29-resync-limit.md)가 남긴 두 한계(DC 캐리·비트 과소비) 중 DC 리셋을 이어받는다.

---

## 증상

resync 엔진이 hole(재동기 실패)에서 멈춰 하단이 회색으로 남는 파일들. `output/jpeg_recovered/report.csv` 기준 회색 잔존 대표 5개:

| 샘플 | gray_before | gray_after | resync | hole | 크기 |
|------|-----|-----|-----|-----|-----|
| 0xB70AC000 | 0.995 | 0.571 | 9 | 1 | 2816×2112 |
| 0xA1F57000 | 0.994 | 0.461 | 8 | 1 | 2816×2112 |
| 0xBA5F6000 | 0.941 | 0.366 | 18 | 1 | 2816×2112 |
| 0xBD866000 | 0.963 | 0.254 | 10 | 1 | 2816×2112 |
| 0xA24B2000 | 0.989 | 0.107 | 20 | 1 | 2816×2112 |

모두 `hole 1`로 끝난다(재동기 못 하고 정지). resync-limit이 0xA1F57000에서 밝힌 원인: hole 지점에서 `_resync_skip`이 DC 예측을 직전값으로 캐리만 해서(resync.py:127) 재개 실패. currentDC best=137(수락 임계 미달) vs zeroDC best=900.

- 재현: `output/jpeg/<샘플>.jpg`를 `recover(dec, time_budget=0)`. 하니스 `scratchpad/harness.py`.

## 조사 과정 (가설 → 예측 → 증거)

### 1단계 — DC 리셋 후보 추가: 전체 리셋(zero)이 회색 최대 감소, 무조건 적용은 회귀

- **가설 / 세운 이유:** resync-limit이 hole 잔존의 원인으로 "resync-skip의 DC 캐리"를 지목하고, DC=0 리셋 시 재개 clean run이 137→900으로 늘어남을 확인했다. 따라서 `_resync_skip`의 재개 탐색에 DC 리셋 후보를 추가하면 hole이 재동기되어 gray_after가 감소할 것이다. 리셋 범위를 셋으로 나눠 비교: 전체 DC=0(zero) vs Y만 0·Cb/Cr 캐리(ymono) vs 캐리만(baseline).
- **실험:** `_resync_skip`을 monkeypatch로 교체(본체 미수정). 각 재개 후보 비트위치에서 DC 후보(캐리 + 리셋변형)를 모두 probe해 clean run 최대인 쪽 채택. masking(제자리 DC 리셋 가짜복구) 차단 위해 `|db|>=24` 위치만 유효. 3전략 × 8샘플(실패 5 + 회귀가드 3), `recover(time_budget=0)`. 지표: gray_after, resync/hole 수. 몽타주 `scratchpad/exp1_montage.png`.
  - 회귀 가드: report.csv에서 resync≥11로 재동기가 많이 일어난(변경에 민감할) RECOVERED 3개 — 0x9906A000(0.996→0.002 resync15), 0xA44AE000(0.995→0.000 resync11), 0x98AB4000(0.900→0.001 resync11).
- **예측:** (실험 전 기록, `scratchpad/exp1_prediction.md`)
  - zero: 실패 5개 gray_after 감소. 0xA1F57000 0.461→~0.27(resync-limit 재현). 나머지 4개(0xB70AC000 0xBA5F6000 0xBD866000 0xA24B2000)도 감소.
  - ymono: 재동기 길이는 zero와 비슷(Y DC가 재동기 결정) → gray 비슷. 색 캐스트는 zero보다 덜함.
  - 회귀가드 3개: gray_after 거의 불변(±0.01), 악화 없음.
- **증거:** (gray_after, 괄호는 resync 수. baseline은 report.csv와 정확히 재현 → 하니스 신뢰 확인)

  | 샘플 | baseline | zero | ymono |
  |------|-----|-----|-----|
  | 0xB70AC000 | 0.571 (9) | **0.077** (25) | 0.229 (20) |
  | 0xA1F57000 | 0.461 (8) | **0.052** (15) | 0.157 (16) |
  | 0xBA5F6000 | 0.366 (18) | **0.059** (24) | 0.088 (27) |
  | 0xBD866000 | 0.254 (10) | 0.057 (17) | **0.051** (17) |
  | 0xA24B2000 | **0.107** (20) | 0.184 (19) | 0.164 (17) |
  | 0x9906A000 G | 0.002 (15) | 0.013 (16) | 0.002 (13) |
  | 0xA44AE000 G | 0.000 (11) | 0.003 (10) | 0.000 (11) |
  | 0x98AB4000 G | 0.001 (11) | 0.005 (10) | 0.001 (10) |

  - zero: 실패 4/5에서 대폭 감소. 0xA1F57000 0.461→0.052(예측 0.27보다 좋음 — full 스캔 + 각 위치 DC후보 덕분). 예측 지지.
  - ymono: zero보다 재동기 약함(0xB70AC000 zero 0.077 vs ymono 0.229; 0xA1F57000 0.052 vs 0.157). **예측 빗나감** — Y만 리셋으론 부족.
  - 0xA24B2000: zero/ymono 둘 다 악화(0.107→0.184/0.164). **예측 빗나감** — 유일 실패 케이스가 악화.
  - 회귀가드: zero는 미미 악화(0.002→0.013, 0.000→0.003, 0.001→0.005), ymono는 불변(0.002/0.000/0.001).
  - 육안(결함 패턴): 실패 4/5는 zero에서 하단 회색이 재동기 세그먼트(가로 밀림 밴드)로 채워짐. baseline도 녹색 캐스트·밀림 존재 → zero가 색을 추가로 틀지 않음. 0xA24B2000은 zero에서 하단에 녹색/무채색 밴드 증가.
- **판단:** 가설 지지(DC 리셋으로 회색 대폭 감소). 세부 결론 3개:
  1. **전체 리셋(zero)이 재동기 최강** — Cb/Cr DC도 재동기(clean run)에 기여한다. ymono(Cb/Cr 캐리)가 zero보다 약한 게 근거: 캐리된 Cb/Cr DC가 틀려 계수 오버플로(DC_BOUND=1400)에 걸려 clean run이 짧아진다.
  2. **무조건 리셋은 회귀** — baseline이 이미 재동기 성공하는 지점(0xA24B2000·가드)까지 DC 리셋이 개입해 다른(나쁜) 경로를 택한다. → 다음 사이클: baseline 캐리 재동기가 실패할 때만 DC 리셋 후보를 쓰는 **조건부 적용**.
  3. **무채색 착시 가능성** — zero는 Cb/Cr=0(무채색)이라 `gray_fraction`(무채색+평탄을 회색으로 카운트)이 회색을 과다 집계할 수 있다(가드 미미 악화·0xA24B2000 악화의 일부일 수 있음). 색 보정(Cb/Cr 인접 추정) 시 gray가 더 내려갈 가능성 — 사용자 관심사(색보정이 복구율에 영향?)와 연결. 다음 사이클에서 분리 측정.

### 2단계 — 조건부(캐리 우선) DC 리셋 기각: 회귀 0이나 개선도 0

- **가설 / 세운 이유:** 1단계에서 zero(무조건 DC 리셋)가 회귀를 냈다(0xA24B2000 0.107→0.184, 가드 0.002→0.013). 원인이 "baseline 캐리로 이미 재동기되던 지점까지 리셋이 개입"이라면, 캐리로 먼저 재동기를 시도하고 수락 임계(run>=max(250,maxW/2)=450) 미달일 때만 zero 후보를 추가하는 조건부로 회귀를 막으며 개선을 유지할 수 있다.
- **실험:** `_resync_skip`을 조건부로 monkeypatch — hole 지점에서 (1) 캐리만 스캔, 수락되면 채택, (2) 미달이면 [캐리, zero] 재스캔. 8샘플, recover(time_budget=0). baseline/zero는 exp1 재사용. `scratchpad/harness2.py`.
- **예측:** (실험 전, `scratchpad/exp2_prediction.md`) 실패 4개(0xB70AC000 0xA1F57000 0xBA5F6000 0xBD866000)는 zero 수준(~0.077/0.052/0.059/0.057)으로 회색↓. 가드 3개는 baseline 완전 보존.
- **증거:**

  | 샘플 | baseline | zero | conditional |
  |------|-----|-----|-----|
  | 0xB70AC000 | 0.571 | 0.077 | 0.571 |
  | 0xA1F57000 | 0.461 | 0.052 | 0.274 |
  | 0xBA5F6000 | 0.366 | 0.059 | 0.366 |
  | 0xBD866000 | 0.254 | 0.057 | 0.254 |
  | 0xA24B2000 | 0.107 | 0.184 | 0.107 |
  | 0x9906A000 G | 0.002 | 0.013 | 0.002 |
  | 0xA44AE000 G | 0.000 | 0.003 | 0.000 |
  | 0x98AB4000 G | 0.001 | 0.005 | 0.001 |

  - 회귀 차단은 완벽: 0xA24B2000·가드 모두 baseline과 동일. **예측 지지.**
  - 그러나 실패 케이스 개선 상실: 0xB70AC000·0xBA5F6000·0xBD866000은 baseline과 완전 동일(gray·resync·hole), 0xA1F57000만 0.274(zero 0.052에 크게 못 미침). **예측 빗나감.**
- **판단:** 기각. 회귀는 막았으나 개선도 사라졌다(회귀 0 + 개선 0). recover가 좌→우로 hole을 처리하므로, 앞쪽 hole에서 캐리로 얕게 재동기하면 그 경로를 따라가다 다른 hole에 부딪히고 거기서 zero가 안 통한다(0xB70AC000 conditional resync 9=baseline vs zero 25). zero는 처음부터 공격적 경로로 깊게 재동기한다. → 다음: 회귀를 경로 선택이 아니라 **무채색 착시** 축에서 규명(3단계).

### 3단계 — zero의 gray 회귀는 무채색 착시: 진짜 복구율(undecoded)은 zero가 항상 우수

- **가설 / 세운 이유:** 2단계에서 conditional은 회귀를 막았으나 개선도 잃었다(캐리 우선이 zero 경로 차단). 그러면 zero를 그대로 쓰되 회귀만 규명하면 된다. zero의 회귀(가드 0.002→0.013, 0xA24B2000 0.107→0.184)가 진짜 미복구 증가인지, `gray_fraction`이 Cb/Cr=0 무채색 콘텐츠(Y는 정상 재동기)를 회색으로 오집계한 착시인지 갈라야 한다.
- **실험:** exp1 baseline/zero 복구본에서 두 지표 대조 — `gray_fraction`(achroma&flat)과 `undecoded_128`(|R−128|<6 & |G−128|<6 & |B−128|<6 & flat = 디코더가 안 채운 회색128 미복구만). `gray − undecoded` = 무채색 콘텐츠(착시분). `scratchpad/exp3_undecoded.py`.
- **예측:** (실험 전, `scratchpad/exp3_prediction.md`) 모든 샘플에서 zero undec ≤ baseline undec. 0xA24B2000 zero undec < 0.107. 가드 zero undec ≈ 0.
- **증거:** (gray / undec)

  | 샘플 | baseline gray/undec | zero gray/undec |
  |------|-----|-----|
  | 0xB70AC000 | 0.570 / 0.570 | 0.074 / **0.058** |
  | 0xA1F57000 | 0.461 / 0.444 | 0.050 / **0.015** |
  | 0xBA5F6000 | 0.365 / 0.365 | 0.056 / **0.040** |
  | 0xBD866000 | 0.253 / 0.250 | 0.054 / **0.041** |
  | 0xA24B2000 | 0.106 / 0.102 | 0.179 / **0.087** |
  | 0x9906A000 G | 0.002 / 0.000 | 0.011 / **0.000** |
  | 0xA44AE000 G | 0.000 / 0.000 | 0.002 / **0.000** |
  | 0x98AB4000 G | 0.001 / 0.000 | 0.005 / **0.000** |

  - **모든 샘플에서 zero undec ≤ baseline undec.** 예측 완전 지지.
  - 0xA24B2000: baseline undec 0.102 → zero 0.087(미복구 감소). gray 0.106→0.179 증가는 chroma 0.092(무채색 착시).
  - 가드 3개: zero undec 0.000 = baseline(미복구 완벽 유지). gray 증가(0.011/0.002/0.005)는 전부 착시.
  - 실패 4개: zero undec 0.058/0.015/0.040/0.041 ≪ baseline 0.570/0.444/0.365/0.250.
- **판단:** 가설 지지. **zero의 gray_fraction 회귀는 전부 무채색 착시이며, 진짜 복구율(undecoded_128)로는 zero가 모든 샘플에서 baseline 이상이다.** → 재동기는 zero(전체 DC 리셋)로 확정. 색 보정은 진짜 복구율과 무관하며(zero가 이미 미복구 최소화) `gray_fraction` 착시·육안 색 품질만 개선한다.

### 4단계 — 본체 이식 + 샘플 재검증: 스크래치와 완전 일치

- **이식:** `_resync_skip`(resync.py)에 DC 후보 `cands=(dc 캐리, np.zeros(3) 전체 리셋)`를 추가. 각 스캔 위치·비트정밀 보정에서 두 후보를 probe해 clean run 긴 쪽 채택, 채택한 dc를 함께 반환(best[2]). masking 차단은 `|db|>=24`로 스캔 단계에서 — 캐리는 제자리 run이 짧아 무해했으나 zero는 제자리 리셋이 run을 늘려 masking 위험이 있어 스캔에서 제외한다.
- **재검증:** 이식한 본체 `recover`를 monkeypatch 없이 직접 호출해 8샘플 재복구, exp1 zero(exp1_results.csv) 대조.
- **예측:** 8샘플 모두 본체 gray_after = exp1 zero(±0.005).
- **증거:** 8/8 완전 일치.

  | 샘플 | 본체 gray | exp1 zero | resync |
  |------|-----|-----|-----|
  | 0xB70AC000 | 0.077 | 0.077 | 25 |
  | 0xA1F57000 | 0.052 | 0.052 | 15 |
  | 0xBA5F6000 | 0.059 | 0.059 | 24 |
  | 0xBD866000 | 0.057 | 0.057 | 17 |
  | 0xA24B2000 | 0.184 | 0.184 | 19 |
  | 0x9906A000 G | 0.013 | 0.013 | 16 |
  | 0xA44AE000 G | 0.003 | 0.003 | 10 |
  | 0x98AB4000 G | 0.005 | 0.005 | 11 |

- **판단:** 이식 정확(스크래치 = 본체). 지표 보완으로 `undecoded_fraction`을 resync.py에 추가하고 recover_file·report.csv에 `undec_before`/`undec_after`를 병기(무채색 착시 없는 진짜 복구율). 전수 적용 진행(전수 결과는 5단계).

### 5단계 — 전수 적용: 진짜 복구율 대폭 개선, 진짜 회귀 3건(미미)

- **실험:** 이식 본체로 `output/jpeg` 822개를 `recover.py -o output/jpeg_recovered_v2 --time-budget 0` 전수(17분 18초). baseline `output/jpeg_recovered`와 대조. `scratchpad/verify_regression.py`.
- **예측:** (실험 전) 대부분 undec 감소, gray 악화는 대부분 무채색 착시. 회귀 가드 유형(잘 복구되던 파일)은 undec 불변.
- **증거:**
  - **action 분포 baseline과 완전 동일**: CLEAN 143 / RECOVERED 557 / SKIP_UNDECODABLE 122. 분류(구조) 안정.
  - 공통 복구 700개(RECOVERED+CLEAN). baseline gray 0.1253, v2 gray 0.1242(무채색 착시로 거의 불변), v2 undec 0.0737. 복구본 557만 재계산: **baseline undec 0.100 → v2 undec 0.092**(진짜 복구율 개선; baseline recovered gray 0.156과 대비 — gray는 무채색 착시로 부풀려진다).
  - gray 악화(v2>base+0.005) 103개 중 >0.03 큰 악화 31개를 baseline 복구본 undec 재계산으로 판별 → **진짜 회귀(undec 증가) 3개, 나머지 28개는 무채색 착시**(undec 불변/감소). 예: 0xA24B2000 gray 0.107→0.184지만 undec 0.103→0.088(감소).
  - **진짜 회귀 3건**: 0xD13BF000(undec 0.190→0.205), 0xCDB0D000(0.055→0.081), 0xCEF8D000(0.167→0.178). 모두 원래 undec 높은(손상 심한) 파일, 증가폭 0.011~0.026.
- **판단:** zero 이식이 전수에서 진짜 복구율(undec)을 개선. 복구본 557 undec 평균 baseline 0.100→0.092 — 전체 평균 개선은 작으나 **회색 잔존 케이스에서 대폭**(0xB70AC000 0.570→0.058). gray_after 악화 103개 중 100개는 무채색 착시임을 확인 — `undecoded_fraction` 병기가 착시를 정확히 걸러낸다. 진짜 회귀는 3/700(0.4%), 손상 심한 파일에서 zero의 전역 공격적 경로가 국소적으로 baseline 캐리보다 불리한 사례(undec 소폭 증가). 완벽 복구 불가 영역의 트레이드오프.

## 기각된 가설 / 막다른 길

- **조건부(캐리 우선) DC 리셋 → 기각.** 캐리로 먼저 재동기하고 실패 시에만 zero를 쓰면 회귀는 0이나 개선도 0이다(실패 케이스 3/5가 baseline 그대로, 0xA1F57000만 부분). 교훈: **좌→우 순차 재동기에서 앞의 얕은 선택이 뒤의 깊은 재동기 경로를 막는다 — 지역 우선순위(조건부)로는 전역 최적 재동기를 얻지 못한다. 재동기 전략은 전역적으로 일관돼야 한다.**
- **ymono(Y만 DC=0, Cb/Cr 캐리)로 색 보존하며 재동기 → 부분 기각.** ymono는 zero보다 재동기가 약하다(0xB70AC000 0.229 vs 0.077). 교훈: **재동기(clean run)는 Y DC뿐 아니라 Cb/Cr DC도 정확해야 길어진다** — 색 보존을 위해 Cb/Cr을 캐리하면 틀린 예측값이 계수 경계에 걸려 재동기를 희생한다. 색은 재동기와 분리해 재동기 후 보정으로 다뤄야 한다.
- **Σdiff 중앙 최적 Y DC(optdc)로 재동기 거리 확대 → 5샘플 성공, 전수 기각.** DC 값은 계수 오버플로 경계(±DC_BOUND)를 통해서만 clean run에 영향을 준다(Huffman·비트레이트는 DC 무관). 절대 DC = 시작DC + Σdiff이고 Σdiff 궤적은 비트열이 고정하므로, 궤적을 오버플로 창 중앙에 놓는 시작 DC(-(ymin+ymax)/2, `decode_dc_span`으로 산출)가 clean run을 최대화한다. DC 스캔으로 실증(한 재동기 지점에서 DC=0 run 36 → Y DC −1300 run 1189). 5샘플에서 undec 감소(0xA1F57000 0.015→**0.000 완전 복구**)했고, 픽셀(손실 0%·새복구=회색감소분)·frontier(88.2→89.7% 등)·skew(1.13→1.12, 유지·개선)의 3중 검증으로 **garbage가 아닌 진짜 데이터 추가 디코드**임을 확인했다. 그러나 전수(822개): undec 평균 **0.0922→0.0915(Δ −0.0007, 무의미)**, 악화 13개, 복구 시간 **17분→48분(2.8배, 최대 819s/파일)**. 교훈: **5샘플 성공이 전수 대표성을 보장하지 않는다.** 이론은 옳으나 (1) 심손상 파일에서 opt 계산(오버플로 지점마다 `decode_dc_span`)이 폭발하고 (2) 전역 이득은 5샘플 과적합이라 비용 대비 이득이 없어 폐기했다. 재시도하려면 opt 계산을 best 위치 근처로 국한하고 악화 13건의 원인부터 규명해야 한다.

## 사용한 방법·도구

- `scratchpad/harness.py` — `carver.resync._resync_skip`을 monkeypatch로 교체해 recover 재사용. DC 후보(캐리/zero/ymono)별 8샘플 복구, gray_after·resync·hole 기록, 몽타주 생성.
- `scratchpad/exp1_prediction.md` — 실험 전 예측 고정.
- `scratchpad/exp1_results.csv` — 측정 원장.
- `scratchpad/exp1_montage.png` — 행=샘플, 열=전략 육안 비교.

## 결론

- `_resync_skip`에 DC 후보 `(직전값 캐리, 전체 0 리셋)`를 추가해 각 재개 위치에서 clean run이 긴 쪽을 채택하도록 이식했다(masking 차단 `|db|≥24`, 채택 DC를 세그먼트와 함께 반환). Cb/Cr DC도 재동기에 기여하므로 Y만이 아닌 전체를 0으로 리셋한다.
- **전수 822개(`--time-budget 0`): 복구본 557 진짜 복구율 undec 평균 0.100→0.092(회색 잔존 케이스는 대폭, 예 0xB70AC000 0.570→0.058).** gray_after는 무채색 착시로 거의 불변(0.156). action 분포 불변(CLEAN 143 / RECOVERED 557 / SKIP 122). `gray_after` 악화 103개 중 100개는 무채색 착시(undec 불변·감소)였고, 진짜 회귀는 3개(0.4%, undec +0.01~0.03, 손상 심한 파일).
- `gray_fraction`이 DC=0의 무채색 콘텐츠를 회색으로 오집계하므로 `undecoded_fraction`을 추가해 `report.csv`에 병기했다. 이 지표로 "회귀가 착시"임을 확인했다.
- **트레이드오프:** DC=0 리셋은 Cb/Cr 절대 오프셋을 잃어 무채색 색 캐스트를 만든다. 진짜 복구율엔 무관하며 색 보정(인접 세그먼트 DC 추정)은 별도 과제(backlog).
- **기각된 방향:** 조건부(캐리 우선)는 회귀는 막으나 개선 상실(좌→우 순차에서 앞 얕은 선택이 뒤 깊은 재동기 차단). skew 채점은 오히려 악화 — 비트 과소비는 데이터 특성이라 재동기로 못 고친다([skew 조사](2026-07-01-resync-skew-underconsumption.md)).
- 결정: [ADR 0004](../adr/0004-resync-dc-reset-recovery.md).
