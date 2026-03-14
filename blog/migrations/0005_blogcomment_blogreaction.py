from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('blog', '0004_alter_blog_content'),
    ]

    operations = [
        migrations.CreateModel(
            name='BlogComment',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('visitor_hash', models.CharField(db_index=True, max_length=64)),
                ('display_name', models.CharField(default='Guest', max_length=80)),
                ('content', models.TextField()),
                ('is_hidden', models.BooleanField(default=False)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('blog', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='comments', to='blog.blog')),
            ],
            options={
                'ordering': ['-created_at'],
            },
        ),
        migrations.CreateModel(
            name='BlogReaction',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('visitor_hash', models.CharField(db_index=True, max_length=64)),
                ('reaction_type', models.CharField(choices=[('like', 'Like')], default='like', max_length=16)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('blog', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='reactions', to='blog.blog')),
            ],
        ),
        migrations.AddConstraint(
            model_name='blogreaction',
            constraint=models.UniqueConstraint(fields=('blog', 'visitor_hash'), name='unique_blog_reaction_per_visitor'),
        ),
    ]
