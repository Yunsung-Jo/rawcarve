import mmap
from carver.models import FileHit

_JPEG_SIG = b'\xff\xd8\xff'
_RIFF_SIG = b'RIFF'
_AVI_TYPE = b'AVI '


def find_all_hits(mm: mmap.mmap) -> list[FileHit]:
    """
    디스크 이미지에서 모든 JPEG/AVI 시그니처 위치를 반환 (오프셋 순 정렬).

    두 번 순회 방식: JPEG 전체 탐색 후 RIFF(AVI) 전체 탐색.
    각 탐색은 bytes.find() 루프로 O(n) 수행.
    """
    size = len(mm)
    hits: list[FileHit] = []

    # JPEG 시그니처 탐색
    pos = 0
    while True:
        p = mm.find(_JPEG_SIG, pos)
        if p == -1:
            break
        hits.append(FileHit(file_type='jpeg', offset=p))
        pos = p + 1

    # AVI 시그니처 탐색 (RIFF + AVI  검증으로 WAV 등 제외)
    pos = 0
    while True:
        p = mm.find(_RIFF_SIG, pos)
        if p == -1:
            break
        if p + 12 <= size and mm[p + 8:p + 12] == _AVI_TYPE:
            hits.append(FileHit(file_type='avi', offset=p))
        pos = p + 1

    hits.sort(key=lambda h: h.offset)
    return hits
