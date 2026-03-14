from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import ckeditor.fields


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='Blog',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('title', models.CharField(max_length=220)),
                ('slug', models.SlugField(blank=True, max_length=260, unique=True)),
                ('excerpt', models.CharField(blank=True, max_length=320)),
                ('content', ckeditor.fields.RichTextField(blank=True)),
                ('cover_image', models.ImageField(blank=True, null=True, upload_to='blog_covers/')),
                ('is_published', models.BooleanField(default=True)),
                ('published_at', models.DateTimeField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('author', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='blog_posts', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ['-published_at', '-created_at'],
            },
        ),
    ]

