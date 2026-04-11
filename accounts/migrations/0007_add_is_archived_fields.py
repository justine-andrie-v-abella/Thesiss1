from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0006_department_is_archived'),
    ]

    operations = [
        migrations.AddField(
            model_name='teacherprofile',
            name='is_archived',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='subadminprofile',
            name='is_archived',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='subject',
            name='is_archived',
            field=models.BooleanField(default=False),
        ),
    ]
