from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('posts', '0003_post_link'),
    ]

    operations = [
        migrations.AddField(
            model_name='post',
            name='visibility',
            field=models.CharField(
                choices=[('all', 'All Users'), ('player', 'Players/Agents'), ('staff', 'Staff/Admin')],
                default='all',
                help_text='Who can view this post.',
                max_length=10,
            ),
        ),
    ]
