from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('rewards', '0004_streakredemptionrequest_source_payload'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='ScratchRewardClaim',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('reward_id', models.CharField(max_length=160, unique=True)),
                ('source', models.CharField(max_length=120)),
                ('amount', models.DecimalField(decimal_places=2, max_digits=10)),
                ('expires_at', models.DateTimeField()),
                ('signature', models.CharField(max_length=256)),
                ('source_payload', models.JSONField(blank=True, default=dict)),
                ('claimed_at', models.DateTimeField(auto_now_add=True)),
                ('redemption_request', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='scratch_reward_claim', to='rewards.streakredemptionrequest')),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='scratch_reward_claims', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ['-claimed_at'],
            },
        ),
        migrations.AddIndex(
            model_name='scratchrewardclaim',
            index=models.Index(fields=['source', 'claimed_at'], name='rewards_scr_source_58d3f8_idx'),
        ),
        migrations.AddIndex(
            model_name='scratchrewardclaim',
            index=models.Index(fields=['user', 'claimed_at'], name='rewards_scr_user_id_fca999_idx'),
        ),
        migrations.AddIndex(
            model_name='scratchrewardclaim',
            index=models.Index(fields=['expires_at'], name='rewards_scr_expires_cfbca5_idx'),
        ),
    ]
