import os
from pathlib import Path


class AlreadyRunning(RuntimeError):
    pass


class WorkspaceLock:
    """The OS releases this lock even after a crash; the file itself may remain."""

    def __init__(self, root: Path):
        self.path = root / '.runtime.lock'
        self.handle = None

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.handle = self.path.open('a+b')
        self.handle.seek(0, 2)
        if self.handle.tell() == 0:
            self.handle.write(b'0')
            self.handle.flush()
        self.handle.seek(0)
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(self.handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            self.handle.close()
            self.handle = None
            raise AlreadyRunning('이 자료 폴더는 이미 실행 중입니다. 열린 프로그램을 사용해 주세요.') from exc
        return self

    def __exit__(self, *_):
        if self.handle:
            self.handle.close()
            self.handle = None
