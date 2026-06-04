# 설계: recover.py 출력의 분류별 폴더 분리

- 날짜: 2026-06-04
- 상태: 승인됨 (구현 대기)
- 관련 코드: `recover.py`, `carver/resync.py`, `tests/test_resync.py`

## 배경 / 문제

현재 `recover.py`는 추출된 손상 JPEG를 일괄 복구하면서 각 파일을 네 가지로 분류한다:

- `RECOVERED` — 복구 성공, 재인코딩 JPEG를 `out_dir`에 저장
- `CLEAN` — 손상 없음(ops==0 && gray_before<0.02), 파일 안 씀
- `SKIP_UNDECODABLE` — 디코더 파싱 실패, 파일 안 씀
- `ERROR` — 워커 예외(`recover.py` `_work`에서 포착), 파일 안 씀

`report.csv`에는 네 분류가 모두 기록되지만, 디스크에 실제로 떨어지는 파일은 `RECOVERED`뿐이다. 그 결과 손상 없던 원본(CLEAN)이나 복구 불가 원본(SKIP/ERROR)을 결과 폴더에서 따로 모아 보거나 후속 처리할 수 없다.

## 목표

복구 결과를 분류별 하위 폴더로 나누어 저장한다. 미복구 분류(CLEAN/SKIP/ERROR)는 원본을 해당 폴더에 복사해 한곳에 모은다.

## 결정된 접근 (접근 A)

각 책임 위치에서 직접 파일을 쓴다. 워커가 디스크에 바로 쓰는 현재의 메모리 효율(큰 RGB 배열을 프로세스 경계로 반환하지 않음)을 유지하고 변경을 최소화한다.

대안으로 검토했으나 버린 것:
- **접근 B (라우팅 헬퍼 단일화):** 폴더명 규칙을 한 함수로 모음. 추가 추상화 대비 이득이 작아 채택하지 않음. 폴더명 규칙은 단순(`action.lower()`)하므로 인라인한다.
- **접근 C (caller가 전부 결정):** `recover_file`이 RGB를 반환하고 호출자가 저장. 프로세스 경계로 대용량 배열을 직렬화·전송해야 하므로 메모리·성능상 비권장.

## 설계

### 1. 출력 폴더 구조

```
output/jpeg_recovered/
├── report.csv              # 전체 분류 기록 (현행 유지)
├── recovered/              # 재인코딩된 복구본 (RECOVERED)
├── clean/                  # 손상 없던 원본 복사 (CLEAN)
├── skip_undecodable/       # 디코드 실패 원본 복사 (SKIP_UNDECODABLE)
└── error/                  # 워커 예외 발생 원본 복사 (ERROR)
```

- 폴더명 규칙: `action.lower()`.
- `main()`이 dispatch 전에 네 폴더를 모두 미리 생성한다(해당 분류가 0건이어도 폴더는 존재해 결과 구조가 일관됨).
- 워커/`recover_file`도 쓰기 직전 `mkdir(parents=True, exist_ok=True)`로 방어적으로 보장한다(독립 호출·멀티프로세스 경쟁에 안전; `exist_ok=True`는 race-safe).

### 2. `recover_file()` 변경 (`carver/resync.py`)

- 대상 폴더 = `out_dir / action.lower()`, 쓰기 직전 `mkdir(parents=True, exist_ok=True)`.
- `RECOVERED` → `recovered/`에 재인코딩 JPEG 저장(현행 동작, 위치만 하위 폴더로).
- `CLEAN` → `clean/`에 **원본 바이트 복사**(이미 읽어 둔 `data` 재사용), 실제 경로 반환.
- `SKIP_UNDECODABLE` → `skip_undecodable/`에 원본 바이트 복사, 실제 경로 반환.
- 반환 시그니처 `(out_path|None, action, stats)`는 유지하되, 이제 CLEAN/SKIP도 `out_path`가 `None`이 아닌 실제 경로다. (SKIP은 디코더 생성 실패로 조기 반환하므로 `stats`는 `{}` 유지.)

### 3. ERROR 처리 (`recover.py` `_work`)

- 예외 포착 시 `out_dir / 'error'`에 원본을 복사한 뒤 `'ERROR'`를 반환한다.
- 복사 자체가 실패하더라도 ERROR 분류·CSV 기록은 유지한다(복사 예외는 삼킴).

### 4. 폴더 목록 상수

- 미리 생성할 폴더 목록 `('recovered', 'clean', 'skip_undecodable', 'error')`를 `recover.py` `main`에 상수로 둔다. 폴더명 도출 규칙 자체(`action.lower()`)는 쓰기 지점에 인라인.

## 데이터 흐름

1. `main()` — 입력 디렉토리 스캔, `out_dir` 및 4개 하위 폴더 생성, 워커 dispatch.
2. 워커 `_work()` — `recover_file()` 호출.
   - 정상 경로: `recover_file`이 분류 판정 + 해당 하위 폴더에 저장.
   - 예외 경로: `_work`이 `error/`에 원본 복사 + `'ERROR'` 반환.
3. `emit()` — 분류 결과를 `report.csv`에 한 줄 기록, 카운트 집계.

## 오류 처리

- 하위 폴더 생성: `exist_ok=True`로 멱등·경쟁 안전.
- ERROR 원본 복사 실패: 삼키고 분류·기록은 진행(배치 견고성 우선).
- SKIP_UNDECODABLE: 디코더 생성 실패 시점에 원본 복사 후 반환.

## 테스트 (`tests/test_resync.py`)

- **CLEAN 복사:** 깨끗한 JPEG 입력 → `out_dir/clean/`에 원본과 바이트 동일한 복사본 생성 확인.
- **RECOVERED 라우팅:** 복구 대상 입력 → 출력이 `out_dir/recovered/` 아래에 위치하고 유효 JPEG인지 확인.
- **(선택) SKIP 복사:** 디코드 불가 입력 → `out_dir/skip_undecodable/`에 원본 복사 확인.
- 기존 `test_recover_file_roundtrip`는 RECOVERED일 때만 `out.exists()`를 검사하므로 호환됨.

## 문서

- `docs/specs/0002-recover.md`(recover.py 스펙) 출력 동작 갱신.
- 루트 `README.md` 출력 폴더 구조 설명 갱신.
- ADR: 폴더 분리는 자명한 동작 변경으로 판단해 작성하지 않음.

## 비목표 (YAGNI)

- RECOVERED 폴더를 복구 강도(회색 잔존율 등)로 더 세분하지 않는다.
- `report.csv`에 출력 경로 컬럼을 추가하지 않는다(분류값으로 폴더가 결정되므로 불필요).
- 폴더명 커스터마이즈 옵션을 추가하지 않는다.
