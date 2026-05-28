# 아키텍처

## 폴더 구조

```
rawcarve/
├── carve.py
├── recover.py
├── carver/
│   ├── models.py
│   ├── extractors.py
│   ├── scanner.py
│   ├── diagnosis.py
│   └── recovery.py
├── output/
│   ├── jpeg/
│   ├── jpeg_thumbnails/
│   ├── jpeg_recovered/
│   └── avi/
└── tests/
```

## 모듈 책임

| 모듈 | 책임 |
|------|------|
| `carve.py` | 디스크 이미지에서 JPEG/AVI 추출 진입점 |
| `recover.py` | 추출된 JPEG 복구 진입점 |
| `carver/models.py` | 파일 탐색 결과를 담는 `FileHit` 데이터 클래스 |
| `carver/scanner.py` | 디스크 이미지에서 파일 시그니처 탐색 |
| `carver/extractors.py` | 탐색 결과로부터 JPEG/AVI 파일 경계 계산 |
| `carver/diagnosis.py` | JPEG 손상 원인 진단 |
| `carver/recovery.py` | 손상 블록 감지·패치·복구 |
