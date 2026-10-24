FROM python:3.13-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 DATA_DIR=/app/data
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg espeak-ng tesseract-ocr tesseract-ocr-eng libglib2.0-0 tini \
    && rm -rf /var/lib/apt/lists/*
COPY requirements.txt requirements.lock ./
RUN pip install --no-cache-dir -r requirements.txt -c requirements.lock
RUN groupadd -g 10001 safewalk && useradd -u 10001 -g safewalk -M safewalk \
    && mkdir -p /app/data && chown safewalk:safewalk /app/data
COPY backend ./backend
COPY specs_app ./specs_app
COPY caregiver_portal ./caregiver_portal
USER 10001:10001
EXPOSE 8000
HEALTHCHECK --interval=20s --timeout=8s --start-period=60s --retries=5 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health/ready',timeout=6)"
ENTRYPOINT ["tini", "--"]
CMD ["uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--no-access-log"]
