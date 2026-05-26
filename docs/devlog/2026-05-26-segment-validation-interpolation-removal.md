# 세그먼트 유효성 검증 및 보간 제거

**날짜:** 2026-05-26  
**브랜치:** fix/segment-validation-interpolation-removal

---

## 기획 배경

Progressive JPEG 다중 스캔 지원을 위해 `_SCAN_BOUNDARY_MARKERS`를 도입한 이후 두 가지 문제가 생겼다.

첫 번째는 회귀 버그였다. `_find_scan_end`가 스캔 데이터 내부의 비트 플립(`FF C4` 등)을 진짜 세그먼트 경계로 오인해 스캔 범위를 조기에 종료했다. `0x17D30000.jpg`를 분석하면서 발견했는데, 853210번지에서 스캔이 잘리고 그 이후 136,656 바이트가 범위 밖으로 밀려났다. 잘린 영역은 `_collect_violations` 탐지 대상이 아니어서 패치도 안 됐고, libjpeg은 `FF C4`를 DHT로 해석하다 실패해 회색으로 채웠다.

두 번째는 보간 아티팩트였다. 사용자가 복구 이미지에서 "반복되는 바이트 패턴"을 HxD로 확인했다. 비트 플립은 바이트 유실이 없어 패치 후 정상 디코딩이 가능한데, `interpolate_damaged_blocks`가 이웃 블록의 단색 평균으로 채우면 DCT에서 동일 허프만 코드가 반복되는 아티팩트가 발생했다.

> "FF C4 케이스만 처리하는 거야? 아니면 다른 케이스도 탐지할 수 있는거야? 비트 플롭이면 저 케이스만 생기는 건 아닐테니. 보간 로직은 필요없다고 생각해."

---

## 주요 결정

### `_is_valid_segment` 헬퍼 도입

경계 마커 후보 위치에서 실제 JPEG 세그먼트인지 검증하는 함수를 추가했다. 검증 조건은 세 가지다:
1. 길이 필드 2바이트를 읽을 수 있어야 한다
2. 길이 값 ≥ 2
3. 세그먼트 끝(`ff_pos + 2 + seg_len`) 바로 뒤가 `0xFF`이거나 파일 끝

### `_NO_LEN_BOUNDARY = frozenset([0xD8, 0xD9, 0xDA])` 설계 결정

처음 플랜에서는 `_NO_LEN_BOUNDARY = frozenset([0xD8, 0xD9])`로 SOI/EOI만 포함했다. 그런데 SOS(`FF DA`)는 뒤에 스캔 데이터가 바로 시작하므로 "다음 바이트가 `0xFF`"인 게 보장되지 않는다. Progressive JPEG 테스트에서 회귀를 확인한 후 `0xDA`를 추가했다.

### `interpolate_damaged_blocks` 전면 삭제

보간 제거에는 두 옵션이 있었다: (1) 함수를 유지하되 호출만 제거, (2) 함수 자체 삭제. 비트 플립이 근본 원인이고 바이트 유실이 없으니 패치 후 정상 디코딩으로 충분하다는 판단 하에 함수 자체를 삭제했다. `_MAX_RADIUS = 16` 상수도 함께 삭제.

### `_recover_interpolate_only` → `_recover_force_decode` 개명

함수명에 "보간"이 남아 있으면 의도를 오해할 수 있어 이름도 바꿨다. 액션 문자열도 `RECOVERED_INTERPOLATED` → `RECOVERED_DECODED`로 변경.

---

## 사용자 피드백 / 주요 프롬프트

> "방금 실행해보니 지금 로직도 반복 바이트로 이미지를 저장하는 것 같아."

`_arr_to_jpeg`로 재인코딩할 때 단색 블록은 DCT에서 동일한 허프만 코드로 인코딩되어 반복 바이트가 나타난다. 이건 JPEG 압축의 정상 동작이다. 보간 후 재인코딩이 아니라 단순 강제 디코딩 후 재인코딩이어도 회색 영역이 있으면 같은 현상이 발생한다. 이 부분은 해결 대상이 아님을 확인했다.

---

## 구현 중 발견된 문제와 수정

### `_is_valid_segment`의 SOS 처리 실패

`test_diagnose_progressive_scan_boundary_not_bad_stuff`가 실패하면서 발견했다. `FF DA` 다음에는 SOS 헤더 길이만큼 건너뛴 뒤 스캔 데이터가 시작하는데, 스캔 데이터 첫 바이트가 `0xFF`일 수도 있고 아닐 수도 있다. "다음 바이트가 `0xFF`" 조건이 Progressive JPEG의 정상 SOS를 비트 플립으로 오진했다. → `0xDA`를 `_NO_LEN_BOUNDARY`에 추가해 SOS는 길이 검증 없이 항상 유효로 처리.

### 기존 `_find_scan_end` 테스트 픽스처 교체

`test_find_scan_end_stops_at_sda`와 `test_find_scan_end_rst_continues`의 합성 SOS 데이터(`FF DA`)가 `_is_valid_segment` 검증 강화 후 통과하지 못했다. 기존 픽스처가 단순히 `FF DA`만 사용했는데, 이제는 실제로 유효한 SOS 구조(`FF DA 00 04 AB CD FF`: length=4, 2바이트 payload, 뒤에 `0xFF`)로 교체했다.

---

## 최종 결과

- **커밋 3개**로 구현 완료 (`eae75d8`, `4b7955a`, `60fa341`)
- 테스트 72개 통과 (기존 64개 + `_is_valid_segment` 8개 신규)
- `0x17D30000.jpg`: `FF C4`(853210번지)가 위반으로 탐지·패치됨, 패치 후 gray 0%
- Progressive JPEG: 정상 `FF DA` 경계 여전히 올바르게 처리됨

---

## 알려진 한계

### 90% 임계값 문제 (`0x9E4A9000.jpg`)

`0x9E4A9000.jpg` 분석: 9개 `FF XX` 위반을 패치했는데도 gray 89.8%였다. 원인은 `FF XX`가 아닌 Huffman 데이터 내부의 비트 플립이다. 이런 손상은 `_collect_violations`로 탐지할 수 없고, libjpeg이 해당 지점부터 회색으로 채운다.

현재 임계값 `>= 0.90`이면 `SKIP_TOO_DAMAGED`인데, 89.8% 회색인 이미지는 사실상 쓸모없지만 저장된다. 임계값을 낮추거나(예: `>= 0.50`) 다른 전략을 검토할 필요가 있다.
