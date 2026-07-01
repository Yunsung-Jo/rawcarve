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
