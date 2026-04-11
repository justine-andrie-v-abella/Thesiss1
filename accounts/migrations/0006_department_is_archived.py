from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0005_alter_subject_code'),
    ]

    operations = [
        migrations.AddField(
            model_name='department',
            name='is_archived',
            field=models.BooleanField(default=False),
        ),
    ]
