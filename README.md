# Chat Application Backend

Django backend for a real-time chat application with WebSocket support using Django Channels.

## Features

- **User Authentication**: Session-based authentication with custom user model
- **Role-Based Access Control**: Three user types (Player, Agent, Staff)
- **Real-Time Chat**: WebSocket support via Django Channels
- **Chat Rooms**: Staff-assigned support rooms
- **REST API**: Comprehensive API for chat functionality
- **Staff Dashboard**: Dedicated dashboard for staff members

## Technology Stack

- **Django 4.2.9**: Web framework
- **Django REST Framework**: API development
- **Django Channels**: WebSocket support
- **PostgreSQL**: Database
- **Redis**: Channel layer backend
- **CORS Headers**: Cross-origin support

## Prerequisites

Before you begin, ensure you have the following installed:

- Python 3.8+
- PostgreSQL
- Redis Server
- pip (Python package manager)

## Installation

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. Set Up PostgreSQL Database

Create a PostgreSQL database:

```bash
createdb chat_db
```

Or using PostgreSQL CLI:

```sql
CREATE DATABASE chat_db;
```

### 3. Set Up Environment Variables

Copy the example environment file and configure it:

```bash
cp .env.example .env
```

Edit `.env` with your database and Redis credentials.

### 4. Run Migrations

```bash
python manage.py makemigrations
python manage.py migrate
```

### 5. Create Superuser

```bash
python manage.py createsuperuser
```

### 6. Create Rooms and Assign Staff

Use Django admin to create rooms and assign staff members:

1. Start the development server (see below)
2. Navigate to `http://localhost:8000/admin/`
3. Create rooms under "Chat > Rooms"
4. Assign staff members to rooms

## Running the Application

### Start Redis Server

Ensure Redis is running:

```bash
redis-server
```

### Start Django Development Server

```bash
python manage.py runserver
```

Or with Daphne (ASGI server for WebSocket support):

```bash
daphne -b 127.0.0.1 -p 8000 chat_project.asgi:application
```

The API will be available at `http://localhost:8000/`

## API Endpoints

### Authentication

- `POST /api/auth/register/` - Register new user
- `POST /api/auth/login/` - Login user
- `POST /api/auth/logout/` - Logout user
- `GET /api/auth/me/` - Get current user

### Chat

- `GET /api/rooms/` - List available rooms
- `GET /api/rooms/<id>/` - Get room details
- `GET /api/rooms/<id>/messages/` - Get room messages
- `POST /api/rooms/<id>/join/` - Join a room
- `GET /api/staff/dashboard/` - Staff dashboard (staff only)

### WebSocket

- `ws://localhost:8000/ws/chat/<room_id>/` - WebSocket connection for chat

## User Types

1. **Player**: Can join rooms and chat with staff
2. **Agent**: Can join rooms and chat with staff (similar to players)
3. **Staff**: Assigned to one room, provides support, has access to staff dashboard

## Project Structure

```
chat-backend/
├── manage.py
├── requirements.txt
├── chat_project/          # Main project settings
│   ├── settings.py
│   ├── urls.py
│   ├── asgi.py
│   └── wsgi.py
├── accounts/              # User authentication app
│   ├── models.py
│   ├── views.py
│   ├── serializers.py
│   ├── urls.py
│   └── admin.py
└── chat/                  # Chat functionality app
    ├── models.py
    ├── views.py
    ├── consumers.py       # WebSocket consumers
    ├── routing.py         # WebSocket routing
    ├── serializers.py
    ├── urls.py
    └── admin.py
```

## Development Notes

- Make sure PostgreSQL and Redis are running before starting the server
- Use the Django admin panel to manage rooms and assign staff
- WebSocket connections require authentication (session cookies)
- CORS is configured for `localhost:3000` (frontend)

## Production Deployment

For production deployment:

1. Set `DEBUG=False` in settings
2. Use a proper secret key
3. Configure `ALLOWED_HOSTS`
4. Use a production ASGI server (Daphne, Uvicorn)
5. Set up a Redis server
6. Configure PostgreSQL with proper credentials
7. Set `SESSION_COOKIE_SECURE=True` for HTTPS
8. Use environment variables for sensitive data
