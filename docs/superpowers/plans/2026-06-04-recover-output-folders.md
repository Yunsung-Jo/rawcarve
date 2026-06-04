# recover 출력 분류별 폴더 분리 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `recover.py`의 복구 결과를 분류별 하위 폴더(`recovered/`, `clean/`, `skip_undecodable/`, `error/`)로 나누어 저장하고, 미복구 분류는 원본을 해당 폴더에 복사한다.

**Architecture:** 접근 A — 각 책임 위치에서 직접 파일을 쓴다. `recover_file()`(carver/resync.py)이 RECOVERED/CLEAN/SKIP_UNDECODABLE를 판정해 `out_dir/<action.lower()>/`에 저장하고, ERROR는 `recover.py`의 워커 `_work()`에서 `error/`에 원본을 복사한다. 워커가 디스크에 직접 쓰는 현재 메모리 효율(대용량 RGB 배열을 프로세스 경계로 반환하지 않음)을 유지한다.

**Tech Stack:** Python 3, numpy, Pillow, pytest, multiprocessing.

---

## File Structure

- `carver/resync.py` — `recover_file()` 수정. 분류별 하위 폴더 라우팅 + CLEAN/SKIP 원본 복사.
- `recover.py` — `_work()`에 ERROR 원본 복사 추가. `main()`에 하위 폴더 사전 생성.
- `tests/test_resync.py` — `recover_file` 라우팅/복사 동작 테스트 추가.
- `tests/test_recover.py` — (신규) `_work` ERROR 복사 테스트.
- `docs/specs/0002-recover.md` — 출력 동작 갱신.
- `README.md` — 출력 폴더 구조 설명 갱신.

---

## Task 1: `recover_file` 분류별 폴더 라우팅 (RECOVERED/CLEAN/SKIP)

**Files:**
- Modify: `carver/resync.py:235-262` (`recover_file`)
- Test: `tests/test_resync.py`

- [ ] **Step 1: RECOVERED 라우팅 실패 테스트 작성**

`tests/test_resync.py` 끝에 추가:

```python
def test_recover_file_routes_recovered_subdir(tmp_path):
    """RECOVERED 결과는 out_dir/recovered/ 아래에 저장된다."""
    src = tmp_path / '0xDEADBEEF.jpg'
    src.write_bytes(corrupt_entropy(encode(textured_image()), n_bytes=24))
    out, action, info = resync.recover_file(src, tmp_path)
    assert action == 'RECOVERED'
    assert out.parent == tmp_path / 'recovered'
    assert out.exists()
    Image.open(out).load()                       # 유효 JPEG
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `python -m pytest tests/test_resync.py::test_recover_file_routes_recovered_subdir -v`
Expected: FAIL — `out.parent`가 `tmp_path`(하위 폴더 아님)이므로 assert 실패.

- [ ] **Step 3: `recover_file` 구현 수정**

`carver/resync.py`의 `recover_file` 본문에서 RECOVERED/CLEAN/SKIP 반환부를 아래로 교체. 함수 시작의 SKIP 분기(디코더 생성 실패)도 원본 복사를 추가한다.

기존:

```python
    data = src_path.read_bytes()
    try:
        dec = jd.Decoder(data)
    except Exception:
        return None, 'SKIP_UNDECODABLE', {}
```

교체 후:

```python
    data = src_path.read_bytes()
    try:
        dec = jd.Decoder(data)
    except Exception:
        skip_path = out_dir / 'skip_undecodable' / (src_path.stem + '.jpg')
        skip_path.parent.mkdir(parents=True, exist_ok=True)
        skip_path.write_bytes(data)
        return skip_path, 'SKIP_UNDECODABLE', {}
```

기존:

```python
    if ops == 0 and before < 0.02:
        return None, 'CLEAN', info
    out_path = out_dir / (src_path.stem + '.jpg')
    out_path.write_bytes(_to_jpeg(rgb, quality))
    return out_path, 'RECOVERED', info
