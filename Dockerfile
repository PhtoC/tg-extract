FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
ENV PYTHONUNBUFFERED=1 \
    TGX_DATA_DIR=/app/data

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY tgextract ./tgextract
RUN mkdir -p /app/data

CMD ["python", "-u", "-m", "tgextract.bot"]
