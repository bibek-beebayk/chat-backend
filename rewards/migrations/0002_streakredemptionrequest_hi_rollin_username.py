from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('rewards', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='streakredemptionrequest',
            name='hi_rollin_username',
            field=models.CharField(blank=True, max_length=100),
        ),
    ]
