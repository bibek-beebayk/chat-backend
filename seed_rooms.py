import os
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "chat_project.settings")
django.setup()

from chat.models import SupportRoom

rooms = ['General Support', 'VIP Support', 'Billing', 'Technical Issues']
for name in rooms:
    SupportRoom.objects.get_or_create(name=name)
print("Support rooms created")
