FROM python:3.11-slim
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpoppler-cpp-dev \
    poppler-utils \
    tesseract-ocr \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY webapp/backend/requirements_cloudrun.txt .
RUN pip install --no-cache-dir -r requirements_cloudrun.txt
COPY core /core
COPY webapp/backend/app /app/app
COPY bq_service_account.json /app/bq_service_account.json
COPY gdrive_key.json /app/gdrive_key.json
ENV GDRIVE_KEY_PATH="/app/gdrive_key.json"
ENV GOOGLE_APPLICATION_CREDENTIALS="/app/bq_service_account.json"
ENV PYTHONPATH="/:/app:/core:${PYTHONPATH}"
EXPOSE 8080
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8080} --workers 1"]
