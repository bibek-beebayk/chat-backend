import os
import django
from django.conf import settings

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'chat_project.settings')
django.setup()

from django.contrib.auth import get_user_model
from chat.models import Room, Message, SupportRoom
from rest_framework.test import APIRequestFactory, force_authenticate
from chat.views import room_list_view, room_messages_view, SupportRoomViewSet

User = get_user_model()
factory = APIRequestFactory()

def run():
    print("--- Setting up Scenario ---")
    # 1. Setup Users
    staff1, _ = User.objects.get_or_create(username='staff1', defaults={'user_type': 'staff'})
    staff2, _ = User.objects.get_or_create(username='staff2', defaults={'user_type': 'staff'})
    player1, _ = User.objects.get_or_create(username='player1', defaults={'user_type': 'player'})
    
    # 2. Setup Support Room
    player_support, _ = SupportRoom.objects.get_or_create(name='Player Support', defaults={'room_type': 'player'})
    
    # Clear previous state
    player_support.staff = None
    player_support.is_active = False
    player_support.save()
    Room.objects.all().delete()
    
    # 3. Staff1 Enters Player Support
    print("-> Staff1 entering Player Support")
    player_support.staff = staff1
    player_support.is_active = True
    player_support.save()
    
    # 4. Player1 creates a room (via room list view or auto)
    # Simulate Player1 hitting room_list_view
    req = factory.get('/api/rooms/')
    force_authenticate(req, user=player1)
    response = room_list_view(req)
    player_room_data = response.data[0]
    room_id = player_room_data['id']
    print(f"-> Player1 created Room {room_id}")
    
    # Verify Staff1 is assigned (auto-assignment logic in view)
    room = Room.objects.get(id=room_id)
    print(f"-> Room {room_id} assigned to: {room.staff_assigned}")
    
    # 5. Staff1 sends a message
    Message.objects.create(room=room, sender=staff1, content="Hello from Staff1")
    
    # 6. Staff1 Leaves
    print("-> Staff1 leaving Player Support")
    player_support.staff = None
    player_support.is_active = False
    player_support.save()
    
    # 7. Staff2 Enters
    print("-> Staff2 entering Player Support")
    player_support.staff = staff2
    player_support.is_active = True
    player_support.save()
    
    # 8. Staff2 Checks Room List
    print("-> Staff2 checking Room List")
    req = factory.get('/api/rooms/')
    force_authenticate(req, user=staff2)
    response = room_list_view(req)
    
    found = False
    for r in response.data:
        if r['id'] == room_id:
            found = True
            print(f"SUCCESS: Staff2 sees Room {room_id}")
            print(f"Room Data: {r}")
            # Check if Staff2 can see messages
            req_msg = factory.get(f'/api/rooms/{room_id}/messages/')
            force_authenticate(req_msg, user=staff2)
            msg_response = room_messages_view(req_msg, room_id=room_id)
            if msg_response.status_code == 200:
                print(f"SUCCESS: Staff2 can fetch messages. Count: {len(msg_response.data)}")
            else:
                print(f"FAILURE: Staff2 cannot fetch messages. Status: {msg_response.status_code}")
            break
            
    if not found:
        print("FAILURE: Staff2 DOES NOT see the room in the list.")

if __name__ == "__main__":
    run()
