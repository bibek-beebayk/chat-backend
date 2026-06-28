from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('faqs', '0001_initial'),
    ]

    operations = [
        migrations.AlterField(
            model_name='faq',
            name='category',
            field=models.CharField(
                choices=[
                    ('general', 'General'),
                    ('account', 'Account'),
                    ('community', 'Community'),
                    ('rewards', 'Rewards'),
                    ('events', 'Events'),
                    ('security', 'Security'),
                    ('technical', 'Technical'),
                ],
                default='general',
                max_length=24,
            ),
        ),
    ]
