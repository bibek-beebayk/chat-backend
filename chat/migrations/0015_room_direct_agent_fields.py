from django.db import migrations, models
import django.db.models.deletion
from django.db.models import Q
from django.conf import settings


class Migration(migrations.Migration):

    dependencies = [
        ('chat', '0014_message_reply_to'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name='room',
            name='room_type',
            field=models.CharField(
                choices=[('support', 'Support'), ('direct_agent', 'Direct Agent')],
                default='support',
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name='room',
            name='direct_agent',
            field=models.ForeignKey(
                blank=True,
                limit_choices_to={'user_type': 'agent'},
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name='direct_player_rooms',
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name='room',
            name='direct_player',
            field=models.ForeignKey(
                blank=True,
                limit_choices_to={'user_type': 'player'},
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name='direct_agent_rooms',
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddConstraint(
            model_name='room',
            constraint=models.UniqueConstraint(
                condition=Q(room_type='direct_agent'),
                fields=('direct_player', 'direct_agent'),
                name='unique_player_agent_direct_room',
            ),
        ),
    ]