```

교체 후:

```python
    if ops == 0 and before < 0.02:
        clean_path = out_dir / 'clean' / (src_path.stem + '.jpg')
        clean_path.parent.mkdir(parents=True, exist_ok=True)
        clean_path.write_bytes(data)
        return clean_path, 'CLEAN', info
    out_path = out_dir / 'recovered' / (src_path.stem + '.jpg')
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(_to_jpeg(rgb, quality))
    return out_path, 'RECOVERED', info
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `python -m pytest tests/test_resync.py::test_recover_file_routes_recovered_subdir -v`
Expected: PASS

- [ ] **Step 5: 커밋**

```bash
git add carver/resync.py tests/test_resync.py
git commit -m "feat: recover_file 결과를 분류별 하위 폴더로 라우팅

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 2: CLEAN 원본 복사 동작 테스트

**Files:**
- Test: `tests/test_resync.py`
- (구현은 Task 1에서 이미 완료 — 본 태스크는 CLEAN 경로 검증)

- [ ] **Step 1: CLEAN 복사 실패 테스트 작성**

`tests/test_resync.py` 끝에 추가:

```python
def test_recover_file_clean_copies_original(tmp_path):
    """손상 없는 JPEG는 clean/ 폴더에 원본 바이트 그대로 복사된다."""
    src = tmp_path / '0xCAFEBABE.jpg'
    raw = encode(textured_image())
    src.write_bytes(raw)
    out, action, info = resync.recover_file(src, tmp_path)
    assert action == 'CLEAN'
    assert out.parent == tmp_path / 'clean'
    assert out.read_bytes() == raw               # 원본 바이트 동일
```

- [ ] **Step 2: 테스트 실행**

Run: `python -m pytest tests/test_resync.py::test_recover_file_clean_copies_original -v`
Expected: PASS (Task 1 구현이 CLEAN 경로를 이미 처리). 만약 입력이 CLEAN으로 분류되지 않아 실패하면, 깨끗한 인코딩이 `ops==0 and before<0.02`를 만족하는지 확인하고 필요 시 `quality`를 높여 재인코딩 손상을 줄인다(예: `encode(textured_image(), quality=98)`).

- [ ] **Step 3: 기존 테스트 회귀 확인**

Run: `python -m pytest tests/test_resync.py -v`
Expected: 전체 PASS (기존 `test_recover_file_roundtrip` 포함).

- [ ] **Step 4: 커밋**

```bash
git add tests/test_resync.py
git commit -m "test: CLEAN 분류 원본 복사 동작 검증 추가

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 3: ERROR 원본 복사 + 하위 폴더 사전 생성 (recover.py)

**Files:**
- Modify: `recover.py:16-24` (`_work`)
- Modify: `recover.py:58-60` (`main`의 `out_dir` 생성부)
- Test: `tests/test_recover.py` (신규)

- [ ] **Step 1: `_work` ERROR 복사 실패 테스트 작성**

`tests/test_recover.py` 신규 생성:

```python
"""recover.py 워커 동작 검증."""
from pathlib import Path

import recover


def test_work_error_copies_original(tmp_path, monkeypatch):
    """recover_file이 예외를 던지면 원본을 error/ 폴더에 복사하고 ERROR를 반환한다."""
    src = tmp_path / '0xBADF00D.jpg'
    raw = b'\xff\xd8not-a-real-jpeg\xff\xd9'
    src.write_bytes(raw)

    def boom(*args, **kwargs):
        raise RuntimeError('decode blew up')

    monkeypatch.setattr(recover, 'recover_file', boom)

    name, action, info, err = recover._work(
        src, tmp_path, quality=95, time_budget=None, near=300000, full=True)

    assert action == 'ERROR'
    assert err == 'decode blew up'
    copied = tmp_path / 'error' / '0xBADF00D.jpg'
    assert copied.read_bytes() == raw
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `python -m pytest tests/test_recover.py::test_work_error_copies_original -v`
Expected: FAIL — `error/` 복사가 아직 없어 `copied.read_bytes()`가 FileNotFoundError.

- [ ] **Step 3: `_work`에 ERROR 복사 구현**

`recover.py`의 `_work`를 아래로 교체:

```python
def _work(path: Path, out_dir: Path, quality: int, time_budget, near: int, full: bool):
    """워커: 파일 1개 복구. 예외는 ERROR 액션으로 변환해 반환."""
    try:
        _out, action, info = recover_file(
            path, out_dir, quality=quality,
            time_budget=time_budget, resync_near=near, resync_full=full)
        return path.name, action, info, None
    except Exception as e:  # noqa: BLE001 — 배치 견고성 위해 모든 예외 포착
        try:
            err_path = out_dir / 'error' / path.name
            err_path.parent.mkdir(parents=True, exist_ok=True)
            err_path.write_bytes(path.read_bytes())
        except Exception:  # noqa: BLE001 — 복사 실패해도 분류·기록은 유지
            pass
        return path.name, 'ERROR', {}, str(e)
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `python -m pytest tests/test_recover.py::test_work_error_copies_original -v`
Expected: PASS

