# ============================================================================
# FILE: questionnaires/models.py  —  FIXED VERSION
# ============================================================================

from django.db import models
from accounts.models import TeacherProfile, Department, Subject
from django.contrib.auth.models import User
import os
from django.db import migrations
import json as _json


def questionnaire_upload_path(instance, filename):
    return f'questionnaires/{instance.department.code}/{instance.subject.code}/{filename}'

class Questionnaire(models.Model):
    FILE_TYPE_CHOICES = [
        ('pdf', 'PDF'),
        ('docx', 'Word Document'),
        ('xlsx', 'Excel Spreadsheet'),
        ('xls', 'Excel Spreadsheet (Legacy)'),
        ('txt', 'Text File'),
    ]

    EXAM_TYPE_CHOICES = [
        ('short_quiz', 'Short Quiz'),
        ('long_quiz',  'Long Quiz'),
        ('prelim',     'Prelim Exam'),
        ('midterm',    'Midterm Exam'),
        ('prefinal',   'Pre-Final Exam'),
        ('final',      'Final Exam'),
        ('activity',   'Activity / Seatwork'),
        ('others',     'Others'),
    ]

    title       = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    department  = models.ForeignKey(Department,      on_delete=models.CASCADE, related_name='questionnaires')
    subject     = models.ForeignKey(Subject,         on_delete=models.CASCADE, related_name='questionnaires')
    uploader    = models.ForeignKey(TeacherProfile,  on_delete=models.CASCADE, related_name='questionnaires')
    file        = models.FileField(upload_to=questionnaire_upload_path)
    file_type   = models.CharField(max_length=10, choices=FILE_TYPE_CHOICES)
    file_size   = models.IntegerField(help_text='File size in bytes')
    uploaded_at = models.DateTimeField(auto_now_add=True)
    updated_at  = models.DateTimeField(auto_now=True)

    exam_type = models.CharField(
        max_length=20,
        choices=EXAM_TYPE_CHOICES,
        default='others',
        help_text='Type of exam or test this questionnaire is intended for',
    )

    is_extracted      = models.BooleanField(default=False, help_text='Whether questions have been extracted')
    extraction_status = models.CharField(
        max_length=20,
        choices=[
            ('pending',    'Pending'),
            ('processing', 'Processing'),
            ('completed',  'Completed'),
            ('failed',     'Failed'),
        ],
        default='pending',
    )
    extraction_error = models.TextField(blank=True, null=True)

    class Meta:
        ordering = ['-uploaded_at']

    def __str__(self):
        return f"{self.title} - {self.subject.code}"

    def get_file_extension(self):
        return os.path.splitext(self.file.name)[1][1:].lower()

    def get_file_size_display(self):
        size = self.file_size
        for unit in ['B', 'KB', 'MB', 'GB']:
            if size < 1024.0:
                return f"{size:.2f} {unit}"
            size /= 1024.0
        return f"{size:.2f} TB"

    def save(self, *args, **kwargs):
        if self.file:
            self.file_size = self.file.size
            self.file_type = self.get_file_extension()
        super().save(*args, **kwargs)


class QuestionType(models.Model):
    MULTIPLE_CHOICE = 'multiple_choice'
    TRUE_FALSE       = 'true_false'
    IDENTIFICATION   = 'identification'
    ESSAY            = 'essay'
    FILL_BLANK       = 'fill_blank'
    MATCHING         = 'matching'

    TYPE_CHOICES = [
        (MULTIPLE_CHOICE, 'Multiple Choice'),
        (TRUE_FALSE,       'True/False'),
        (IDENTIFICATION,   'Identification'),
        (ESSAY,            'Essay'),
        (FILL_BLANK,       'Fill in the Blanks'),
        (MATCHING,         'Matching Type'),
    ]

    name        = models.CharField(max_length=50, choices=TYPE_CHOICES, unique=True)
    description = models.TextField(blank=True)
    is_active   = models.BooleanField(default=True)

    def __str__(self):
        return self.get_name_display()

    class Meta:
        ordering = ['name']


