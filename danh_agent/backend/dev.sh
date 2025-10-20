PORT="${PORT:-8080}"
# PORT="${PORT:-10000}"
uvicorn open_webui.main:app --port $PORT --host 0.0.0.0 --forwarded-allow-ips '*' --reload