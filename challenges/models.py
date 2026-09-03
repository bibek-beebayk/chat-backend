"""
Proxy models over xp.XPAction, one per challenge period, so Django admin
can give Daily/Weekly/Special Challenges their own dedicated, pre-filtered
"Challenges" sidebar section instead of one long, undifferentiated XPAction
list. A proxy model adds no table and no migration-visible schema change -
it's the same XPAction rows, just a different Python-level view onto them
(a scoped default manager) with its own ModelAdmin. See challenges/admin.py
for the actual add/edit UI this exists to support.

"Challenge" here means an XPAction with a target set (challenge_target_count
is not None) - the same definition xp/views.py::daily_progress_view uses to
distinguish a real challenge from a plain checklist item like daily_login,
or a background counter like gameplay_round. Those still only appear in the
general XP Actions admin (xp/admin.py), not here.
"""

from django.conf import settings
from django.db import models

from xp.models import XPAction


class DailyChallengeManager(models.Manager):
    def get_queryset(self):
        return super().get_queryset().filter(
            challenge_period=XPAction.PERIOD_DAILY,
            challenge_target_count__isnull=False,
        )


class WeeklyChallengeManager(models.Manager):
    def get_queryset(self):
        return super().get_queryset().filter(
            challenge_period=XPAction.PERIOD_WEEKLY,
            challenge_target_count__isnull=False,
        )


class SpecialChallengeManager(models.Manager):
    def get_queryset(self):
        return super().get_queryset().filter(
            challenge_period=XPAction.PERIOD_EVENT,
            challenge_target_count__isnull=False,
        )


class DailyChallenge(XPAction):
    objects = DailyChallengeManager()

    class Meta:
        proxy = True
        app_label = 'challenges'
        verbose_name = 'Daily Challenge'
        verbose_name_plural = 'Daily Challenges'


class WeeklyChallenge(XPAction):
    objects = WeeklyChallengeManager()

    class Meta:
        proxy = True
        app_label = 'challenges'
        verbose_name = 'Weekly Challenge'
        verbose_name_plural = 'Weekly Challenges'


class SpecialChallenge(XPAction):
    objects = SpecialChallengeManager()

    class Meta:
        proxy = True
        app_label = 'challenges'
        verbose_name = 'Special Challenge'
        verbose_name_plural = 'Special Challenges'


class RotationConfig(models.Model):
    """
    Singleton (always pk=1), admin-editable - mirrors
    points.models.PointsRedemptionConfig's exact pattern. The two knobs for
    challenge rotation: how many of the rotation-pool Daily Challenges, and
    separately how many of the rotation-pool Weekly Challenges (XPAction
    rows with rotation_pool=True - see xp/models.py's field and
    current_rotation_pool_ids()), are actually live at once. A challenge
    NOT in a pool (rotation_pool=False, the default) is entirely
    unaffected by this and shows every period, exactly as before this
    feature existed - rotation is opt-in per challenge, not a global
    behavior change. Event challenges have no rotation knob here - each
    runs exactly once and never repeats, so "rotation" has no meaning for
    them.
    """
    daily_active_count = models.PositiveSmallIntegerField(
        default=3,
        help_text=(
            'How many rotation-pool Daily Challenges are live each day. '
            '0 hides the whole pool. A count at or above the pool size '
            'shows the entire pool every day (no rotation effect).'
        ),
    )
    weekly_active_count = models.PositiveSmallIntegerField(
        default=1,
        help_text=(
            'How many rotation-pool Weekly Challenges are live each week. '
            '0 hides the whole pool. A count at or above the pool size '
            'shows the entire pool every week (no rotation effect).'
        ),
    )
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )

    class Meta:
        verbose_name = 'Rotation Settings'
        verbose_name_plural = 'Rotation Settings'

    def __str__(self):
        return f'Rotation: {self.daily_active_count}/day, {self.weekly_active_count}/week'

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        pass

    @classmethod
    def get_solo(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj
