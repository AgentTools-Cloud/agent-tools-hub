FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

COPY pyproject.toml README.md ./
COPY hub ./hub
RUN pip install --no-cache-dir .

RUN mkdir -p /var/lib/agent-tools-hub

EXPOSE 9300

CMD ["uvicorn", "hub.main:app", "--host", "0.0.0.0", "--port", "9300", "--workers", "2"]
