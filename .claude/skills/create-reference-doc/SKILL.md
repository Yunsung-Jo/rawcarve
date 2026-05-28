---
name: create-reference-doc
description: Use when needing external knowledge (file formats, binary specs, library APIs, standards) during development but docs/reference/ has no file covering it yet — symptoms include uncertainty about magic bytes, chunk structures, encoding rules, or third-party API behavior
---

# 레퍼런스 파일 생성

## Overview

작업 중 외부 스펙·포맷·API 지식이 필요한데 `docs/reference/`에 해당 파일이 없을 때,
정보를 수집해 레퍼런스 파일을 만들고 작업을 이어간다.

## When to Use

- 파일 포맷의 구조가 불확실할 때 (JPEG 마커, AVI RIFF 청크, PNG 시그니처 등)
- 라이브러리 동작·API 세부사항을 확인해야 할 때
- RFC·표준의 특정 조항이 필요할 때
- `docs/reference/README.md` 목록에 관련 항목이 없을 때

## Process

서브에이전트를 띄워 아래 작업을 위임한다. 메인 컨텍스트에 검색 결과가 쌓이지 않도록 하기 위함이다.

서브에이전트 지시 내용:
1. **기존 파일 확인** — `docs/reference/` 디렉토리와 `README.md`를 확인해 동일 주제 파일이 있으면 새로 만들지 않고 기존 파일 경로를 보고한다.
2. **범위 확정** — 필요한 정보가 무엇인지 한 문장으로 정리한다.
3. **검색** — WebSearch / WebFetch로 공식 문서, RFC, Wikipedia, 소스 리포지터리를 확인한다.
4. **핵심만 추출** — 작업과 직접 관련된 내용만 담는다. 전체 스펙을 옮기지 않는다.
5. **파일 생성** — `docs/reference/0000-template.md`를 복사해 `docs/reference/<주제>.md`를 만든다.
6. **목록 업데이트** — `docs/reference/README.md` 표에 한 줄 추가한다.
7. **완료 보고** — 생성한 파일 경로와 담긴 내용을 한 단락으로 요약해 반환한다.

메인 컨텍스트는 요약만 받아 작업을 재개한다.

## Template 구조

```markdown
# [제목]

- **출처:** 공식 스펙 | 실측 | 외부 문서 (링크 또는 설명)
- **최종 수정:** YYYY-MM-DD

---

(내용은 자유 형식)
```

## 파일명 규칙

`<주제>.md` — 소문자, 하이픈 구분  
예: `jpeg-format.md`, `avi-riff.md`, `pillow-image-api.md`

## Common Mistakes

| 실수 | 수정 |
|------|------|
| 스펙 전체를 복사해 넣기 | 현재 작업에 필요한 섹션만 |
| README.md 목록 업데이트 누락 | 파일 생성 직후 반드시 추가 |
| 출처 링크 생략 | 나중에 검증할 수 있도록 반드시 기재 |
