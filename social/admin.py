from django.contrib import admin

from .models import UserConnection, UserOnboardingState


@admin.register(UserOnboardingState)
class UserOnboardingStateAdmin(admin.ModelAdmin):
    list_display = (
        'user',
        'has_seen_agent_suggestions',
        'has_seen_player_suggestions',
        'has_completed_social_onboarding',
        'onboarding_version',
        'updated_at',
    )
    search_fields = ('user__username', 'user__email')


@admin.register(UserConnection)
class UserConnectionAdmin(admin.ModelAdmin):
    list_display = (
        'id',
        'requester',
        'receiver',
        'connection_type',
        'status',
        'initiated_from_onboarding',
        'updated_at',
    )
    list_filter = ('connection_type', 'status', 'initiated_from_onboarding')
    search_fields = (
        'requester__username',
        'requester__email',
        'receiver__username',
        'receiver__email',
    )

