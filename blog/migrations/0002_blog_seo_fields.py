from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('blog', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='blog',
            name='meta_description',
            field=models.CharField(blank=True, max_length=320),
        ),
        migrations.AddField(
            model_name='blog',
            name='meta_title',
            field=models.CharField(blank=True, max_length=220),
        ),
        migrations.AddField(
            model_name='blog',
            name='og_image',
            field=models.ImageField(blank=True, null=True, upload_to='blog_og/'),
        ),
    ]

