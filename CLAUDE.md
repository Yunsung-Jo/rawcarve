# rawcarve

ddrescue 등으로 복구한 손상된 디스크 이미지(.img)에서
JPEG 이미지와 AVI 영상 파일을 추출하고, 손상된 JPEG를 복구하는 파일 카빙 도구.

- **carve.py** — 디스크 이미지에서 JPEG/AVI를 시그니처 기반으로 추출
- **recover.py** — 추출된 손상 JPEG의 비트스트림 디싱크를 resync 엔진으로 복구

## 작업 규칙

- **main에 직접 커밋 금지.** 커밋 전 현재 브랜치가 main이면 feature 브랜치를 먼저 생성한다.
- 브랜치명: `<타입>/<짧은-설명>` (예: `feat/avi-recovery`, `fix/jpeg-scan`)
- 로컬 머지 시 항상 `--squash` 플래그를 사용한다.
  (`git merge --squash <branch>` → 커밋 → `git branch -d <branch>`)

## 커밋 메시지 규칙

Conventional Commits 형식, 한글. 제목 50자 이내, 본문에 변경 이유와 맥락을 담는다.
`Co-Authored-By` 트레일러 필수.

## 문서

@docs/README.md

- 문서 유형(스펙·ADR·조사 기록·보고서·레퍼런스)을 작성·갱신할 때는 대응하는 작성 스킬을 호출한다 — 목표·독자·문체·제목·자가점검을 따른다: `write-spec` · `write-adr` · `write-investigation` · `write-report` · `write-reference`. (템플릿은 구조를, 스킬은 작성 품질을 담당한다.)
- 문서를 작성·수정한 뒤에는 `review-doc` 스킬로 검토한다 — 수치 원자료 재계산·코드 참조 grep·링크·단정/추론 구분·검증 실행을 능동 확인한다(작성 자가점검이 못 잡는 정밀도 결함을 거른다).
- 비자명한 기술 결정(설계 대안 선택, fallback 전략, 포맷 처리 방식 등)이 있으면 ADR을 작성한다. 결정이 확정되면 상태를 Accepted로, 기존 결정이 대체되면 Superseded로 업데이트한다.
- `finishing-a-development-branch` 스킬을 호출하기 전에 아래 문서를 먼저 생성·업데이트한다:
  - 영향받은 spec
  - architecture.md
  - README.md
  - 필요한 ADR·조사 기록·보고서·레퍼런스 문서
