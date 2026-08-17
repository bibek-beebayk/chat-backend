from django.contrib import admin
from .models import RocketRound


@admin.register(RocketRound)
class RocketRoundAdmin(admin.ModelAdmin):
    list_display = ('user', 'status', 'wager_amount', 'auto_cashout_multiplier', 'cashout_multiplier', 'payout_amount', 'created_at')
    list_filter = ('status', 'game_version', 'created_at')
    search_fields = ('user__username', 'user__email')

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
