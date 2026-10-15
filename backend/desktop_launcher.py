"""Windowless Windows entry point. Keep diagnostics available without a console."""
import ctypes
import os
import sys
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path


def main():
    root = Path(__file__).resolve().parents[1]
    log_dir = Path(os.environ.get('LOCALAPPDATA', Path.home())) / 'CatalystCutoff' / 'logs'
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f'desktop-{os.getpid()}.log'
    # pythonw has no standard streams; Uvicorn and startup diagnostics need them.
    with log_path.open('w', encoding='utf-8', buffering=1) as stream, redirect_stdout(stream), redirect_stderr(stream):
        try:
            from backend.launcher import main as launch, settings_path
            if len(sys.argv) == 1 and not settings_path().exists():
                previous = root.parent / '.work' / 'implementation-20261014' / 'september-rehearsal'
                if (previous / 'database' / 'closing.sqlite').is_file():
                    sys.argv.extend(['--data-dir', str(previous)])
            try:
                result = launch()
            except SystemExit as exc:
                result = exc.code if isinstance(exc.code, int) else 1
            if result:
                stream.flush()
                lines = log_path.read_text(encoding='utf-8').splitlines()
                detail = next((line for line in reversed(lines) if '실행할 수 없습니다:' in line or '이미 실행 중' in line), '프로그램을 시작하지 못했습니다.')
                ctypes.windll.user32.MessageBoxW(None, detail + '\n\n실행 기록: ' + str(log_path), '촉매 마감 실행 안내', 0x10)
            return result
        except Exception as exc:
            import traceback
            traceback.print_exc()
            stream.flush()
            ctypes.windll.user32.MessageBoxW(None, f'프로그램을 시작하지 못했습니다.\n{exc}\n\n실행 기록: {log_path}', '촉매 마감 실행 안내', 0x10)
            return 1


if __name__ == '__main__':
    raise SystemExit(main())
