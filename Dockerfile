FROM python:3.12-slim

# Bibliothèques système nécessaires au moteur de rendu skia
RUN apt-get update \
 && apt-get install -y --no-install-recommends libgl1 libegl1 libfontconfig1 \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .

ENV PYTHONUNBUFFERED=1
CMD ["python", "bot.py"]
