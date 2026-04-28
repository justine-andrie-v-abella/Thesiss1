from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0008_add_program_model'),
    ]

    operations = [
        migrations.AddField(
            model_name='teacherprofile',
            name='subjects',
            field=models.ManyToManyField(blank=True, related_name='assigned_teachers', to='accounts.subject'),
        ),
    ]
