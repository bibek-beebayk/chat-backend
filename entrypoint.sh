#!/bin/sh

# Wait for database (optional)
echo "Waiting for DB..."
sleep 5  # or use a proper wait-for-db script

# Apply migrations
python manage.py migrate --noinput

# Collect static files
python manage.py collectstatic --noinput

# Start Daphne
exec daphne -b 0.0.0.0 -p $PORT chat_project.asgi:application
