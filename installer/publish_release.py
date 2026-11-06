"""Publish the Windows installer using Git's existing credential manager."""
import json
import hashlib
from pathlib import Path
import subprocess
from urllib.request import Request, urlopen

REPO = 'balagarsage3-web/schedule-desktop'
TAG = 'v1.0.0'
ASSET = Path(__file__).resolve().parents[1] / 'release' / 'Schedule-Setup-1.0.0.exe'


def main():
    credential = subprocess.run(['git', 'credential', 'fill'],
        input='protocol=https\nhost=github.com\n\n', text=True,
        capture_output=True, check=True)
    fields = dict(line.split('=', 1) for line in credential.stdout.splitlines() if '=' in line)
    token = fields.get('password')
    if not token:
        raise RuntimeError('GitHub credential is unavailable')
    headers = {'Authorization': 'Bearer ' + token,
               'Accept': 'application/vnd.github+json',
               'X-GitHub-Api-Version': '2022-11-28', 'User-Agent': 'ScheduleDesktop-release'}

    def api(url, method='GET', body=None, binary=None):
        request_headers = dict(headers)
        payload = binary
        if body is not None:
            payload = json.dumps(body).encode('utf-8')
            request_headers['Content-Type'] = 'application/json'
        if binary is not None:
            request_headers['Content-Type'] = 'application/octet-stream'
        request = Request(url, data=payload, headers=request_headers, method=method)
        with urlopen(request, timeout=1800) as response:
            return json.load(response)

    base = 'https://api.github.com/repos/' + REPO
    releases = api(base + '/releases')
    release = next((r for r in releases if r['tag_name'] == TAG), None)
    if release is None:
        release = api(base + '/releases', 'POST', body={
            'tag_name': TAG, 'target_commitish': 'main', 'name': 'Расписание 1.0.0 — Windows',
            'draft': True, 'prerelease': False,
            'body': 'Установщик desktop-приложения для Windows 10 (1809+) / Windows 11 x64.\n\n'
                    'Скачайте Schedule-Setup-1.0.0.exe, запустите и следуйте мастеру установки. '
                    'Python и Node.js не требуются. При отсутствии WebView2 установщик загрузит его через интернет.\n\n'
                    'Первый вход: admin / admin. На новом компьютере создаётся чистая база данных.'})
        print('Draft release created', flush=True)
    asset = next((a for a in release['assets'] if a['name'] == ASSET.name), None)
    if asset is None:
        print('Uploading installer (' + str(ASSET.stat().st_size) + ' bytes)', flush=True)
        asset = api(release['upload_url'].split('{')[0] + '?name=' + ASSET.name,
                    'POST', binary=ASSET.read_bytes())
    if asset['size'] != ASSET.stat().st_size or asset['state'] != 'uploaded':
        raise RuntimeError('Uploaded asset verification failed')
    if asset.get('digest'):
        expected = 'sha256:' + hashlib.sha256(ASSET.read_bytes()).hexdigest()
        if asset['digest'] != expected:
            raise RuntimeError('Uploaded asset checksum mismatch')
    if release['draft']:
        release = api(base + '/releases/' + str(release['id']), 'PATCH', body={'draft': False})
    print(release['html_url'], flush=True)
    print(asset['browser_download_url'], flush=True)
    print('Verified installer size: ' + str(asset['size']), flush=True)


if __name__ == '__main__':
    main()
