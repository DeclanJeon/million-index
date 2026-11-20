"""Read and save local API keys without evaluating shell syntax."""
import os
from pathlib import Path
import stat
from tempfile import NamedTemporaryFile

ENV_PATH = Path(__file__).resolve().with_name('.env')
KEYS = ('YOUTUBE_API_KEY', 'BRAVE_SEARCH_API_KEY', 'OPENROUTER_API_KEY')


def read_keys(path=ENV_PATH):
    try:
        with path.open(encoding='utf-8') as stream:
            info = os.fstat(stream.fileno())
            if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o077:
                raise ValueError('.env 권한을 확인하세요. chmod 600 .env')
            values = {}
            for line in stream:
                name, sep, value = line.strip().partition('=')
                if sep and name in KEYS and value and not any(c.isspace() for c in value):
                    values[name] = value
            return values
    except FileNotFoundError:
        return {}


def load_keys(path=ENV_PATH):
    for name, value in read_keys(path).items():
        if not os.environ.get(name):
            os.environ[name] = value


def save_keys(values, path=ENV_PATH):
    merged = read_keys(path)
    for name, value in values.items():
        if name not in KEYS or not value or any(c.isspace() for c in value):
            raise ValueError('API 키에 빈 값이나 공백을 사용할 수 없습니다.')
        merged[name] = value
    with NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent,
                            prefix='.env-tmp-', delete=False) as stream:
        temp = Path(stream.name)
        try:
            for name in KEYS:
                if name in merged:
                    stream.write(f'{name}={merged[name]}\n')
            stream.close()
            temp.replace(path)
        finally:
            temp.unlink(missing_ok=True)


if __name__ == '__main__':
    import sys
    name = sys.argv[1]
    try:
        save_keys({name: os.environ.get(name, '')})
    except (OSError, ValueError) as error:
        sys.exit(str(error))