class ExtractedQuestion(models.Model):
    questionnaire = models.ForeignKey(
        Questionnaire,
        on_delete=models.CASCADE,
        related_name='extracted_questions',
    )
    question_type = models.ForeignKey(QuestionType, on_delete=models.PROTECT)
    question_text = models.TextField()

    # For multiple choice: plain text (option A, B, C, D)
    # For matching type:
    #   option_a → JSON list: Column A items  e.g. ["1. CREATE", "2. DROP", ...]
    #   option_b → JSON list: Column B items  e.g. ["A. Deletes object", ...]
    #   option_c → JSON list: pairs           e.g. [{"item": "1. CREATE", "match": "B"}, ...]
    #   option_d → unused
    option_a = models.TextField(blank=True, null=True)
    option_b = models.TextField(blank=True, null=True)
    option_c = models.TextField(blank=True, null=True)
    option_d = models.TextField(blank=True, null=True)

    correct_answer = models.TextField()
    explanation    = models.TextField(blank=True, null=True)
    points         = models.IntegerField(default=1)
    difficulty     = models.CharField(
        max_length=20,
        choices=[
            ('easy',   'Easy'),
            ('medium', 'Medium'),
            ('hard',   'Hard'),
        ],
        default='medium',
    )

    is_approved = models.BooleanField(default=False)
    created_at  = models.DateTimeField(auto_now_add=True)
    updated_at  = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['created_at']

    def __str__(self):
        return f"{self.question_type} - {self.question_text[:50]}"

    # ── Type checks ───────────────────────────────────────────────────────────

    @property
    def is_matching(self):
        return self.question_type.name == 'matching'

    @property
    def is_multiple_choice(self):
        return self.question_type.name == 'multiple_choice'

    # ── Multiple choice ───────────────────────────────────────────────────────

    @property
    def options_list(self):
        pairs = [
            ('a', self.option_a),
            ('b', self.option_b),
            ('c', self.option_c),
            ('d', self.option_d),
        ]
        return [(letter, text) for letter, text in pairs if text]

    # ── Matching type ─────────────────────────────────────────────────────────
    # ▼▼▼ FIX: this method was accidentally at module-level (0 indent).
    #          It must be indented 4 spaces to live inside the class. ▼▼▼

    def get_matching_data(self):
        """
        Parses JSON stored in option_a / option_b / option_c.

        option_a → JSON list: Column A items  ["1. CREATE", "2. TINYINT", ...]
        option_b → JSON list: Column B items  ["A. Deletes...", "B. Creates...", ...]
        option_c → JSON list: pairs           [{"item": "1. CREATE", "match": "B"}, ...]

        Returns dict or None.
        """
        if not self.is_matching:
            return None

        import logging
        logger = logging.getLogger(__name__)
        logger.debug(
            "get_matching_data id=%s option_a=%r option_b=%r option_c=%r",
            self.pk, self.option_a, self.option_b, self.option_c,
        )

        if not self.option_a or not self.option_b:
            logger.warning(
                "Matching question id=%s has empty option_a or option_b",
                self.pk,
            )
            return None

        try:
            column_a = _json.loads(self.option_a)
            column_b = _json.loads(self.option_b)
            pairs    = _json.loads(self.option_c) if self.option_c else []

            if not column_a or not column_b:
                logger.warning(
                    "Matching question id=%s parsed OK but column_a or column_b is empty.",
                    self.pk,
                )
                return None

            pairs_by_item = {
                p['item']: p['match']
                for p in pairs
                if isinstance(p, dict) and 'item' in p and 'match' in p
            }

            return {
                'column_a':      column_a,
                'column_b':      column_b,
                'pairs':         pairs,
                'pairs_by_item': pairs_by_item,
            }

        except (ValueError, TypeError, KeyError) as exc:
            logger.error(
                "get_matching_data id=%s failed to parse JSON: %s",
                self.pk, exc,
            )
            return None

    def set_matching_data(self, column_a: list, column_b: list, pairs: list):
        """
        Convenience method for saving matching data to the option fields.
        """
        self.option_a = _json.dumps(column_a, ensure_ascii=False)
        self.option_b = _json.dumps(column_b, ensure_ascii=False)
        self.option_c = _json.dumps(pairs,    ensure_ascii=False)
        self.option_d = None

        if not self.correct_answer and pairs:
            self.correct_answer = ', '.join(
                f"{p['item'].split('.')[0].strip()}-{p['match']}"
                for p in pairs
                if isinstance(p, dict) and 'item' in p and 'match' in p
            )


