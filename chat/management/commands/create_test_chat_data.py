from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

from chat.models import SupportRoom


class Command(BaseCommand):
    help = "Create isolated test users and test support rooms."

    def add_arguments(self, parser):
        parser.add_argument(
            "--password",
            type=str,
            default="Test@12345",
            help="Password used for all created test users.",
        )
        parser.add_argument(
            "--staff-count",
            type=int,
            default=2,
            help="Number of test staff users to create.",
        )
        parser.add_argument(
            "--player-count",
            type=int,
            default=3,
            help="Number of test player users to create.",
        )
        parser.add_argument(
            "--agent-count",
            type=int,
            default=2,
            help="Number of test agent users to create.",
        )

    def handle(self, *args, **options):
        user_model = get_user_model()
        password = options["password"]

        created = {"staff": 0, "player": 0, "agent": 0}
        existing = {"staff": 0, "player": 0, "agent": 0}

        def create_users(role: str, count: int):
            for index in range(1, count + 1):
                username = f"test_{role}_{index}"
                email = f"{username}@example.local"
                user, was_created = user_model.objects.get_or_create(
                    username=username,
                    defaults={
                        "email": email,
                        "user_type": role,
                        "is_test_user": True,
                        "is_active": True,
                        "is_verified": True,
                    },
                )
                if was_created:
                    user.set_password(password)
                    user.save(update_fields=["password"])
                    created[role] += 1
                else:
                    user.user_type = role
                    user.is_test_user = True
                    user.is_active = True
                    user.email = user.email or email
                    user.save(
                        update_fields=["user_type", "is_test_user", "is_active", "email"]
                    )
                    existing[role] += 1

        create_users("staff", options["staff_count"])
        create_users("player", options["player_count"])
        create_users("agent", options["agent_count"])

        room_specs = [
            ("[TEST] Player Support", "player"),
            ("[TEST] Agent Support", "agent"),
            ("[TEST] General Support", "all"),
        ]
        created_rooms = 0
        updated_rooms = 0
        for room_name, room_type in room_specs:
            room, was_created = SupportRoom.objects.get_or_create(
                name=room_name,
                defaults={
                    "room_type": room_type,
                    "is_test_room": True,
                    "is_active": False,
                },
            )
            if was_created:
                created_rooms += 1
            else:
                changed = False
                if room.room_type != room_type:
                    room.room_type = room_type
                    changed = True
                if not room.is_test_room:
                    room.is_test_room = True
                    changed = True
                if changed:
                    room.save(update_fields=["room_type", "is_test_room"])
                    updated_rooms += 1

        self.stdout.write(self.style.SUCCESS("Test chat data setup complete."))
        self.stdout.write(
            f"Users created: staff={created['staff']}, player={created['player']}, agent={created['agent']}"
        )
        self.stdout.write(
            f"Users already existed/updated: staff={existing['staff']}, player={existing['player']}, agent={existing['agent']}"
        )
        self.stdout.write(
            f"Support rooms created={created_rooms}, updated={updated_rooms}"
        )
        self.stdout.write(
            self.style.WARNING(
                "Reminder: run migrations first and keep test users/rooms only for controlled QA."
            )
        )
