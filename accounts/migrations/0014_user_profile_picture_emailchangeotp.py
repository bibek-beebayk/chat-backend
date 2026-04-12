from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0013_homeinfosection_footer'),
    ]

    operations = [
        migrations.AddField(
            model_name='user',
            name='profile_picture',
            field=models.ImageField(blank=True, help_text='Optional user profile picture', null=True, upload_to='profile_pictures/'),
        ),
        migrations.CreateModel(
            name='EmailChangeOTP',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('new_email', models.EmailField(max_length=254)),
                ('otp_code', models.CharField(max_length=6)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('expires_at', models.DateTimeField()),
                ('is_used', models.BooleanField(default=False)),
                ('attempts', models.IntegerField(default=0)),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='email_change_otps', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'verbose_name': 'Email Change OTP',
                'verbose_name_plural': 'Email Change OTPs',
                'ordering': ['-created_at'],
            },
        ),
    ]
