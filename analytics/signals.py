from django.conf import settings
from django.db.models.signals import post_save
from django.dispatch import receiver

from analytics.models import ActivityEvent


def create_activity(actor, kind, action, target_title='', target_url='', metadata=None):
    ActivityEvent.objects.create(
        actor=actor,
        kind=kind,
        action=action,
        target_title=target_title or '',
        target_url=target_url or '',
        metadata=metadata or {},
    )


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


@receiver(post_save, sender='rewards.StreakRedemptionRequest')
def record_streak_redemption_request(sender, instance, created, **kwargs):
    if created:
        create_activity(
            instance.user,
            ActivityEvent.KIND_REWARD,
            'requested a streak credit redemption',
            target_title='$5 Hi-Rollin credit',
            target_url='/settings',
            metadata={'redemption_request_id': instance.id, 'amount': str(instance.amount)},
        )
