from django import forms
from django.contrib import admin
from django.contrib.auth import get_user_model
from django.shortcuts import render
from .models import (
    PointAction,
    PointsAdjustment,
    PointsBalance,
    PointsLedgerEntry,
    PointsRedemptionConfig,
    PointsRedemptionRequest,
)
from .services import InsufficientPoints, apply_adjustment


@admin.register(PointAction)
class PointActionAdmin(admin.ModelAdmin):
    list_display = ('slug', 'label', 'points_value', 'is_active', 'max_awards_per_day', 'updated_at')
    list_filter = ('is_active',)
    search_fields = ('slug', 'label')


@admin.register(PointsBalance)
class PointsBalanceAdmin(admin.ModelAdmin):
    list_display = ('user', 'balance', 'lifetime_earned', 'updated_at')
    search_fields = ('user__username', 'user__email')
    readonly_fields = ('balance', 'lifetime_earned', 'created_at', 'updated_at')

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(PointsLedgerEntry)
class PointsLedgerEntryAdmin(admin.ModelAdmin):
    list_display = ('user', 'entry_type', 'delta', 'balance_after', 'action', 'created_at')
    list_filter = ('entry_type', 'created_at')
    search_fields = ('user__username', 'user__email', 'idempotency_key', 'note')

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(PointsRedemptionConfig)
class PointsRedemptionConfigAdmin(admin.ModelAdmin):
    list_display = ('min_redemption_points', 'rp_to_credit_rate', 'updated_by', 'updated_at')
    readonly_fields = ('updated_at',)

    def has_add_permission(self, request):
        # Singleton - block adding a second row once one exists.
        return not PointsRedemptionConfig.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False

    def save_model(self, request, obj, form, change):
        obj.updated_by = request.user
        super().save_model(request, obj, form, change)


@admin.register(PointsRedemptionRequest)
class PointsRedemptionRequestAdmin(admin.ModelAdmin):
    list_display = ('user', 'points_amount', 'status', 'reviewed_by', 'reviewed_at', 'completed_at', 'created_at')
    list_filter = ('status', 'created_at', 'reviewed_at')
    search_fields = ('user__username', 'user__email', 'note', 'staff_note')
    readonly_fields = ('created_at', 'updated_at')


class PointsAdjustmentForm(forms.Form):
    username = forms.CharField(help_text='Exact username of the player to adjust.')
    points_delta = forms.IntegerField(help_text='Positive to award points, negative to deduct.')
    note = forms.CharField(widget=forms.Textarea, required=False)


def points_adjustment_view(request):
    context = {
        **admin.site.each_context(request),
        'title': 'Award / Deduct Points',
    }
    form = PointsAdjustmentForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        try:
            target_user = get_user_model().objects.get(username=form.cleaned_data['username'])
        except get_user_model().DoesNotExist:
            form.add_error('username', 'No user found with that username.')
        else:
            try:
                balance, entry = apply_adjustment(
                    target_user,
                    request.user,
                    form.cleaned_data['points_delta'],
                    note=form.cleaned_data.get('note', ''),
                )
            except InsufficientPoints:
                form.add_error('points_delta', 'This would take the balance below zero.')
            except ValueError as exc:
                form.add_error('points_delta', str(exc))
            else:
                verb = 'Awarded' if entry.delta > 0 else 'Deducted'
                context['success'] = f'{verb} {abs(entry.delta)} points for {target_user.username}. New balance: {balance.balance}.'
                form = PointsAdjustmentForm()
    context['form'] = form
    return render(request, 'admin/points/points_adjustment.html', context)


@admin.register(PointsAdjustment)
class PointsAdjustmentAdmin(admin.ModelAdmin):
    def changelist_view(self, request, extra_context=None):
        return points_adjustment_view(request)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
