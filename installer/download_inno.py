"""Download the official Inno Setup release with bounded parallel HTTP ranges."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.request import Request, urlopen

URL = 'https://github.com/jrsoftware/issrc/releases/download/is-6_5_3/innosetup-6.5.3.exe'
SIZE = 7769232
TARGET = Path(__file__).parent / 'tools' / 'inno-parallel.exe'


def part(index):
    start = index * SIZE // 12
    end = (index + 1) * SIZE // 12 - 1
    request = Request(URL, headers={'Range': f'bytes={start}-{end}'})
    with urlopen(request, timeout=120) as response:
        if response.status != 206:
            raise RuntimeError('Server did not accept byte range')
        value = response.read()
    if len(value) != end - start + 1:
        raise RuntimeError('Incomplete byte range')
    print(f'Part {index + 1}/12 ready', flush=True)
    return value


if __name__ == '__main__':
    with ThreadPoolExecutor(max_workers=12) as pool:
        pieces = list(pool.map(part, range(12)))
    TARGET.write_bytes(b''.join(pieces))
    print(TARGET, flush=True)
