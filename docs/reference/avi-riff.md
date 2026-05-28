# RIFF/AVI 청크 구조

- **출처:** [Resource Interchange File Format (RIFF) — Microsoft Learn](https://learn.microsoft.com/en-us/windows/win32/xaudio2/resource-interchange-file-format--riff-) / [AVI RIFF File Reference — Microsoft Learn](https://learn.microsoft.com/en-us/windows/win32/directshow/avi-riff-file-reference)
- **최종 수정:** 2026-05-28

---

## RIFF 청크 헤더 바이트 레이아웃

RIFF 파일은 항상 12바이트 헤더로 시작한다.

| 오프셋 | 길이 | 값 | 설명 |
|--------|------|----|------|
| +0 | 4 | `52 49 46 46` (`"RIFF"`) | FOURCC 시그니처 |
| +4 | 4 | little-endian uint32 | `chunk_size` — 이후 데이터 크기 (바이트) |
| +8 | 4 | ASCII 4자 | form type (파일 종류 식별자) |

`chunk_size`의 정의: `"RIFF"` FOURCC 4바이트와 `chunk_size` 필드 자체 4바이트는 포함하지 않는다. 따라서 **전체 파일 크기 = `offset + 8 + chunk_size`**.

## AVI 식별 조건

form type(오프셋 +8, 4바이트)이 `41 56 49 20` (`"AVI "`, 마지막이 공백)인 경우 AVI 파일이다.

```
RIFF  <chunk_size>  AVI   <inner chunks...>
+0    +4            +8    +12
```

WAV, WEBP 등 다른 RIFF 파생 포맷도 동일한 `RIFF` 시그니처를 가지므로, AVI 여부는 반드시 form type으로 구분해야 한다.

| form type | 포맷 |
|-----------|------|
| `"AVI "` | AVI 영상 |
| `"WAVE"` | WAV 오디오 |
| `"WEBP"` | WebP 이미지 |

## 파일 크기 계산 (이 프로젝트 적용 방식)

```python
chunk_size = struct.unpack('<I', data[offset + 4:offset + 8])[0]
end_from_header = offset + 8 + chunk_size
```

`chunk_size`가 0이거나 `max_size`를 초과하거나 이미지 경계를 벗어나면 신뢰할 수 없으므로 fallback(다음 시그니처 위치 또는 `max_size` 상한)을 사용한다.

## 내부 구조 (참고)

AVI RIFF 내부에는 두 개의 필수 LIST 청크가 있다.

```
RIFF ('AVI '
    LIST ('hdrl'          ← 스트림 포맷 정의
        'avih' (...)      ← AVIMAINHEADER
        LIST ('strl'
            'strh' (...)  ← AVISTREAMHEADER
            'strf' (...)  ← 비디오: BITMAPINFO, 오디오: WAVEFORMATEX
        )
    )
    LIST ('movi'          ← 실제 A/V 데이터
        '00dc' (...)      ← 압축 비디오 프레임
        '01wb' (...)      ← 오디오 데이터
    )
    ['idx1' (...)]        ← 선택적 인덱스
)
```

카빙 목적상 내부 구조를 파싱할 필요는 없으며, 외부 RIFF 헤더의 `chunk_size`만으로 파일 경계를 결정한다.

## 패딩 규칙

청크 데이터가 홀수 바이트이면 패딩 바이트(0x00) 1개가 추가된다. `chunk_size`는 패딩을 포함하지 않으므로 실제 파일에서 청크 간 경계는 `chunk_size`가 홀수일 때 1바이트 밀릴 수 있다. 카빙 시에는 외부 RIFF `chunk_size`만 사용하므로 내부 패딩은 무관하다.
