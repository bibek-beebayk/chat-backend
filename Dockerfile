FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# System deps
RUN apt-get update && apt-get install -y \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Python deps
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Project files
COPY . .

# Collect static (if needed)
RUN python manage.py collectstatic --noinput || true

# Start Daphne
CMD ["sh", "-c", "daphne -b 0.0.0.0 -p $PORT project.asgi:application"]
