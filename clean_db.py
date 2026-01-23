import os
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "chat_project.settings")
django.setup()

from django.contrib.auth import get_user_model
from chat.models import Room, Message, RoomParticipant, SupportRoom

User = get_user_model()

print("Cleaning database...")

# Keep superusers
superusers = User.objects.filter(is_superuser=True)
print(f"Found {superusers.count()} superusers to preserve.")

# Keep default users
default_users = User.objects.filter(username__in=['staff', 'player', 'agent'])
print(f"Found {default_users.count()} default users to preserve.")

# Delete non-superusers
deleted_users = User.objects.filter(is_superuser=False).exclude(username__in=['staff', 'player', 'agent']).delete()
print(f"Deleted non-superusers: {deleted_users}")

# Delete all rooms, messages, support rooms (cascading might have done this, but to be sure)
Room.objects.all().delete()
Message.objects.all().delete()
RoomParticipant.objects.all().delete()
SupportRoom.objects.all().delete()

print("Database cleaned.")

