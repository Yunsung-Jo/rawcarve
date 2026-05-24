# recover.py
from __future__ import annotations
import argparse
import csv
import sys
from pathlib import Path

from tqdm import tqdm

from carver.diagnosis import diagnose
from carver.recovery import detect_damaged_blocks, recover_file, _force_decode_arr


def _damage_pct(data: bytes) -> float:
    arr = _force_decode_arr(data)
    if arr is None:
        return 1.0
    return float(detect_damaged_blocks(arr).mean())


def main() -> None:
    parser = argparse.ArgumentParser(
        description='rawcarve가 추출한 JPEG 파일을 복구합니다.'
    )
    parser.add_argument('input', help='입력 디렉토리 (output/jpeg/)')
    parser.add_argument('-o', '--output', default=None,
                        help='출력 디렉토리 (기본: <input>_recovered)')
    args = parser.parse_args()

    in_dir = Path(args.input)
    if not in_dir.is_dir():
        print(f'오류: 디렉토리를 찾을 수 없습니다: {in_dir}', file=sys.stderr)
        sys.exit(1)

    out_dir = (Path(args.output) if args.output
               else in_dir.parent / (in_dir.name + '_recovered'))
    out_dir.mkdir(parents=True, exist_ok=True)

    jpeg_files = sorted(in_dir.glob('*.jpg'))
    if not jpeg_files:
        print('JPEG 파일을 찾을 수 없습니다.')
        return

    fieldnames = [
        'filename', 'causes', 'action',
        'damaged_block_pct', 'recovered_block_pct',
        'cut_offset_kb', 'image_size',
    ]
    counts: dict[str, int] = {}

    with open(out_dir / 'report.csv', 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()

        for path in tqdm(jpeg_files, desc='복구 중', unit='파일'):
            row: dict[str, str] = {k: '' for k in fieldnames}
            row['filename'] = path.name
            try:
                dr = diagnose(path)
                row['causes'] = ';'.join(dr.causes)

                before_pct = _damage_pct(path.read_bytes())
                result_path, action = recover_file(path, dr, out_dir)
                row['action'] = action

                after_pct = 0.0
                if result_path is not None and result_path.exists():
                    after_pct = _damage_pct(result_path.read_bytes())

                row['damaged_block_pct'] = f'{before_pct:.3f}'
                row['recovered_block_pct'] = f'{after_pct:.3f}'

                if dr.sof:
                    row['image_size'] = f'{dr.sof[0]}x{dr.sof[1]}'
                if dr.first_bad_offset is not None and dr.scan_start >= 0:
                    kb = (dr.scan_start + dr.first_bad_offset) / 1024
                    row['cut_offset_kb'] = f'{kb:.1f}'

            except Exception as e:
                row['action'] = 'ERROR'
                row['causes'] = 'ERROR'
                tqdm.write(f'[ERROR] {path.name}: {e}')

            writer.writerow(row)
            counts[row['action']] = counts.get(row['action'], 0) + 1
            if row['action'] not in ('CLEAN',):
                tqdm.write(f"[{row['action']}] {path.name}")

    print(f"\n완료. 리포트: {out_dir / 'report.csv'}")
    for action, cnt in sorted(counts.items()):
        print(f'  {action}: {cnt}개')


if __name__ == '__main__':
    main()
