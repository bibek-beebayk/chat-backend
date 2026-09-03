from django.db import migrations, models

import xp.models


# The ladder that used to live hardcoded in xp/ranks.py + xp/services.py
# (RANK_UP_BONUS_RP) + xp/views.py (RANK_TIER_TAGLINES). Seeded once here;
# from now on it is edited in Django admin. Badge art is uploaded per tier.
SEED_TIERS = [
    {'slug': 'bronze', 'name': 'Bronze', 'min_xp': 0, 'rank_up_bonus_rp': 0, 'tagline': 'Best for new players'},
    {'slug': 'silver', 'name': 'Silver', 'min_xp': 1000, 'rank_up_bonus_rp': 100, 'tagline': 'For active players'},
    {'slug': 'gold', 'name': 'Gold', 'min_xp': 2500, 'rank_up_bonus_rp': 250, 'tagline': 'For established players'},
    {'slug': 'platinum', 'name': 'Platinum', 'min_xp': 5000, 'rank_up_bonus_rp': 500, 'tagline': 'For loyal players'},
    {'slug': 'diamond', 'name': 'Diamond', 'min_xp': 9000, 'rank_up_bonus_rp': 750, 'tagline': 'High-status community tier'},
    {'slug': 'rollin_elite', 'name': 'Rollin Elite', 'min_xp': 15000, 'rank_up_bonus_rp': 1000, 'tagline': 'Top community tier'},
    {'slug': 'rollin_legend', 'name': 'Rollin Legend', 'min_xp': 25000, 'rank_up_bonus_rp': 1500, 'tagline': "You've reached the highest rank"},
]


def seed_tiers(apps, schema_editor):
    Tier = apps.get_model('xp', 'Tier')
    for row in SEED_TIERS:
        Tier.objects.get_or_create(slug=row['slug'], defaults=row)


def unseed_tiers(apps, schema_editor):
    Tier = apps.get_model('xp', 'Tier')
    Tier.objects.filter(slug__in=[r['slug'] for r in SEED_TIERS]).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('xp', '0004_gameplay_round_counter'),
    ]

    operations = [
        migrations.CreateModel(
            name='Tier',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('slug', models.SlugField(max_length=32, unique=True)),
                ('name', models.CharField(max_length=60)),
                ('min_xp', models.PositiveIntegerField(help_text='Inclusive XP needed to reach this tier. Exactly one tier must be 0.', unique=True)),
                ('rank_up_bonus_rp', models.PositiveIntegerField(default=0, help_text='One-time RP credited the first time a player reaches this tier. 0 = no bonus (e.g. the starting tier).')),
                ('tagline', models.CharField(blank=True, max_length=120)),
                ('badge', models.ImageField(blank=True, null=True, upload_to=xp.models.tier_badge_upload_to)),
                ('is_active', models.BooleanField(default=True, help_text='Inactive tiers are excluded from the ladder and all rank math.')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
            options={
                'ordering': ['min_xp'],
            },
        ),
        migrations.RunPython(seed_tiers, unseed_tiers),
    ]
