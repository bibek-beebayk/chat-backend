from django import forms
from django.contrib import admin, messages
from django.contrib.admin import helpers
from django.contrib.admin.widgets import AutocompleteSelect
from django.contrib.auth import get_user_model
from django.shortcuts import render
from django.template.response import TemplateResponse
from .models import (
    PointAction,
    PointsAdjustment,
    PointsBalance,
    PointsLedgerEntry,
    PointsRedemptionConfig,
    PointsRedemptionRequest,
)
from .services import InsufficientPoints, apply_adjustment


class BulkPointsAdjustmentForm(forms.Form):
    points_delta = forms.IntegerField(help_text='Positive to award points, negative to deduct. Applied identically to every selected user.')
    note = forms.CharField(widget=forms.Textarea, required=False)

    def clean_points_delta(self):
        value = self.cleaned_data['points_delta']
        if value == 0:
            raise forms.ValidationError('Enter a non-zero amount.')
        return value


@admin.register(PointAction)
class PointActionAdmin(admin.ModelAdmin):
    list_display = ('slug', 'label', 'points_value', 'is_active', 'max_awards_per_day', 'updated_at')
    list_filter = ('is_active',)
    search_fields = ('slug', 'label')


@admin.register(PointsBalance)
class PointsBalanceAdmin(admin.ModelAdmin):
    """
    Also where bulk points adjustment lives - not a separate page, but a
    standard admin action on this list, which is what gets multi-select,
    "select all N matching your search across every page", and the search
    box itself (search_fields below) entirely from Django's own changelist
    machinery rather than any custom selection UI. Search by username or
    email, tick the players you want (or the header checkbox, then "Select
    all N" for everyone matching the search), then choose "Award / deduct
    points for selected users" from the Action dropdown.
    """
    list_display = ('user', 'balance', 'lifetime_earned', 'updated_at')
    search_fields = ('user__username', 'user__email')
    readonly_fields = ('balance', 'lifetime_earned', 'created_at', 'updated_at')
    actions = ['bulk_adjust_points']

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def get_queryset(self, request):
        """
        A PointsBalance row is created lazily - the first time a player's
        points are ever touched, via get_or_create() inside award_points/
        debit_balance/apply_adjustment/settle_wager - so a player who has
        never had a single points event (never played, registered before
        the registration bonus existed, etc.) has no row at all and simply
        never appears in PointsBalance.objects.all(). That's the actual
        cause of "not all players show up here": this list only ever
        showed players who happened to already have a row, not every
        player.

        Backfilling any missing rows here, on every changelist load, makes
        "every player is visible and selectable" durable rather than a
        one-time data fix: a brand-new player who hasn't earned anything
        yet still shows up here (at a real 0.00 balance) the moment staff
        opens this page, not only after their first points event - and,
        just as important, it's what makes them selectable at all for the
        bulk "Award / deduct points" action above, which operates on this
        same PointsBalance queryset.
        """
        User = get_user_model()
        missing = User.objects.filter(user_type='player', points_balance__isnull=True)
        if missing.exists():
            PointsBalance.objects.bulk_create(
                [PointsBalance(user=user) for user in missing],
                ignore_conflicts=True,
            )
        return super().get_queryset(request)

    @admin.action(description='Award / deduct points for selected users')
    def bulk_adjust_points(self, request, queryset):
        """
        Two-step action, mirroring Django's own built-in delete_selected
        exactly (see django.contrib.admin.actions and its confirmation
        template): the first submit (the Action dropdown "Go") lands here
        with no 'apply' marker, so it renders an intermediate form instead
        of doing anything; that form re-posts the same selected users (as
        explicit hidden `_selected_action` inputs - resolved fresh by
        Django's action machinery either way, whether the staff member
        checked individual boxes or used "Select all N matching your
        search") back to this exact action, this time with 'apply' set, so
        the second call actually applies it.

        Each user is adjusted independently (not one large transaction) -
        apply_adjustment() is already atomic per call, and one user's
        balance being too low to take a negative adjustment must not block
        every other selected user's adjustment from going through.
        """
        if request.POST.get('apply'):
            form = BulkPointsAdjustmentForm(request.POST)
            if form.is_valid():
                points_delta = form.cleaned_data['points_delta']
                note = form.cleaned_data['note']
                succeeded, skipped = [], []
                for balance in queryset.select_related('user'):
                    try:
                        apply_adjustment(balance.user, request.user, points_delta, note=note)
                    except InsufficientPoints:
                        skipped.append(balance.user.username)
                    else:
                        succeeded.append(balance.user.username)

                if succeeded:
                    verb = 'Awarded' if points_delta > 0 else 'Deducted'
                    self.message_user(
                        request,
                        f'{verb} {abs(points_delta)} points for {len(succeeded)} user(s).',
                        level=messages.SUCCESS,
                    )
                if skipped:
                    preview = ', '.join(skipped[:15]) + ('…' if len(skipped) > 15 else '')
                    self.message_user(
                        request,
                        f'Skipped {len(skipped)} user(s) - this deduction would take their balance below zero: {preview}',
                        level=messages.WARNING,
                    )
                return None  # falls through to the changelist, same as delete_selected
        else:
            form = BulkPointsAdjustmentForm()

        context = {
            **self.admin_site.each_context(request),
            'title': 'Award / Deduct Points',
            'subtitle': None,
            'queryset': queryset,
            'user_count': queryset.count(),
            'opts': self.model._meta,
            'action_checkbox_name': helpers.ACTION_CHECKBOX_NAME,
            'form': form,
        }
        return TemplateResponse(request, 'admin/points/bulk_points_adjustment.html', context)


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
    """
    `user` used to be a plain CharField requiring the exact, already-known
    username - unfindable and easy to typo, and gave no way to see who
    exists. This is Django admin's own searchable autocomplete widget
    instead: start typing a few characters of a username or email and
    every matching player appears, live, via AJAX - not just someone
    already memorized.

    The AJAX search itself is served by UserAdmin's search_fields
    (accounts/admin.py) and isn't restricted to players by the widget - the
    `queryset` below is what actually enforces "must be a player": a staff
    account may briefly appear while typing (the search endpoint doesn't
    know this form's intent), but selecting one is rejected on submit with
    a normal "select a valid choice" error, since it falls outside this
    field's queryset.

    Reuses PointsBalance's real `user` field (rather than declaring a new
    one anywhere) purely so the widget has a genuine model field to
    introspect for the app/model/field it needs to build its AJAX request -
    no schema or admin-registration change required for this to work.
    """
    user = forms.ModelChoiceField(
        queryset=get_user_model().objects.filter(user_type='player'),
        label='Player',
        widget=AutocompleteSelect(PointsBalance._meta.get_field('user'), admin.site),
    )
    points_delta = forms.IntegerField(help_text='Positive to award points, negative to deduct.')
    note = forms.CharField(widget=forms.Textarea, required=False)


def points_adjustment_view(request):
    context = {
        **admin.site.each_context(request),
        'title': 'Award / Deduct Points',
    }
    form = PointsAdjustmentForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        target_user = form.cleaned_data['user']
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
