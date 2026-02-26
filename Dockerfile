FROM python:3.11-slim

RUN apt-get update && apt-get install -y \
    ffmpeg \
    fonts-noto \
    wget \
    gcc \
    && wget -q -O /usr/share/fonts/Kalpurush.ttf "https://github.com/googlefonts/kalpurush/raw/main/fonts/ttf/Kalpurush.ttf" || true \
    && fc-cache -fv \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .

CMD gunicorn --timeout 3600 --workers 1 --bind 0.0.0.0:$PORT app:app
