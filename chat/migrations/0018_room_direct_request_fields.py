from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('chat', '0017_group_chat_features'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name='room',
            name='direct_request_initiator',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='initiated_direct_requests',
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name='room',
            name='direct_request_status',
            field=models.CharField(
                choices=[
                    ('accepted', 'Accepted'),
                    ('pending', 'Pending'),
                    ('rejected', 'Rejected'),
                ],
                default='accepted',
                max_length=10,
            ),
        ),
    ]

