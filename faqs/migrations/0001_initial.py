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
            name='FAQ',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('question', models.CharField(max_length=260)),
                ('answer', ckeditor_uploader.fields.RichTextUploadingField()),
                ('category', models.CharField(choices=[('account', 'Account'), ('community', 'Community'), ('rewards', 'Rewards'), ('events', 'Events'), ('security', 'Security'), ('technical', 'Technical')], default='account', max_length=24)),
                ('audience', models.CharField(choices=[('all', 'All Members'), ('players', 'Players'), ('agents', 'Agents'), ('staff', 'Staff')], default='all', max_length=16)),
                ('sort_order', models.PositiveIntegerField(default=0)),
                ('is_featured', models.BooleanField(default=False)),
                ('is_published', models.BooleanField(default=True)),
                ('published_at', models.DateTimeField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('created_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='created_faqs', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'verbose_name': 'FAQ',
                'verbose_name_plural': 'FAQs',
                'ordering': ['sort_order', '-is_featured', '-published_at', 'question'],
            },
        ),
        migrations.AddIndex(
            model_name='faq',
            index=models.Index(fields=['is_published', 'audience', 'category'], name='faqs_faq_is_publ_f25432_idx'),
        ),
        migrations.AddIndex(
            model_name='faq',
            index=models.Index(fields=['sort_order', 'category'], name='faqs_faq_sort_or_86687b_idx'),
        ),
    ]
