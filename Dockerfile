FROM python:3.12-slim

RUN pip install --no-cache-dir uv==0.11.32
WORKDIR /app
COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --frozen --no-dev --no-install-project
COPY app/ app/
COPY data/meridian_dataset/scheduling_db/ data/meridian_dataset/scheduling_db/
COPY data/meridian_dataset/knowledge_base/ data/meridian_dataset/knowledge_base/

ENV PATH=/app/.venv/bin:$PATH PYTHONUNBUFFERED=1
# Runs as root so the Railway volume at /data is writable.
CMD ["python", "-m", "app"]
