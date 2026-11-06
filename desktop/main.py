"""Windows desktop entry point. No development runtime is required after freezing."""
import ctypes
import json
import logging
import os
from pathlib import Path
import secrets
import socket
import sys
import threading
import time
import urllib.request


def main():
    smoke = '--smoke-test' in sys.argv
    data = Path(os.getenv('LOCALAPPDATA', str(Path.home()))) / 'ScheduleDesktop'
    if smoke:
        import tempfile
        data = Path(tempfile.mkdtemp(prefix='schedule-smoke-'))
    data.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(filename=data / 'desktop.log', level=logging.INFO,
                        format='%(asctime)s %(levelname)s %(message)s')
    resource = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent.parent))
    secret_file = data / 'secret.key'
    if not secret_file.exists():
        secret_file.write_text(secrets.token_hex(32), encoding='ascii')
    os.environ['DATABASE_URL'] = 'sqlite:///' + (data / 'schedule.db').as_posix()
    os.environ['SECRET_KEY'] = secret_file.read_text(encoding='ascii').strip()
    os.environ['FRONTEND_DIST'] = str(resource / 'frontend' / 'dist')
    if not getattr(sys, 'frozen', False):
        sys.path.insert(0, str(resource / 'backend'))

    import uvicorn
    from app.main import app
    import webview

    webview.settings['ALLOW_DOWNLOADS'] = True
    sock = socket.socket()
    sock.bind(('127.0.0.1', 0))
    port = sock.getsockname()[1]
    config = uvicorn.Config(app, log_config=None, access_log=False, lifespan='on')
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, kwargs={'sockets': [sock]}, daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 60
        while not server.started:
            if not thread.is_alive() or time.monotonic() > deadline:
                raise RuntimeError('Не удалось запустить сервер. Подробности в ' + str(data / 'desktop.log'))
            time.sleep(0.1)
        url = f'http://127.0.0.1:{port}'
        if smoke:
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            assert json.loads(opener.open(url + '/api/health').read())['ok']
            assert b'<html' in opener.open(url).read().lower()
            request = urllib.request.Request(url + '/api/auth/login',
                data=json.dumps({'login': 'admin', 'password': 'admin'}).encode(),
                headers={'Content-Type': 'application/json'})
            assert 'token' in json.loads(opener.open(request).read())
            (Path(sys.executable).parent / 'smoke-test-ok.txt').write_text('Health, UI, login OK', encoding='utf-8')
        else:
            webview.create_window('Расписание', url, width=1360, height=900, min_size=(960, 640))
            webview.start(gui='edgechromium', storage_path=str(data / 'webview'))
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        sock.close()
        if smoke:
            from app.db import engine
            engine.dispose()
            import shutil
            shutil.rmtree(data, ignore_errors=True)


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        logging.exception('Desktop startup failed')
        if '--smoke-test' not in sys.argv:
            ctypes.windll.user32.MessageBoxW(0, str(error), 'Расписание — ошибка запуска', 0x10)
        sys.exit(1)
