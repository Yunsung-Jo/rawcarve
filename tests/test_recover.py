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
