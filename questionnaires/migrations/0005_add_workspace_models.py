# ============================================================================
# FILE: questionnaires/migrations/XXXX_add_workspace_models.py
# Rename to match your next migration number, e.g. 0005_add_workspace_models.py
# ============================================================================

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        # Replace with your actual last migration
        ('questionnaires', '0004_populate_question_types'),
        ('accounts', '0001_initial'),  # or whichever migration added TeacherProfile
    ]

    operations = [
        migrations.CreateModel(
            name='WorkspaceFolder',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=80)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('teacher', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='workspace_folders',
                    to='accounts.teacherprofile',
                )),
            ],
            options={
                'verbose_name': 'Workspace Folder',
                'verbose_name_plural': 'Workspace Folders',
                'ordering': ['-created_at'],
            },
        ),
        migrations.CreateModel(
            name='WorkspaceFolderQuestion',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('added_at', models.DateTimeField(auto_now_add=True)),
                ('folder', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='folder_questions',
                    to='questionnaires.workspacefolder',
                )),
                ('question', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='workspace_entries',
                    to='questionnaires.extractedquestion',
                )),
            ],
            options={
                'verbose_name': 'Workspace Folder Question',
                'verbose_name_plural': 'Workspace Folder Questions',
                'ordering': ['added_at'],
                'unique_together': {('folder', 'question')},
            },
        ),
    ]