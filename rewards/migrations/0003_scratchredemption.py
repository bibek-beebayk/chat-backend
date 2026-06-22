from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('rewards', '0002_streakredemptionrequest_hi_rollin_username'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='ScratchRedemption',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('source', models.CharField(max_length=120)),
                ('amount', models.DecimalField(decimal_places=2, max_digits=10)),
                ('query_params', models.JSONField(blank=True, default=dict)),
                ('confirmed_at', models.DateTimeField(auto_now_add=True)),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='scratch_redemptions', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ['-confirmed_at'],
            },
        ),
        migrations.AddIndex(
            model_name='scratchredemption',
            index=models.Index(fields=['source', 'confirmed_at'], name='rewards_scr_source_3ecca5_idx'),
        ),
        migrations.AddIndex(
            model_name='scratchredemption',
            index=models.Index(fields=['user', 'confirmed_at'], name='rewards_scr_user_id_9b9a90_idx'),
        ),
    ]
