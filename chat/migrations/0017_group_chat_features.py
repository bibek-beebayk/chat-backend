from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
from django.db.models import Q


class Migration(migrations.Migration):

    dependencies = [
        ('chat', '0016_room_resolution_and_agent_tools'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name='message',
            name='is_broadcast',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='room',
            name='group_admin',
            field=models.ForeignKey(blank=True, limit_choices_to={'user_type': 'agent'}, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='managed_group_rooms', to=settings.AUTH_USER_MODEL),
        ),
        migrations.AddField(
            model_name='room',
            name='group_description',
            field=models.CharField(blank=True, max_length=240),
        ),
        migrations.AlterField(
            model_name='room',
            name='room_type',
            field=models.CharField(choices=[('support', 'Support'), ('direct_agent', 'Direct Agent'), ('group', 'Group')], default='support', max_length=20),
        ),
        migrations.CreateModel(
            name='GroupJoinRequest',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('status', models.CharField(choices=[('pending', 'Pending'), ('approved', 'Approved'), ('rejected', 'Rejected')], default='pending', max_length=10)),
                ('requested_at', models.DateTimeField(auto_now_add=True)),
                ('reviewed_at', models.DateTimeField(blank=True, null=True)),
                ('player', models.ForeignKey(limit_choices_to={'user_type': 'player'}, on_delete=django.db.models.deletion.CASCADE, related_name='group_join_requests', to=settings.AUTH_USER_MODEL)),
                ('reviewed_by', models.ForeignKey(blank=True, limit_choices_to={'user_type': 'agent'}, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='reviewed_group_join_requests', to=settings.AUTH_USER_MODEL)),
                ('room', models.ForeignKey(limit_choices_to={'room_type': 'group'}, on_delete=django.db.models.deletion.CASCADE, related_name='join_requests', to='chat.room')),
            ],
            options={
                'ordering': ['-requested_at'],
            },
        ),
        migrations.AddConstraint(
            model_name='groupjoinrequest',
            constraint=models.UniqueConstraint(condition=Q(status='pending'), fields=('room', 'player'), name='unique_pending_group_join_request'),
        ),
    ]
