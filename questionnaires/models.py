# ============================================================================
# FILE: questionnaires/models.py
# ============================================================================

from django.db import models
from accounts.models import TeacherProfile, Department, Subject
from django.contrib.auth.models import User
import os
from django.db import migrations

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
    
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    department = models.ForeignKey(Department, on_delete=models.CASCADE, related_name='questionnaires')
    subject = models.ForeignKey(Subject, on_delete=models.CASCADE, related_name='questionnaires')
    uploader = models.ForeignKey(TeacherProfile, on_delete=models.CASCADE, related_name='questionnaires')
    file = models.FileField(upload_to=questionnaire_upload_path)
    file_type = models.CharField(max_length=10, choices=FILE_TYPE_CHOICES)
    file_size = models.IntegerField(help_text='File size in bytes')
    uploaded_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    # AI Extraction fields
    is_extracted = models.BooleanField(default=False, help_text='Whether questions have been extracted')
    extraction_status = models.CharField(
        max_length=20,
        choices=[
            ('pending', 'Pending'),
            ('processing', 'Processing'),
            ('completed', 'Completed'),
            ('failed', 'Failed')
        ],
        default='pending'
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
    """Types of questions that can be extracted"""
    MULTIPLE_CHOICE = 'multiple_choice'
    TRUE_FALSE = 'true_false'
    IDENTIFICATION = 'identification'
    ESSAY = 'essay'
    FILL_BLANK = 'fill_blank'
    MATCHING = 'matching'
    
    TYPE_CHOICES = [
        (MULTIPLE_CHOICE, 'Multiple Choice'),
        (TRUE_FALSE, 'True/False'),
        (IDENTIFICATION, 'Identification'),
        (ESSAY, 'Essay'),
        (FILL_BLANK, 'Fill in the Blanks'),
        (MATCHING, 'Matching Type'),
    ]
    
    name = models.CharField(max_length=50, choices=TYPE_CHOICES, unique=True)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    
    def __str__(self):
        return self.get_name_display()
    
    class Meta:
        ordering = ['name']


class ExtractedQuestion(models.Model):
    """Questions extracted from uploaded questionnaire"""
    questionnaire = models.ForeignKey(
        Questionnaire, 
        on_delete=models.CASCADE, 
        related_name='extracted_questions'
    )
    question_type = models.ForeignKey(QuestionType, on_delete=models.PROTECT)
    question_text = models.TextField()
    
    # For multiple choice
    option_a = models.TextField(blank=True, null=True)
    option_b = models.TextField(blank=True, null=True)
    option_c = models.TextField(blank=True, null=True)
    option_d = models.TextField(blank=True, null=True)
    
    # For various question types
    correct_answer = models.TextField()
    explanation = models.TextField(blank=True, null=True)
    points = models.IntegerField(default=1)
    difficulty = models.CharField(
        max_length=20, 
        choices=[
            ('easy', 'Easy'),
            ('medium', 'Medium'),
            ('hard', 'Hard')
        ], 
        default='medium'
    )
    
    is_approved = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['created_at']
    
    def __str__(self):
        return f"{self.question_type} - {self.question_text[:50]}"
    
    @property
    def options_list(self):
        """Returns list of (letter, option) tuples for multiple choice"""
        return [
            ('a', self.option_a),
            ('b', self.option_b),
            ('c', self.option_c),
            ('d', self.option_d),
        ]


class GeneratedTest(models.Model):
    """Test generated from extracted questions"""
    questionnaire = models.ForeignKey(
        Questionnaire, 
        on_delete=models.CASCADE, 
        related_name='generated_tests'
    )
    teacher = models.ForeignKey(User, on_delete=models.CASCADE)
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    question_types = models.ManyToManyField(QuestionType)
    questions = models.ManyToManyField(ExtractedQuestion)
    
    total_points = models.IntegerField(default=0)
    time_limit = models.IntegerField(null=True, blank=True, help_text="Time limit in minutes")
    
    is_published = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['-created_at']
    
    def __str__(self):
        return self.title


class Download(models.Model):
    """Track questionnaire downloads"""
    questionnaire = models.ForeignKey(
        Questionnaire, 
        on_delete=models.CASCADE,
        related_name='downloads'
    )
    user = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='questionnaire_downloads'
    )
    downloaded_at = models.DateTimeField(auto_now_add=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    
    class Meta:
        ordering = ['-downloaded_at']
        verbose_name = 'Download'
        verbose_name_plural = 'Downloads'
    
    def __str__(self):
        return f"{self.questionnaire.title} - {self.downloaded_at.strftime('%Y-%m-%d %H:%M')}"


# ============================================================================
# WORKSPACE MODELS
# ============================================================================

class WorkspaceFolder(models.Model):
    """
    A named folder inside a teacher's workspace.
    Teachers must create a folder before they can save questions into it.
    """
    teacher    = models.ForeignKey(
        TeacherProfile,
        on_delete=models.CASCADE,
        related_name='workspace_folders'
    )
    name       = models.CharField(max_length=80)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name        = 'Workspace Folder'
        verbose_name_plural = 'Workspace Folders'

    def __str__(self):
        return f"{self.teacher.user.get_full_name()} — {self.name}"

    def question_count(self):
        return self.folder_questions.count()


class WorkspaceFolderQuestion(models.Model):
    """
    A question pinned inside a workspace folder.
    The unique_together constraint prevents the same question from being
    added to the same folder twice.
    """
    folder   = models.ForeignKey(
        WorkspaceFolder,
        on_delete=models.CASCADE,
        related_name='folder_questions'
    )
    question = models.ForeignKey(
        ExtractedQuestion,
        on_delete=models.CASCADE,
        related_name='workspace_entries'
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
# DATA MIGRATION HELPER  (keep as-is from original)
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