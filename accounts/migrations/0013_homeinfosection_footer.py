from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0012_homeinfopoint_refactor'),
    ]

    operations = [
        migrations.AddField(
            model_name='homeinfosection',
            name='footer',
            field=models.CharField(blank=True, max_length=320),
        ),
    ]
