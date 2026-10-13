"""Run with python -m backend.launcher; only loopback traffic is accepted."""
import argparse
import json
import os
import socket
import sys
import webbrowser
from pathlib import Path

import uvicorn

from backend.api.app import create_app

REPO = Path(__file__).resolve().parents[1]


def settings_path():
    return Path(os.environ.get('LOCALAPPDATA', Path.home() / '.local/share')) / 'CatalystCutoff' / 'settings.json'


def remember_data_dir(selected):
    config = settings_path()
    config.parent.mkdir(parents=True, exist_ok=True)
    temporary = config.with_suffix('.tmp')
    temporary.write_text(json.dumps({'data_dir': str(selected)}, ensure_ascii=False), encoding='utf-8')
    temporary.replace(config)


def choose_data_dir(explicit=None, choose=False):
    config = settings_path()
    if explicit:
        selected = Path(explicit).expanduser().resolve()
    else:
        selected = None
        if config.exists() and not choose:
            saved = json.loads(config.read_text(encoding='utf-8'))
            candidate = Path(saved['data_dir'])
            if (candidate / 'database' / 'closing.sqlite').exists():
                selected = candidate.resolve()
            else:
                raise RuntimeError('저장된 자료 폴더를 찾지 못했습니다. 연결을 확인하거나 --choose-data-dir로 기존 자료 폴더를 선택해 주세요.')
        if selected is None:
            import tkinter as tk
            from tkinter import filedialog
            root = tk.Tk()
            root.withdraw()
            try:
                folder = filedialog.askdirectory(title='촉매 마감 자료를 보관할 폴더를 선택해 주세요', mustexist=True)
            finally:
                root.destroy()
            if not folder:
                return None
            selected = Path(folder).resolve()
    if selected == REPO or REPO in selected.parents:
        raise RuntimeError('업무 자료는 코드 폴더 밖의 별도 폴더를 선택해 주세요.')
    selected.mkdir(parents=True, exist_ok=True)
    return selected


def main():
    parser = argparse.ArgumentParser(description='촉매 월 마감 로컬 실행기')
    parser.add_argument('--data-dir', type=Path)
    parser.add_argument('--choose-data-dir', action='store_true')
    parser.add_argument('--no-browser', action='store_true')
    parser.add_argument('--port', type=int, default=0)
    args = parser.parse_args()
    try:
        static = REPO / 'frontend' / 'dist'
        if not (static / 'index.html').exists():
            raise RuntimeError('화면 빌드가 필요합니다. frontend에서 npm ci와 npm run build를 실행해 주세요.')
        data_dir = choose_data_dir(args.data_dir, args.choose_data_dir)
        if data_dir is None:
            return 0
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            if hasattr(socket, 'SO_EXCLUSIVEADDRUSE'):
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            sock.bind(('127.0.0.1', args.port))
            url = f'http://127.0.0.1:{sock.getsockname()[1]}'

            def ready():
                # Remember only a successfully initialized workspace; CLI test runs stay isolated.
                if not args.data_dir:
                    remember_data_dir(data_dir)
                print(f'CATALYST_URL={url}', flush=True)
                if not args.no_browser:
                    webbrowser.open(url)

            class ReadyServer(uvicorn.Server):
                async def startup(self, sockets=None):
                    await super().startup(sockets=sockets)
                    if self.started:
                        ready()

            app = create_app(data_dir, static, on_shutdown=lambda: setattr(server, 'should_exit', True))
            server = ReadyServer(uvicorn.Config(app, host='127.0.0.1', log_level='warning', access_log=False, proxy_headers=False))
            server.run(sockets=[sock])
            return 0 if server.started else 1
    except (RuntimeError, OSError, ValueError, KeyError) as exc:
        print(f'실행할 수 없습니다: {exc}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
