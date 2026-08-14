from django.contrib import admin
from .models import SlotRound


@admin.register(SlotRound)
class SlotRoundAdmin(admin.ModelAdmin):
    list_display = ('user', 'game_version', 'wager_amount', 'total_multiplier', 'payout_amount', 'balance_after', 'created_at')
    list_filter = ('game_version', 'created_at')
    search_fields = ('user__username', 'user__email')

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
