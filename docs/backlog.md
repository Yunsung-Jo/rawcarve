# 백로그

작업 중 발견한 **off-target 문제·버그** — 현재 목표와는 다르지만 나중에 손댈 가치가 있는 항목을 모은다.
즉흥적으로 쫓지 않고 여기 적어 두며, 현재 브랜치의 조사 기록은 한 가지 목표만 다루도록 유지한다.

- 항목을 새 브랜치로 다루기 시작하면, 그 설명이 [experiment-loop](../.claude/skills/experiment-loop/SKILL.md) 1단계(문제 정리)의 출발점이 된다.
- **포맷 사실**은 여기가 아니라 `reference/`에, **현재 목표 자체를 다시 잡게 만드는 발견**은 현재 조사 기록에 적는다.

## 항목

| 발견일 | 항목 | 맥락 / 처음 본 곳 |
|--------|------|------------------|
| 2026-07-01 | 재동기 세그먼트 내 저주파(blocky) MCU 화질 | **2026-07-02 조사됨**: 비중 0.3~0.5%(세그 농축 최대 3.1%, 세그 머리 2~6%), 대상 구간은 27.9bits/MCU 저엔트로피로 clean run의 정렬 판별력이 0(±1024비트 전 정렬 포화) — 현행 신호로 복구 불가, 콘텐츠 기반 채점 필요. 육안 지배 결함은 blocky가 아니라 밀림·색 캐스트로 판명 → 밀림 보정에 부수해 재평가. 독립 우선순위 낮음. [blocky 조사](investigations/2026-07-02-blocky-shift-dc-offset.md) 1~2단계. |
| 2026-07-01 | 재동기 세그먼트 Cb/Cr 색 캐스트 보정 | zero DC 리셋은 세그먼트 Cb/Cr 절대 오프셋을 잃어 색 캐스트를 만든다(진짜 복구율 무관 — [조사](investigations/2026-07-01-resync-dc-reset.md) 3단계). **2026-07-02 방법 단순화**: DC 차분의 선형성 덕에 재디코드 없이 **디코드 후 (세그먼트×컴포넌트)별 상수 오프셋 덧셈**으로 보정 가능 — 오프셋 추정만 남음(경계 행 연속성, 밀림 보정과 결합). 주의: 위-행 렌더 DC를 재동기 후보로 쓰는 원안은 실패(순환 오염, 24세그 중 18개 run ≤ 67). [blocky 조사](investigations/2026-07-02-blocky-shift-dc-offset.md) 5·7단계. |
| 2026-07-02 | 재동기 세그먼트 밀림(shift) 보정 | `_resync_skip`이 재개 비트를 frontier MCU에 배정하나 hole의 실제 MCU 수(k)를 모름 → 세그먼트마다 수평 오프셋 누적(육안 지배 결함, resync 2029세그/286파일 = RECOVERED 51%). 보정 신호: 세그 경계 행 상관(상대 k) + EOI 앵커(절대 — 단 데이터 소진 파일은 부재, 0xBA5F6000 소비 100.0%). 상대 보정만으로도 내부 정합 가능(전역 1자유도 잔존). 색 캐스트 오프셋 추정과 결합. [blocky 조사](investigations/2026-07-02-blocky-shift-dc-offset.md) 6단계. |
| 2026-07-02 | DC 물리 범위(±1016+q0/2) 채점 | 유효 JPEG의 dequant DC는 8×(평균−128) ∈ [−1024,+1016]. 이 불변량으로 (a) 재동기 후보 채점 강화 — masking 없이 수락 임계 인하 가능(clean run은 저엔트로피 구간·DC 품질을 판별 못 함), (b) 온전성 판별(plain e0는 증거 아님 — 40건 전원 드리프트), (c) 불완전 바이트 편집 잔존 오차 검출(정정렬 세그에서 max\|DC\| 1364>1016 관측). 미실험 제안. [blocky 조사](investigations/2026-07-02-blocky-shift-dc-offset.md) 4·6단계. |
| 2026-07-02 | 헤더 복구 pass (빈 huff 검증 → DHT 이식 → SOS/SOF 재구성) | SKIP 122건 전부 헤더 손상, 그중 DHT 완전 소실 66건. 다수파 DHT(=Annex-K 전형, 704/822 공유) 이식만으로 plain 디코드 복원 실증(96×72군 3건 undec 0.99→0.00 등). 단계화: ① `Decoder` 빈 huff 검증(분류 버그 즉수정), ② DHT 이식+resync, ③ SOS 재구성(8건), ④ SOF 재구성(~102건: 해상도 후보=코퍼스 분포, 우측 경계 연속성 채점). [발견 조사](investigations/2026-07-02-recovery-tool-blindspots.md) 5~7단계. |
| 2026-07-02 | ~~계수 경계 quant-비례 보정~~ → 경계는 정탐, 잔여 이슈만 | **2026-07-02 재검으로 수정**: plain e0 완주 40건 전원이 물리 초과 DC 드리프트 보유 — 경계 err3은 오탐이 아니라 정탐([blocky 조사](investigations/2026-07-02-blocky-shift-dc-offset.md) 4단계, [선행 조사](investigations/2026-07-02-recovery-tool-blindspots.md) 8단계의 결론 수정). 잔여 이슈 2건만 유효: (a) AC 경계 마진(정상 극단값 6052 vs 경계 6000, 1계수 관측 — 미미), (b) DHT 이식 도너의 DQT 가족 매칭(0xCA9AA000·0x95AAD000 [49,94,94] 계열은 Annex-K가 아닌 자체 DHT일 가능성 — 헤더 복구 pass에서 가족별 도너 선택). |
| 2026-07-02 | resync/edit 수락 임계 잔여 MCU 비례화 | 총 MCU<450이면 resync 수락(`max(250, maxW//2)`=450) 산술 불가 — RECOVERED 557 중 196건 잠금, undec 악화 66건(평균 +0.354)의 주원인. 비례 임계(probe 캡 W=min(900,잔여), 수락 max(30,0.55W))로 5건 중 4건 복구 실증(0xC91AF000 0.961→0.004). masking 가드·파일별 회귀 가드·육안 표본 전제. maxW만 줄이면 250 바닥이 지배해 실패(기각 기록 참조). [발견 조사](investigations/2026-07-02-recovery-tool-blindspots.md) 2~4단계. **2026-07-02 보강**: 잠금의 일반형은 총 MCU가 아니라 **연속 손상 간격 < 450**(0xC9CD0000: 정지 7, 잔여 631인데 ops 0) — 중형 파일까지 적용 범위 확대, 안전장치로 DC 물리 범위 채점 병행 권장([blocky 조사](investigations/2026-07-02-blocky-shift-dc-offset.md) 4단계). |
| 2026-07-02 | report 악화 플래그·무행동 FAILED 분류 | ops 0·hole 1(무행동) 70건이 RECOVERED로 분류되어 입력보다 회색 많은 재인코딩본 저장. `undec_after > undec_before` 악화 66건을 아무도 질의하지 않았음. 별도 action(FAILED)과 악화 플래그, 크기별 층화 통계 추가. [발견 조사](investigations/2026-07-02-recovery-tool-blindspots.md) 1단계·결론 4. |
| 2026-07-02 | 단편화 probe 탐색 (데이터 소진 회색의 대안 가설) | 데이터 소진형(BYTE 100%·MCU<100%) 파일의 frontier 상태(비트·DC)로 usb.img 전 클러스터 후보(~107K, 32KB 정렬)를 `decode_probe`해 이어지는 단편을 찾는 탐색. 0x95AAD000 재정지점은 섹터 비정렬로 단편 경계 아님 확인(가설 자체는 미검증으로 열림). 성공 시 "데이터 한계" 일부를 carve 연속성 가정의 한계로 재정의. [발견 조사](investigations/2026-07-02-recovery-tool-blindspots.md) 9단계. |
| 2026-07-02 | 0xC8069000 스케일 임계로도 재동기 불가 원인 | 소형 잠금군 실증 5건 중 유일한 실패(300 MCU, undec 0.843 불변, hole 1). plain 디코드는 300/300 err 0(gray 0.426). 원인 미조사. [발견 조사](investigations/2026-07-02-recovery-tool-blindspots.md) 4단계. |
