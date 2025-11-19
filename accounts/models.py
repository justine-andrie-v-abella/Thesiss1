# ============================================================================
# FILE: accounts/models.py
# ============================================================================

from django.db import models
from django.contrib.auth.models import User

class Department(models.Model):
    name = models.CharField(max_length=200, unique=True)
    code = models.CharField(max_length=20, unique=True)
    description = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['name']
    
    def __str__(self):
        return f"{self.code} - {self.name}"

class Subject(models.Model):
    departments = models.ManyToManyField(Department, related_name='subjects')
    name = models.CharField(max_length=200)
    code = models.CharField(max_length=20, unique=True)
    description = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['code']
    
    def __str__(self):
        return f"{self.code} - {self.name}"
    
    def get_departments_display(self):
        return ", ".join([dept.code for dept in self.departments.all()])

class TeacherProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='teacher_profile')
    department = models.ForeignKey(Department, on_delete=models.SET_NULL, null=True, related_name='teachers')
    employee_id = models.CharField(max_length=50, unique=True)
    phone = models.CharField(max_length=20, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    def __str__(self):
        return f"{self.user.get_full_name()} - {self.employee_id}"

class ActivityLog(models.Model):
    ACTIVITY_TYPES = [
        ('teacher_created', 'Teacher Created'),
        ('teacher_updated', 'Teacher Updated'),
        ('teacher_deleted', 'Teacher Deleted'),
        ('department_created', 'Department Created'),
        ('department_updated', 'Department Updated'),
        ('department_deleted', 'Department Deleted'),
        ('subject_created', 'Subject Created'),
        ('subject_updated', 'Subject Updated'),
        ('subject_deleted', 'Subject Deleted'),
        ('questionnaire_uploaded', 'Questionnaire Uploaded'),
        ('user_login', 'User Login'),
        ('system', 'System Activity'),
    ]
    
    activity_type = models.CharField(max_length=50, choices=ACTIVITY_TYPES)
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='activities')
    description = models.TextField()
    metadata = models.JSONField(default=dict, blank=True)  # For storing additional data
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['activity_type', 'created_at']),
            models.Index(fields=['is_read', 'created_at']),
        ]
    
    def __str__(self):
        return f"{self.get_activity_type_display()} - {self.description}"
    
    def get_icon(self):
        """Get Bootstrap icon for activity type"""
        icons = {
            'teacher_created': 'bi-person-plus',
            'teacher_updated': 'bi-person-check',
            'teacher_deleted': 'bi-person-x',
            'department_created': 'bi-building-add',
            'department_updated': 'bi-building',
            'department_deleted': 'bi-building-x',
            'subject_created': 'bi-journal-plus',
            'subject_updated': 'bi-journal',
            'subject_deleted': 'bi-journal-x',
            'questionnaire_uploaded': 'bi-upload',
            'user_login': 'bi-box-arrow-in-right',
            'system': 'bi-shield-check',
        }
        return icons.get(self.activity_type, 'bi-info-circle')
    
    def get_color(self):
        """Get color class for activity type"""
        colors = {
            'teacher_created': 'success',
            'teacher_updated': 'primary',
            'teacher_deleted': 'danger',
            'department_created': 'info',
            'department_updated': 'info',
            'department_deleted': 'danger',
            'subject_created': 'warning',
            'subject_updated': 'warning',
            'subject_deleted': 'danger',
            'questionnaire_uploaded': 'primary',
            'user_login': 'dark',
            'system': 'secondary',
        }
        return colors.get(self.activity_type, 'secondary')
    
    @classmethod
    def create_activity(cls, activity_type, description, user=None, metadata=None):
        """Helper method to create activities"""
        return cls.objects.create(
            activity_type=activity_type,
            user=user,
            description=description,
            metadata=metadata or {}
        )