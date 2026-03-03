from django.db import migrations, models
import django.db.models.deletion


def migrate_section_points(apps, schema_editor):
    HomeInfoSection = apps.get_model('accounts', 'HomeInfoSection')
    HomeInfoPoint = apps.get_model('accounts', 'HomeInfoPoint')

    for section in HomeInfoSection.objects.all():
        points = [
            (section.point_1 or '').strip(),
            (section.point_2 or '').strip(),
            (section.point_3 or '').strip(),
        ]
        order = 0
        for text in points:
            if not text:
                continue
            HomeInfoPoint.objects.create(
                section=section,
                icon='info_outline',
                content=text,
                sort_order=order,
            )
            order += 1


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0011_homeinfosection'),
    ]

    operations = [
        migrations.CreateModel(
            name='HomeInfoPoint',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('icon', models.CharField(default='info_outline', help_text='Material icon name, e.g. verified_user_outlined', max_length=80)),
                ('content', models.CharField(max_length=240)),
                ('sort_order', models.PositiveIntegerField(default=0)),
                ('section', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='points', to='accounts.homeinfosection')),
            ],
            options={
                'verbose_name': 'Home Info Point',
                'verbose_name_plural': 'Home Info Points',
                'ordering': ['sort_order', 'id'],
            },
        ),
        migrations.RunPython(migrate_section_points, migrations.RunPython.noop),
        migrations.RemoveField(
            model_name='homeinfosection',
            name='point_1',
        ),
        migrations.RemoveField(
            model_name='homeinfosection',
            name='point_2',
        ),
        migrations.RemoveField(
            model_name='homeinfosection',
            name='point_3',
        ),
    ]
