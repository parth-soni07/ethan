FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
# BuildKit cache mount: downloaded wheels survive between builds (and failed attempts), and stay out of the image.
RUN --mount=type=cache,target=/root/.cache/pip pip install --retries 10 --timeout 300 -r requirements.txt
COPY backend/ backend/
COPY data/ data/
USER nobody
ENV PORT=8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
  CMD python -c "import os, urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{os.environ[\"PORT\"]}/api/accuracy', timeout=4)"
CMD ["sh", "-c", "exec uvicorn backend.app:app --host 0.0.0.0 --port \"$PORT\""]
