FROM python:3.13-slim

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends libpq5 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV PERSISTANCE_PORT=8003
EXPOSE 8003

CMD ["sh", "-c", "python migrate.py && uvicorn main:app --host 0.0.0.0 --port ${PERSISTANCE_PORT}"]
