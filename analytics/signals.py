from django.conf import settings
from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver

from analytics.models import ActivityEvent
from analytics.models import AnalyticsEvent
from analytics.services import track_event


def create_activity(actor, kind, action, target_title='', target_url='', metadata=None):
    ActivityEvent.objects.create(
        actor=actor,
        kind=kind,
        action=action,
        target_title=target_title or '',
        target_url=target_url or '',
        metadata=metadata or {},
    )


def get_redemption_activity_details(redemption):
    amount = f'${redemption.amount}'
    source = getattr(redemption, 'source', '')

    source_map = {
        'login_streak': {
            'label': 'Login Streak Credit',
            'action_label': 'login streak credit',
        },
        'scratch_bonus': {
            'label': 'Scratch Bonus',
            'action_label': 'scratch bonus',
        },
        'win_bonus': {
            'label': 'Win Bonus',
            'action_label': 'win bonus',
        },
    }
    details = source_map.get(source, {
        'label': redemption.get_source_display() if hasattr(redemption, 'get_source_display') else 'Bonus',
        'action_label': 'bonus',
    })

    return {
        'source': source,
        'label': details['label'],
        'action_label': details['action_label'],
        'target_title': f'{amount} {details["label"]}',
    }


@receiver(post_save, sender=settings.AUTH_USER_MODEL)
def record_user_joined(sender, instance, created, **kwargs):
    if created:
        create_activity(instance, ActivityEvent.KIND_ACCOUNT, 'joined the community')


@receiver(post_save, sender='posts.Post')
def record_post_created(sender, instance, created, **kwargs):
    if created and getattr(instance, 'is_active', True):
        create_activity(
            instance.author,
            ActivityEvent.KIND_POST,
            'shared a post',
            target_title=instance.title or 'Community post',
            target_url=f'/posts/{instance.id}',
            metadata={'post_id': instance.id},
        )


@receiver(post_save, sender='posts.PostComment')
def record_post_comment_created(sender, instance, created, **kwargs):
    if created and getattr(instance, 'is_active', True):
        create_activity(
            instance.author,
            ActivityEvent.KIND_COMMENT,
            'commented on a post',
            target_title=instance.post.title or 'Community post',
            target_url=f'/posts/{instance.post_id}',
            metadata={'post_id': instance.post_id, 'comment_id': instance.id},
        )


@receiver(post_save, sender='events.EventRegistration')
def record_event_registration(sender, instance, created, **kwargs):
    if created:
        create_activity(
            instance.user,
            ActivityEvent.KIND_EVENT,
            f'joined {instance.event.title}',
            target_title=instance.event.title,
            target_url=f'/events/{instance.event_id}',
            metadata={'event_id': instance.event_id},
        )
        track_event(
            user=instance.user,
            event_type=AnalyticsEvent.EVENT_EVENT_REGISTRATION,
            event_name='event_registration',
            path=f'/events/{instance.event_id}',
            metadata={'event_id': instance.event_id, 'event_title': instance.event.title},
        )


@receiver(pre_save, sender='rewards.StreakRedemptionRequest')
def cache_redemption_previous_status(sender, instance, **kwargs):
    if not instance.pk:
        instance._previous_status = None
        return

    previous = sender.objects.filter(pk=instance.pk).values('status').first()
    instance._previous_status = previous['status'] if previous else None


@receiver(post_save, sender='rewards.StreakRedemptionRequest')
def record_streak_redemption_request(sender, instance, created, **kwargs):
    details = get_redemption_activity_details(instance)
    if created:
        track_event(
            user=instance.user,
            event_type=AnalyticsEvent.EVENT_REDEMPTION,
            event_name='redemption_requested',
            path='/settings',
            source=details['source'],
            metadata={
                'redemption_request_id': instance.id,
                'amount': str(instance.amount),
                'source': details['source'],
                'status': instance.status,
            },
        )
        create_activity(
            instance.user,
            ActivityEvent.KIND_REWARD,
            f'requested a {details["action_label"]} redemption',
            target_title=details['target_title'],
            target_url='/settings',
            metadata={
                'redemption_request_id': instance.id,
                'amount': str(instance.amount),
                'source': details['source'],
                'status': instance.status,
            },
        )
        return

    previous_status = getattr(instance, '_previous_status', None)
    if previous_status != instance.status and instance.status == 'approved':
        track_event(
            user=instance.user,
            event_type=AnalyticsEvent.EVENT_REDEMPTION,
            event_name='redemption_approved',
            path='/settings',
            source=details['source'],
            metadata={
                'redemption_request_id': instance.id,
                'amount': str(instance.amount),
                'source': details['source'],
                'status': instance.status,
            },
        )
        create_activity(
            instance.user,
            ActivityEvent.KIND_REWARD,
            f'had a {details["action_label"]} redemption accepted',
            target_title=details['target_title'],
            target_url='/settings',
            metadata={
                'redemption_request_id': instance.id,
                'amount': str(instance.amount),
                'source': details['source'],
                'status': instance.status,
            },
        )
