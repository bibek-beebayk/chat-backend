from django.contrib import admin
from django.utils.html import format_html
from .models import Tier, XPAction, XPBalance, XPLedgerEntry


@admin.register(Tier)
class TierAdmin(admin.ModelAdmin):
    list_display = ('name', 'slug', 'min_xp', 'rank_up_bonus_rp', 'is_active', 'badge_preview', 'updated_at')
    list_editable = ('min_xp', 'rank_up_bonus_rp', 'is_active')
    ordering = ('min_xp',)
    prepopulated_fields = {'slug': ('name',)}
    readonly_fields = ('badge_preview', 'created_at', 'updated_at')
    fields = ('name', 'slug', 'min_xp', 'rank_up_bonus_rp', 'tagline', 'badge', 'badge_preview', 'is_active', 'created_at', 'updated_at')

    @admin.display(description='Badge')
    def badge_preview(self, obj):
        if obj.badge:
            return format_html('<img src="{}" style="height:48px;width:48px;object-fit:contain;" />', obj.badge.url)
        return '—'


@admin.register(XPAction)
class XPActionAdmin(admin.ModelAdmin):
    list_display = ('slug', 'label', 'xp_value', 'is_active', 'max_awards_per_day', 'challenge_target_count', 'updated_at')
    list_filter = ('is_active',)
    search_fields = ('slug', 'label')


@admin.register(XPBalance)
class XPBalanceAdmin(admin.ModelAdmin):
    list_display = ('user', 'total_xp', 'rank_slug', 'rank_updated_at', 'updated_at')
    list_filter = ('rank_slug',)
    search_fields = ('user__username', 'user__email')
    readonly_fields = ('total_xp', 'rank_slug', 'rank_updated_at', 'created_at', 'updated_at')

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(XPLedgerEntry)
class XPLedgerEntryAdmin(admin.ModelAdmin):
    list_display = ('user', 'entry_type', 'delta', 'xp_after', 'rank_after', 'action', 'created_at')
    list_filter = ('entry_type', 'created_at')
    search_fields = ('user__username', 'user__email', 'idempotency_key', 'note')

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
