"""
Seed local development database with mock players, agents, and posts.

Usage (PowerShell):
  $env:DJANGO_SETTINGS_MODULE="chat_project.settings.dev"
  ./env/Scripts/python.exe ./scripts/seed_local_dev_mock_data.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import django
from django.conf import settings
from django.db import transaction


os.environ.setdefault("DJANGO_SETTINGS_MODULE", "chat_project.settings.dev")
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
django.setup()

from django.contrib.auth import get_user_model  # noqa: E402
from posts.models import Post  # noqa: E402


User = get_user_model()


MOCK_PASSWORD = "MockPass@123"
PLAYER_COUNT = 6
AGENT_COUNT = 4


def _ensure_local_dev_only() -> None:
    if not settings.DEBUG:
        raise RuntimeError("Refusing to seed because DEBUG is False.")
    settings_module = os.environ.get("DJANGO_SETTINGS_MODULE", "")
    if "dev" not in settings_module:
        raise RuntimeError(
            f"Refusing to seed because settings module is not dev: {settings_module}"
        )


def _build_user_specs():
    specs = []
    for i in range(1, PLAYER_COUNT + 1):
        specs.append(
            {
                "username": f"mock_player_{i:02d}",
                "email": f"mock_player_{i:02d}@local.test",
                "user_type": "player",
                "agent_availability": "online",
                "agent_status_note": "",
            }
        )
    for i in range(1, AGENT_COUNT + 1):
        status_note = "Ready to help players" if i == 1 else f"Support window {i}"
        specs.append(
            {
                "username": f"mock_agent_{i:02d}",
                "email": f"mock_agent_{i:02d}@local.test",
                "user_type": "agent",
                "agent_availability": "online" if i % 2 else "busy",
                "agent_status_note": status_note,
            }
        )
    return specs


def _upsert_user(spec: dict) -> User:
    username = spec["username"]
    defaults = {
        "email": spec["email"],
        "user_type": spec["user_type"],
        "is_active": True,
        "is_verified": True,
        "agent_availability": spec["agent_availability"],
        "agent_status_note": spec["agent_status_note"],
    }
    user, created = User.objects.get_or_create(username=username, defaults=defaults)

    changed = False
    for key, value in defaults.items():
        if getattr(user, key) != value:
            setattr(user, key, value)
            changed = True

    if created or not user.check_password(MOCK_PASSWORD):
        user.set_password(MOCK_PASSWORD)
        changed = True

    if changed:
        user.save()
    return user


def _ensure_posts(users: list[User]) -> int:
    created_count = 0
    for user in users:
        for idx in range(1, 3):
            title = f"[Local Mock] {user.username} Update {idx}"
            content = (
                f"<p>This is local mock content posted by <strong>{user.username}</strong>.</p>"
                f"<p>Entry #{idx} for local testing.</p>"
            )
            visibility = "all"
            if user.user_type == "agent" and idx == 2:
                visibility = "players"
            elif user.user_type == "player" and idx == 2:
                visibility = "agents"

            _, created = Post.objects.get_or_create(
                author=user,
                title=title,
                defaults={
                    "content": content,
                    "visibility": visibility,
                    "is_pinned": idx == 1,
                    "is_active": True,
                },
            )
            if created:
                created_count += 1
    return created_count


def _write_credentials_file(users: list[User]) -> Path:
    project_root = Path(__file__).resolve().parents[1]
    temp_dir = project_root / "temp"
    temp_dir.mkdir(parents=True, exist_ok=True)
    credentials_path = temp_dir / "mock_user_credentials.txt"

    lines = [
        "LOCAL DEV MOCK USERS (AUTO-GENERATED)",
        "Do not use in staging/production.",
        "",
        f"Password for all users: {MOCK_PASSWORD}",
        "",
        "username | email | user_type",
        "-" * 64,
    ]

    for user in sorted(users, key=lambda u: (u.user_type, u.username)):
        lines.append(f"{user.username} | {user.email} | {user.user_type}")

    credentials_path.write_text("\n".join(lines), encoding="utf-8")
    return credentials_path


def main() -> None:
    _ensure_local_dev_only()
    specs = _build_user_specs()

    with transaction.atomic():
        users = [_upsert_user(spec) for spec in specs]
        posts_created = _ensure_posts(users)

    credentials_path = _write_credentials_file(users)

    print("Mock data seeding complete.")
    print(f"Users ensured: {len(users)}")
    print(f"Posts created this run: {posts_created}")
    print(f"Credentials file: {credentials_path}")


if __name__ == "__main__":
    main()
