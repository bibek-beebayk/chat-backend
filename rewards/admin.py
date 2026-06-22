from django.contrib import admin
from .models import LoginStreak, LoginStreakEntry, ScratchRedemption, ScratchRewardClaim, StreakRedemptionRequest


@admin.register(LoginStreak)
class LoginStreakAdmin(admin.ModelAdmin):
    list_display = ('user', 'current_streak', 'last_login_date', 'receivable_bonus', 'last_awarded_at', 'updated_at')
    search_fields = ('user__username', 'user__email')
    readonly_fields = ('created_at', 'updated_at')


@admin.register(LoginStreakEntry)
class LoginStreakEntryAdmin(admin.ModelAdmin):
    list_display = ('user', 'login_date', 'created_at')
    list_filter = ('login_date',)
    search_fields = ('user__username', 'user__email')


@admin.register(StreakRedemptionRequest)
class StreakRedemptionRequestAdmin(admin.ModelAdmin):
    list_display = ('user', 'source', 'amount', 'status', 'reviewed_by', 'reviewed_at', 'completed_at', 'created_at')
    list_filter = ('source', 'status', 'created_at', 'reviewed_at')
    search_fields = ('user__username', 'user__email', 'note', 'staff_note')
    readonly_fields = ('created_at', 'updated_at')


@admin.register(ScratchRedemption)
class ScratchRedemptionAdmin(admin.ModelAdmin):
    list_display = ('user', 'source', 'amount', 'confirmed_at')
    list_filter = ('source', 'confirmed_at')
    search_fields = ('user__username', 'user__email', 'source')
    readonly_fields = ('confirmed_at',)


@admin.register(ScratchRewardClaim)
class ScratchRewardClaimAdmin(admin.ModelAdmin):
    list_display = ('reward_id', 'user', 'source', 'amount', 'expires_at', 'claimed_at')
    list_filter = ('source', 'claimed_at', 'expires_at')
    search_fields = ('reward_id', 'user__username', 'user__email')
    readonly_fields = ('claimed_at',)
