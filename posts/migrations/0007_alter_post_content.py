from django.db import migrations
import ckeditor_uploader.fields


class Migration(migrations.Migration):

    dependencies = [
        ('posts', '0006_post_is_pinned'),
    ]

    operations = [
        migrations.AlterField(
            model_name='post',
            name='content',
            field=ckeditor_uploader.fields.RichTextUploadingField(blank=True),
        ),
    ]
