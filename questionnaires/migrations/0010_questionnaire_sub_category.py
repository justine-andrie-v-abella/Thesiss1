from django.db import migrations, models


# ---------------------------------------------------------------------------
# Data migration: map old exam_type values to the new two-term scheme
# ---------------------------------------------------------------------------
OLD_TO_NEW = {
    # old value       -> (new exam_type,  sub_category)
    'prelim':         ('midterm',    'prelim'),
    'midterm':        ('midterm',    ''),
    'semi_final':     ('final_term', 'semi_final'),
    'final':          ('final_term', ''),
    'final_term':     ('final_term', ''),   # already correct
    'others':         ('midterm',    ''),
}


def migrate_exam_types(apps, schema_editor):
    Questionnaire = apps.get_model('questionnaires', 'Questionnaire')
    for q in Questionnaire.objects.all():
        mapping = OLD_TO_NEW.get(q.exam_type)
        if mapping:
            q.exam_type, q.sub_category = mapping
            q.save(update_fields=['exam_type', 'sub_category'])


def reverse_migrate(apps, schema_editor):
    # Best-effort reverse: reconstruct old value from (term, sub_category)
    Questionnaire = apps.get_model('questionnaires', 'Questionnaire')
    for q in Questionnaire.objects.all():
        if q.sub_category == 'prelim':
            q.exam_type = 'prelim'
        elif q.sub_category == 'semi_final':
            q.exam_type = 'semi_final'
        elif q.exam_type == 'final_term':
            q.exam_type = 'final'
        q.save(update_fields=['exam_type'])


class Migration(migrations.Migration):

    dependencies = [
        ('questionnaires', '0009_add_school_year_semester'),
    ]

    operations = [
        # 1. Add the sub_category column (nullable so existing rows are fine)
        migrations.AddField(
            model_name='questionnaire',
            name='sub_category',
            field=models.CharField(
                blank=True,
                choices=[
                    ('short_quiz', 'Short Quiz'),
                    ('long_quiz',  'Long Quiz'),
                    ('prelim',     'Prelim'),
                    ('semi_final', 'Semi-Final'),
                ],
                default='',
                help_text='Sub-category within the term (e.g. Short Quiz, Prelim)',
                max_length=20,
            ),
        ),

        # 2. Migrate old exam_type values to the new two-term scheme
        migrations.RunPython(migrate_exam_types, reverse_migrate),

        # 3. Update exam_type choices + default
        migrations.AlterField(
            model_name='questionnaire',
            name='exam_type',
            field=models.CharField(
                choices=[
                    ('midterm',    'Midterm'),
                    ('final_term', 'Final Term'),
                ],
                default='midterm',
                help_text='Academic term this questionnaire is intended for',
                max_length=20,
            ),
        ),
    ]
