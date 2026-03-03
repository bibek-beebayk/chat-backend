from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0010_user_is_test_user'),
    ]

    operations = [
        migrations.CreateModel(
            name='HomeInfoSection',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('user_type', models.CharField(choices=[('player', 'Player'), ('agent', 'Agent')], help_text='Which user type should see this section.', max_length=10, unique=True)),
                ('title', models.CharField(max_length=120)),
                ('subtitle', models.CharField(blank=True, max_length=240)),
                ('point_1', models.CharField(max_length=240)),
                ('point_2', models.CharField(blank=True, max_length=240)),
                ('point_3', models.CharField(blank=True, max_length=240)),
                ('is_active', models.BooleanField(default=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
            options={
                'verbose_name': 'Home Info Section',
                'verbose_name_plural': 'Home Info Sections',
                'ordering': ['user_type'],
            },
        ),
    ]