class GeneratedTest(models.Model):
    questionnaire  = models.ForeignKey(
        Questionnaire,
        on_delete=models.CASCADE,
        related_name='generated_tests',
    )
    teacher        = models.ForeignKey(User, on_delete=models.CASCADE)
    title          = models.CharField(max_length=200)
    description    = models.TextField(blank=True)
    question_types = models.ManyToManyField(QuestionType)
    questions      = models.ManyToManyField(ExtractedQuestion)

    total_points = models.IntegerField(default=0)
    time_limit   = models.IntegerField(null=True, blank=True, help_text="Time limit in minutes")

    is_published = models.BooleanField(default=False)
    created_at   = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return self.title


class Download(models.Model):
    questionnaire = models.ForeignKey(
        Questionnaire,
        on_delete=models.CASCADE,
        related_name='downloads',
    )
    user = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='questionnaire_downloads',
    )
    downloaded_at = models.DateTimeField(auto_now_add=True)
    ip_address    = models.GenericIPAddressField(null=True, blank=True)

    class Meta:
        ordering     = ['-downloaded_at']
        verbose_name = 'Download'
        verbose_name_plural = 'Downloads'

    def __str__(self):
        return f"{self.questionnaire.title} - {self.downloaded_at.strftime('%Y-%m-%d %H:%M')}"


# ============================================================================
# WORKSPACE MODELS
# ============================================================================

class WorkspaceFolder(models.Model):
    teacher    = models.ForeignKey(
        TeacherProfile,
        on_delete=models.CASCADE,
        related_name='workspace_folders',
    )
    name       = models.CharField(max_length=80)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering            = ['-created_at']
        verbose_name        = 'Workspace Folder'
        verbose_name_plural = 'Workspace Folders'

    def __str__(self):
        return f"{self.teacher.user.get_full_name()} — {self.name}"

    def question_count(self):
        return self.folder_questions.count()


class WorkspaceFolderQuestion(models.Model):
    folder   = models.ForeignKey(
        WorkspaceFolder,
        on_delete=models.CASCADE,
        related_name='folder_questions',
    )
    question = models.ForeignKey(
        ExtractedQuestion,
        on_delete=models.CASCADE,
        related_name='workspace_entries',
    )
    added_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering            = ['added_at']
        unique_together     = ('folder', 'question')
        verbose_name        = 'Workspace Folder Question'
        verbose_name_plural = 'Workspace Folder Questions'

    def __str__(self):
        return f"{self.folder.name} → Q#{self.question.pk}"


# ============================================================================
# DATA MIGRATION HELPER
# ============================================================================

def populate_question_types(apps, schema_editor):
    QuestionType = apps.get_model('questionnaires', 'QuestionType')
    question_types = [
        'multiple_choice',
        'true_false',
        'essay',
        'short_answer',
        'fill_in_the_blank',
        'matching',
        'enumeration',
    ]
    for qt in question_types:
        QuestionType.objects.get_or_create(name=qt)

def reverse_question_types(apps, schema_editor):
    QuestionType = apps.get_model('questionnaires', 'QuestionType')
    QuestionType.objects.all().delete()

class Migration(migrations.Migration):

    dependencies = [
        ('questionnaires', '0003_questiontype_questionnaire_extraction_error_and_more'),
    ]

    operations = [
        migrations.RunPython(populate_question_types, reverse_question_types),
    ]