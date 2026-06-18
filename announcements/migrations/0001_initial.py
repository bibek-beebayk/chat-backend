from django.conf import settings
from django.db import migrations, models
import ckeditor_uploader.fields
import django.db.models.deletion


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='Announcement',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('title', models.CharField(max_length=220)),
                ('summary', models.CharField(blank=True, max_length=360)),
                ('content', ckeditor_uploader.fields.RichTextUploadingField(blank=True)),
                ('cover_image', models.ImageField(blank=True, null=True, upload_to='announcement_covers/')),
                ('category', models.CharField(choices=[('general', 'General'), ('event', 'Event'), ('reward', 'Reward'), ('maintenance', 'Maintenance'), ('security', 'Security'), ('vip', 'VIP')], default='general', max_length=24)),
                ('audience', models.CharField(choices=[('all', 'All Members'), ('players', 'Players'), ('agents', 'Agents'), ('staff', 'Staff')], default='all', max_length=16)),
                ('priority', models.CharField(choices=[('normal', 'Normal'), ('important', 'Important'), ('urgent', 'Urgent')], default='normal', max_length=16)),
                ('is_pinned', models.BooleanField(default=False)),
                ('is_published', models.BooleanField(default=True)),
                ('published_at', models.DateTimeField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('created_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='created_announcements', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ['-is_pinned', '-published_at', '-created_at'],
            },
        ),
        migrations.AddIndex(
            model_name='announcement',
            index=models.Index(fields=['is_published', 'audience', 'published_at'], name='announcemen_is_publ_bc1462_idx'),
        ),
        migrations.AddIndex(
            model_name='announcement',
            index=models.Index(fields=['is_pinned', 'published_at'], name='announcemen_is_pinn_278360_idx'),
        ),
    ]
