# questionnaires/models.py
from django.db import models
from accounts.models import TeacherProfile, Department, Subject
import os

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
        
class Download(models.Model):
    """Track questionnaire downloads"""
    questionnaire = models.ForeignKey(
        Questionnaire, 
        on_delete=models.CASCADE,
        related_name='downloads'
    )
    user = models.ForeignKey(
        'auth.User',
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