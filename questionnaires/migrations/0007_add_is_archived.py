from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('questionnaires', '0006_questionnaire_exam_type'),
    ]

    operations = [
        migrations.AddField(
            model_name='questionnaire',
            name='is_archived',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='workspacefolder',
            name='is_archived',
            field=models.BooleanField(default=False),
        ),
    ]
