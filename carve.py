import argparse
import mmap
import struct
import sys
from pathlib import Path

from tqdm import tqdm

from carver.extractors import jpeg_end, avi_end, MAX_AVI_SIZE_DEFAULT, JPEG_MAX_FALLBACK_SIZE
from carver.models import FileHit
from carver.scanner import find_all_hits


def make_output_dirs(output_dir: Path, save_thumbnails: bool) -> None:
    (output_dir / 'jpeg').mkdir(parents=True, exist_ok=True)
    (output_dir / 'avi').mkdir(parents=True, exist_ok=True)
    if save_thumbnails:
        (output_dir / 'jpeg_thumbnails').mkdir(parents=True, exist_ok=True)


def is_in_range(offset: int, ranges: list[tuple[int, int]]) -> bool:
    return any(start < offset < end for start, end in ranges)


def process(
    mm: mmap.mmap,
    hits: list[FileHit],
    output_dir: Path,
    max_avi_bytes: int,
    save_thumbnails: bool,
    error_log,
) -> dict:
    offsets = [h.offset for h in hits]
    jpeg_count = avi_count = thumb_count = error_count = 0
    extracted_ranges: list[tuple[int, int]] = []

    for i, hit in enumerate(tqdm(hits, desc='추출 중', unit='파일')):
        next_sig = offsets[i + 1] if i + 1 < len(offsets) else None
        offset = hit.offset

        try:
            embedded = is_in_range(offset, extracted_ranges)

            if embedded and hit.file_type == 'jpeg':
                thumb_count += 1
                if save_thumbnails:
                    try:
                        end, _ = jpeg_end(mm, offset, next_sig)
                    except (ValueError, struct.error):
                        end = next_sig if next_sig is not None else offset + JPEG_MAX_FALLBACK_SIZE
                        end = min(end, len(mm))
                    out_path = output_dir / 'jpeg_thumbnails' / f'0x{offset:08X}.jpg'
                    out_path.write_bytes(mm[offset:end])
                    tqdm.write(f'[THUMB] JPEG at 0x{offset:08X} → {out_path}')
                else:
                    tqdm.write(f'[THUMB] JPEG at 0x{offset:08X} → skipped (embedded thumbnail)')
                continue

            if embedded:
                continue

            if hit.file_type == 'jpeg':
                end, complete = jpeg_end(mm, offset, next_sig)
                file_bytes = mm[offset:end]
                extracted_ranges.append((offset, end))
                jpeg_count += 1
                out_path = output_dir / 'jpeg' / f'0x{offset:08X}.jpg'
                out_path.write_bytes(file_bytes)
                warn = '' if complete else ' [불완전, fallback 사용]'
                tqdm.write(
                    f'[FOUND] JPEG at 0x{offset:08X} → {out_path} '
                    f'({len(file_bytes) / 1024:.1f} KB){warn}'
                )

            elif hit.file_type == 'avi':
                end, used_header = avi_end(mm, offset, max_avi_bytes, next_sig)
                file_bytes = mm[offset:end]
                extracted_ranges.append((offset, end))
                avi_count += 1
                out_path = output_dir / 'avi' / f'0x{offset:08X}.avi'
                out_path.write_bytes(file_bytes)
                warn = '' if used_header else ' [fallback 사용]'
                tqdm.write(
                    f'[FOUND] AVI  at 0x{offset:08X} → {out_path} '
                    f'({len(file_bytes) / 1024 / 1024:.1f} MB){warn}'
                )

        except Exception as e:
            error_count += 1
            msg = f'오류 at 0x{offset:08X} ({hit.file_type}): {e}'
            tqdm.write(f'[ERROR] {msg}')
            error_log.write(msg + '\n')

    return {
        'jpeg': jpeg_count,
        'avi': avi_count,
        'thumbnails': thumb_count,
        'errors': error_count,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description='손상된 디스크 이미지에서 JPEG/AVI 파일을 추출합니다.'
    )
    parser.add_argument('image', help='디스크 이미지 파일 경로')
    parser.add_argument('-o', '--output', default='output', help='출력 디렉토리 (기본: ./output)')
    parser.add_argument('--max-avi-size', type=int, default=500, metavar='MB',
                        help='AVI 최대 크기 MB (기본: 500)')
    parser.add_argument('--save-thumbnails', action='store_true',
                        help='썸네일을 jpeg_thumbnails/ 에 저장')
    args = parser.parse_args()

    image_path = Path(args.image)
    output_dir = Path(args.output)
    max_avi_bytes = args.max_avi_size * 1024 * 1024

    if not image_path.exists():
        print(f'오류: 파일을 찾을 수 없습니다: {image_path}', file=sys.stderr)
        sys.exit(1)

    make_output_dirs(output_dir, args.save_thumbnails)

    image_size = image_path.stat().st_size
    print(f'Scanning {image_path} ({image_size / 1024 / 1024:.2f} MB)...')
    print('시그니처 탐색 중...')

    with open(image_path, 'rb') as f:
        mm = mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ)
        hits = find_all_hits(mm)
        print(f'시그니처 발견: {len(hits)}개')

        with open(output_dir / 'errors.log', 'a', encoding='utf-8') as error_log:
            result = process(mm, hits, output_dir, max_avi_bytes, args.save_thumbnails, error_log)

        mm.close()

    print(
        f'\nScan complete. '
        f"JPEG: {result['jpeg']}, "
        f"AVI: {result['avi']}, "
        f"Thumbnails: {result['thumbnails']}, "
        f"Errors: {result['errors']}"
    )


if __name__ == '__main__':
    main()
