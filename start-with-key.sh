#!/usr/bin/env bash
set +x
set -euo pipefail
cd -- "$(dirname -- "$0")"
PORT=8765
case ${1:-} in
  --openrouter)
    printf 'OpenRouter API 키를 붙여넣고 Enter를 누르세요 (화면에는 표시되지 않습니다): ' >&2
    IFS= read -rs OPENROUTER_API_KEY || exit 1
    printf '\n' >&2
    if [[ ! $OPENROUTER_API_KEY =~ ^sk-or-v1-[A-Za-z0-9_-]+$ ]]; then
      echo 'OpenRouter API 키 형식을 확인하세요. 저장하지 않았습니다.' >&2
      exit 1
    fi
    export OPENROUTER_API_KEY
    python3 local_keys.py OPENROUTER_API_KEY
    echo 'OpenRouter API 키를 로컬 .env에 저장했습니다.'
    exit 0
    ;;
  --brave)
    printf 'Brave Search API 키를 붙여넣고 Enter를 누르세요 (화면에는 표시되지 않습니다): ' >&2
    IFS= read -rs BRAVE_SEARCH_API_KEY || exit 1
    printf '\n' >&2
    if [[ -z $BRAVE_SEARCH_API_KEY || $BRAVE_SEARCH_API_KEY =~ [[:space:][:cntrl:]] ]]; then
      echo '빈 값이나 공백이 없는 API 키를 입력하세요. 기존 서버는 변경하지 않았습니다.' >&2
      exit 1
    fi
    export BRAVE_SEARCH_API_KEY
    key_name=BRAVE_SEARCH_API_KEY
    ;;
  '')
    printf 'YouTube Data API v3 키를 붙여넣고 Enter를 누르세요 (화면에는 표시되지 않습니다): ' >&2
    IFS= read -rs YOUTUBE_API_KEY || exit 1
    printf '\n' >&2
    if [[ ! $YOUTUBE_API_KEY =~ ^AIza[A-Za-z0-9_-]{35}$ ]]; then
      echo 'Google API 키 형식을 확인하세요. 기존 서버는 변경하지 않았습니다.' >&2
      exit 1
    fi
    export YOUTUBE_API_KEY
    key_name=YOUTUBE_API_KEY
    ;;
  *) echo '사용법: ./start-with-key.sh [--brave|--openrouter]' >&2; exit 1 ;;
esac
python3 local_keys.py "$key_name"
echo 'API 키를 로컬 .env에 저장했습니다.'
# Only replace this project's local listener, never another service.
pid=$(lsof -nP -t -iTCP:"$PORT" -sTCP:LISTEN || true)
if [[ -n $pid ]]; then
  if [[ $pid =~ ^[0-9]+$ && $(readlink "/proc/$pid/cwd") == "$(pwd -P)" && $(ps -p "$pid" -o args=) == 'python3 app.py' ]]; then
    # Preserve the other provider's key without printing or writing it.
    if [[ ! -r /proc/$pid/environ ]]; then
      echo '기존 서버의 설정을 확인할 수 없어 재시작하지 않았습니다.' >&2
      exit 1
    fi
    while IFS= read -r -d '' setting; do
      case $setting in
        YOUTUBE_API_KEY=*) if [[ -z ${YOUTUBE_API_KEY:-} ]]; then export "$setting"; fi ;;
        BRAVE_SEARCH_API_KEY=*) if [[ -z ${BRAVE_SEARCH_API_KEY:-} ]]; then export "$setting"; fi ;;
      esac
    done < "/proc/$pid/environ"
    kill -TERM "$pid"
    for _ in {1..30}; do
      lsof -nP -t -iTCP:"$PORT" -sTCP:LISTEN >/dev/null 2>&1 || break
      sleep .1
    done
  else
    echo '8765 포트를 다른 프로그램이 사용 중입니다. 종료하지 않았습니다.' >&2
    exit 1
  fi
fi
export PORT
echo '서버 실행 중에는 이 터미널을 열어 두세요. 종료: Ctrl+C'
exec python3 app.py
