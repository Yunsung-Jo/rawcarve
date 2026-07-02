# 백로그

작업 중 발견한 **off-target 문제·버그** — 현재 목표와는 다르지만 나중에 손댈 가치가 있는 항목을 모은다.
즉흥적으로 쫓지 않고 여기 적어 두며, 현재 브랜치의 조사 기록은 한 가지 목표만 다루도록 유지한다.

- 항목을 새 브랜치로 다루기 시작하면, 그 설명이 [experiment-loop](../.claude/skills/experiment-loop/SKILL.md) 1단계(문제 정리)의 출발점이 된다.
- **포맷 사실**은 여기가 아니라 `reference/`에, **현재 목표 자체를 다시 잡게 만드는 발견**은 현재 조사 기록에 적는다.

## 항목

| 발견일 | 항목 | 맥락 / 처음 본 곳 |
|--------|------|------------------|
| 2026-07-01 | 재동기 세그먼트 내 저주파(blocky) MCU 화질 | DC 리셋으로 회색→콘텐츠 복구 후에도 세그먼트 경계·비트 과소비(skew)로 일부 MCU가 저주파 단색 덩어리로 남는다. 정렬 어긋남이면 공간 연속성 채점 등 정밀 재동기 여지, 물리 소실이면 회색과 같은 한계. `feat/resync-dc-reset` 실험1 몽타주에서 사용자 관찰. [resync-limit 조사](investigations/2026-06-29-resync-limit.md)의 비트 과소비 한계와 연결. |
| 2026-07-01 | 재동기 세그먼트 Cb/Cr 색 캐스트 보정 | zero DC 리셋(resync.py `_resync_skip`)은 재동기 세그먼트의 Cb/Cr 절대 DC 오프셋을 0으로 잃어 무채색/색 캐스트를 만든다. **진짜 복구율(디코드된 영역)엔 무관**하고 `gray_fraction` 착시·육안 색 품질만 영향(`undecoded_fraction`으로는 zero가 항상 최선 — [조사](investigations/2026-07-01-resync-dc-reset.md) 3단계). 세그먼트 경계에서 위쪽 MCU 행 Cb/Cr DC로 offset 추정해 공간 연속성 보정 가능. `feat/resync-dc-reset`에서 zero 채택, 사용자가 색은 후순위로 지정해 분리. |
| 2026-07-02 | 헤더 복구 pass (빈 huff 검증 → DHT 이식 → SOS/SOF 재구성) | SKIP 122건 전부 헤더 손상, 그중 DHT 완전 소실 66건. 다수파 DHT(=Annex-K 전형, 704/822 공유) 이식만으로 plain 디코드 복원 실증(96×72군 3건 undec 0.99→0.00 등). 단계화: ① `Decoder` 빈 huff 검증(분류 버그 즉수정), ② DHT 이식+resync, ③ SOS 재구성(8건), ④ SOF 재구성(~102건: 해상도 후보=코퍼스 분포, 우측 경계 연속성 채점). [발견 조사](investigations/2026-07-02-recovery-tool-blindspots.md) 5~7단계. |
| 2026-07-02 | 계수 경계(DC 1400/AC 6000) quant-비례 보정 | 경계가 dequant 도메인 고정 상수라 DQT 큰 파일(Cb/Cr max 94 등)에서 정상 스트림을 MCU 0~2에서 err 3 오탐 → 즉시 hole·전량 회색. DHT 이식 성과도 recover 단계에서 무효화됨(0xCA9AA000 plain 89/225 vs recover 1). **헤더 복구 pass의 전제 조건.** [발견 조사](investigations/2026-07-02-recovery-tool-blindspots.md) 8단계. |
| 2026-07-02 | resync/edit 수락 임계 잔여 MCU 비례화 | 총 MCU<450이면 resync 수락(`max(250, maxW//2)`=450) 산술 불가 — RECOVERED 557 중 196건 잠금, undec 악화 66건(평균 +0.354)의 주원인. 비례 임계(probe 캡 W=min(900,잔여), 수락 max(30,0.55W))로 5건 중 4건 복구 실증(0xC91AF000 0.961→0.004). masking 가드·파일별 회귀 가드·육안 표본 전제. maxW만 줄이면 250 바닥이 지배해 실패(기각 기록 참조). [발견 조사](investigations/2026-07-02-recovery-tool-blindspots.md) 2~4단계. |
| 2026-07-02 | report 악화 플래그·무행동 FAILED 분류 | ops 0·hole 1(무행동) 70건이 RECOVERED로 분류되어 입력보다 회색 많은 재인코딩본 저장. `undec_after > undec_before` 악화 66건을 아무도 질의하지 않았음. 별도 action(FAILED)과 악화 플래그, 크기별 층화 통계 추가. [발견 조사](investigations/2026-07-02-recovery-tool-blindspots.md) 1단계·결론 4. |
| 2026-07-02 | 단편화 probe 탐색 (데이터 소진 회색의 대안 가설) | 데이터 소진형(BYTE 100%·MCU<100%) 파일의 frontier 상태(비트·DC)로 usb.img 전 클러스터 후보(~107K, 32KB 정렬)를 `decode_probe`해 이어지는 단편을 찾는 탐색. 0x95AAD000 재정지점은 섹터 비정렬로 단편 경계 아님 확인(가설 자체는 미검증으로 열림). 성공 시 "데이터 한계" 일부를 carve 연속성 가정의 한계로 재정의. [발견 조사](investigations/2026-07-02-recovery-tool-blindspots.md) 9단계. |
| 2026-07-02 | 0xC8069000 스케일 임계로도 재동기 불가 원인 | 소형 잠금군 실증 5건 중 유일한 실패(300 MCU, undec 0.843 불변, hole 1). plain 디코드는 300/300 err 0(gray 0.426). 원인 미조사. [발견 조사](investigations/2026-07-02-recovery-tool-blindspots.md) 4단계. |
