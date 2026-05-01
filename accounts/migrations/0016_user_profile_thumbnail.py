from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0015_user_agent_availability_and_note'),
    ]

    operations = [
        migrations.AddField(
            model_name='user',
            name='profile_thumbnail',
            field=models.ImageField(
                blank=True,
                help_text='Low-size generated thumbnail for profile previews',
                null=True,
                upload_to='profile_pictures/thumbs/',
            ),
        ),
    ]

