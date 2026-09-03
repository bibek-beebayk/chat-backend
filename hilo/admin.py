from django.contrib import admin
from .models import HiLoRound, HiLoStep


class HiLoStepInline(admin.TabularInline):
    model = HiLoStep
    extra = 0
    can_delete = False
    fields = ('step_index', 'from_rank', 'prediction', 'to_rank', 'outcome', 'step_multiplier', 'multiplier_after')
    readonly_fields = fields

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(HiLoRound)
class HiLoRoundAdmin(admin.ModelAdmin):
    list_display = ('user', 'status', 'wager_amount', 'multiplier', 'streak', 'steps_taken', 'payout_amount', 'capped', 'created_at')
    list_filter = ('status', 'capped', 'game_version', 'created_at')
    search_fields = ('user__username', 'user__email')
    inlines = [HiLoStepInline]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
