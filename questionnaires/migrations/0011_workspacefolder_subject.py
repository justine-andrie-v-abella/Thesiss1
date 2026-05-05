from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('accounts',         '0001_initial'),
        ('questionnaires',   '0010_questionnaire_sub_category'),
    ]

    operations = [
        migrations.AddField(
            model_name='workspacefolder',
            name='subject',
            field=models.ForeignKey(
                blank=True,
                help_text='Subject this folder is locked to — only questions from this subject can be added',
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='workspace_folders',
                to='accounts.subject',
            ),
        ),
    ]