- [ ] **Step 5: `main`에 하위 폴더 사전 생성 추가**

`recover.py`의 `main`에서 `out_dir.mkdir(...)` 직후(현재 line 60)에 추가:

```python
    out_dir.mkdir(parents=True, exist_ok=True)
    for sub in ('recovered', 'clean', 'skip_undecodable', 'error'):
        (out_dir / sub).mkdir(exist_ok=True)
```

- [ ] **Step 6: 전체 테스트 회귀 확인**

Run: `python -m pytest -q`
Expected: 전체 PASS.

- [ ] **Step 7: 커밋**

```bash
git add recover.py tests/test_recover.py
git commit -m "feat: ERROR 원본을 error/ 폴더에 복사, 하위 폴더 사전 생성

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 4: 문서 갱신 (spec + README)

**Files:**
- Modify: `docs/specs/0002-recover.md`
- Modify: `README.md`

- [ ] **Step 1: `docs/specs/0002-recover.md` 출력 동작 갱신**

해당 spec에서 출력 디렉토리/저장 동작을 기술한 부분을 찾아, 다음 내용을 반영한다:
- 출력은 `out_dir` 아래 네 하위 폴더로 분리: `recovered/`(재인코딩 복구본), `clean/`(손상 없던 원본 복사), `skip_undecodable/`(디코드 실패 원본 복사), `error/`(워커 예외 원본 복사).
- `report.csv`는 `out_dir` 최상위에 그대로 유지하며 네 분류를 모두 기록.
- 폴더명 규칙은 `action.lower()`. `main`이 dispatch 전에 네 폴더를 사전 생성한다.

먼저 현재 내용을 읽고(`docs/specs/0002-recover.md`) 기존 서술 스타일에 맞춰 해당 단락만 수정한다.

- [ ] **Step 2: `README.md` 출력 폴더 구조 설명 갱신**

README에서 recover.py 사용법/출력 설명 부분을 찾아 출력 폴더 구조 트리를 추가한다:

```
output/jpeg_recovered/
├── report.csv
├── recovered/          # 복구본 (재인코딩 JPEG)
├── clean/              # 손상 없던 원본 복사
├── skip_undecodable/   # 디코드 실패 원본 복사
└── error/              # 워커 예외 원본 복사
```

먼저 README의 recover 관련 섹션을 읽고 기존 형식에 맞춰 삽입한다.

- [ ] **Step 3: 커밋**

```bash
git add docs/specs/0002-recover.md README.md
git commit -m "docs: recover 출력 폴더 분리 동작 문서화

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## 완료 후

모든 태스크 완료 후 `finishing-a-development-branch` 스킬로 통합한다. 그 전에 CLAUDE.md 규칙대로 영향받은 spec/README는 Task 4에서 갱신 완료. `architecture.md`는 모듈 책임 변화가 없으므로(파일 추가 없음, 동작만 확장) 갱신 불필요로 판단하되, 검토 시 출력 구조 한 줄 보강 여부를 확인한다.
