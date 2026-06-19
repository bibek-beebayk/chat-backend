from decimal import Decimal
from django.conf import settings
from django.db import migrations, models
import django.db.models
import django.db.models.deletion


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='LoginStreak',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('current_streak', models.PositiveIntegerField(default=0)),
                ('last_login_date', models.DateField(blank=True, null=True)),
                ('receivable_bonus', models.DecimalField(decimal_places=2, default=Decimal('0.00'), max_digits=8)),
                ('last_awarded_at', models.DateTimeField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('user', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='login_streak', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ['-updated_at'],
            },
        ),
        migrations.CreateModel(
            name='LoginStreakEntry',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('login_date', models.DateField()),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='login_streak_entries', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'verbose_name': 'Login streak entry',
                'verbose_name_plural': 'Login streak entries',
                'ordering': ['-login_date', '-created_at'],
            },
        ),
        migrations.CreateModel(
            name='StreakRedemptionRequest',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('amount', models.DecimalField(decimal_places=2, default=Decimal('5.00'), max_digits=8)),
                ('status', models.CharField(choices=[('pending', 'Pending'), ('approved', 'Approved'), ('completed', 'Completed'), ('rejected', 'Rejected')], default='pending', max_length=16)),
                ('note', models.TextField(blank=True)),
                ('staff_note', models.TextField(blank=True)),
                ('reviewed_at', models.DateTimeField(blank=True, null=True)),
                ('completed_at', models.DateTimeField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('reviewed_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='reviewed_streak_redemptions', to=settings.AUTH_USER_MODEL)),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='streak_redemption_requests', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ['-created_at'],
            },
        ),
        migrations.AddConstraint(
            model_name='loginstreakentry',
            constraint=models.UniqueConstraint(fields=('user', 'login_date'), name='unique_login_streak_entry_per_day'),
        ),
        migrations.AddIndex(
            model_name='streakredemptionrequest',
            index=models.Index(fields=['status', 'created_at'], name='rewards_str_status_6c3b52_idx'),
        ),
        migrations.AddIndex(
            model_name='streakredemptionrequest',
            index=models.Index(fields=['user', 'status'], name='rewards_str_user_id_e3d441_idx'),
        ),
        migrations.AddConstraint(
            model_name='streakredemptionrequest',
            constraint=models.UniqueConstraint(condition=django.db.models.Q(('status__in', ['pending', 'approved'])), fields=('user',), name='unique_active_streak_redemption_per_user'),
        ),
    ]
