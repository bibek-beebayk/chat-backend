from django.contrib import admin
from .models import PlinkoRound


@admin.register(PlinkoRound)
class PlinkoRoundAdmin(admin.ModelAdmin):
    list_display = ('user', 'rows', 'risk_level', 'wager_amount', 'slot_index', 'multiplier', 'payout_amount', 'balance_after', 'created_at')
    list_filter = ('rows', 'risk_level', 'created_at')
    search_fields = ('user__username', 'user__email')

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
