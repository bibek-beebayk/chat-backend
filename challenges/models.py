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
