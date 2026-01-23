import os
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "chat_project.settings")
django.setup()

from chat.models import SupportRoom

rooms = [
    {'name': 'Player Support', 'room_type': 'player'},
    {'name': 'Agent Support', 'room_type': 'agent'},
    {'name': 'General Support', 'room_type': 'all'},
]
for room_data in rooms:
    obj, created = SupportRoom.objects.get_or_create(
        name=room_data['name'],
        defaults={'room_type': room_data['room_type']}
    )
    if not created and obj.room_type != room_data['room_type']:
        obj.room_type = room_data['room_type']
        obj.save()
        
print("Support rooms created/updated")
