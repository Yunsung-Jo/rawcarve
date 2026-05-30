---
name: antigravity-review
description: Use when reviewing implementation plans, specs, ADRs, or code changes — triggers at writing-plans completion, after spec/ADR authoring, or before finishing-a-development-branch
---

# Antigravity 리뷰

## 개요

`mcp__antigravity__ask_antigravity`를 호출해 독립적인 분석을 위임한다. Antigravity는 자체 도구로 파일을 읽고 git 명령을 직접 실행할 수 있으므로, 파일 내용을 prompt에 직렬화하지 않는다.

## 언제 사용하는가

| 트리거 | 리뷰 대상 |
|--------|----------|
| `writing-plans` 완료 후 | 계획의 논리적 빈틈, 빠진 엣지 케이스 |
| spec/ADR 작성 후 | 완결성, 모호한 정의, 대안 검토 누락 |
| `finishing-a-development-branch` 전 | 코드 정확성, 설계 문제 |
| 새 복구 전략 설계 시 | 전략의 견고성, 손상 패턴 커버리지 |
| 파서/추출기 로직 변경 시 | 바이너리 포맷 처리 정확성 |

**사용하지 않는 경우:** 단순 버그픽스, 한두 줄 수정.

## 호출 방법

`add_dirs`에 프로젝트 루트를 항상 전달한다. `@파일명`(프로젝트 루트 기준 상대 경로)으로 특정 파일을 참조한다. `permission_mode: "default"`로 충분하다 — 파일 읽기와 `git log`/`git diff` 실행 모두 가능하다.

```
mcp__antigravity__ask_antigravity(
  prompt="@docs/specs/0002-recover.md 이 스펙의 완결성을 검토해줘. ...",
  add_dirs=["<project_root>"],
  permission_mode="default"
)
```

**절대 하지 말 것** — 불필요한 수동 직렬화:
```
# ❌ 파일을 직접 읽어서 prompt에 붙여넣기
content = read("recover.py")
prompt = f"다음 파일을 리뷰해줘:\n{content}"
```

## 프롬프트 템플릿

### 계획 / Spec / ADR 리뷰
```
@<파일경로> 이 문서를 검토해줘.
- 논리적 빈틈이나 빠진 엣지 케이스가 있는지
- 모호하게 정의된 동작이 있는지
- 대안 검토가 충분한지
```

### 코드 리뷰
```
현재 브랜치(main 대비)의 변경사항을 코드 리뷰해줘.
git diff main..HEAD로 변경 내용을 직접 확인하고,
변경된 파일을 @파일명으로 참조해서:
- 버그나 엣지 케이스 누락
- 설계 문제
- 변경되지 않은 관련 파일과의 일관성
```

**주의:** `@파일명`은 실제 변경된 파일을 git diff로 확인한 뒤 결정한다. 예시 파일명을 그대로 쓰지 않는다.

## 대화 이어가기 (선택)

응답에 포함된 `conversation_id`를 저장해두면 같은 맥락에서 후속 질문을 이어갈 수 있다.

```
# 후속 질문 예시
mcp__antigravity__ask_antigravity(
  prompt="2번 지적사항을 이렇게 수정하면 괜찮을까?",
  conversation_id="<이전 응답의 conversation_id>",
  add_dirs=["<project_root>"],
  permission_mode="default"
)
```

새 브랜치나 새 문서를 리뷰할 때는 `conversation_id` 없이 새 대화로 시작한다.

## 흔한 실수

| 실수 | 올바른 방법 |
|------|------------|
| `permission_mode: "ask"` 지정 | `"default"` 사용 (ask는 존재하지 않음) |
| 파일 내용을 직접 prompt에 삽입 | `add_dirs` + `@파일명` 사용 |
| `add_dirs` 없이 호출 | 항상 프로젝트 루트를 `add_dirs`에 전달 |
| git diff를 Claude가 직접 실행해서 붙여넣기 | Antigravity에게 git 실행 위임 |
| `@docs/specs/` 처럼 디렉토리 참조 | `@`는 파일 단위만 가능 (`@docs/specs/0002-recover.md`) |
