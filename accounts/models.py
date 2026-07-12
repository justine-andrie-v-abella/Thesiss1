# ============================================================================
# FILE: accounts/models.py
# ============================================================================

from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone


class Department(models.Model):
    name = models.CharField(max_length=200, unique=True)
    code = models.CharField(max_length=20, unique=True)
    description = models.TextField(blank=True)
    is_archived = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return f"{self.code} - {self.name}"


class Subject(models.Model):
    departments = models.ManyToManyField(Department, related_name='subjects')
    name = models.CharField(max_length=200)
    code = models.CharField(max_length=20)
    description = models.TextField(blank=True)
    is_archived = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['code']

    def __str__(self):
        return f"{self.code} - {self.name}"

    def save(self, *args, **kwargs):
        self.code = self.code.upper()  # always uppercase at DB level
        super().save(*args, **kwargs)

    def get_departments_display(self):
        return ", ".join([dept.code for dept in self.departments.all()])

class SchoolYear(models.Model):
    """
    Represents an academic school year (e.g. 2024-2025).
    Only one record can be marked is_current=True at a time.
    When a new school year is set as current, subject assignments reset
    (but old assignments are preserved as read-only history).
    """
    name = models.CharField(
        max_length=20, unique=True,
        help_text='e.g. 2024-2025'
    )
    start_date = models.DateField(null=True, blank=True)
    end_date   = models.DateField(null=True, blank=True)
    is_current = models.BooleanField(
        default=False,
        help_text='Only one school year should be current at a time.'
    )
    created_at = models.DateTimeField(auto_now_add=True)
 
    class Meta:
        ordering = ['-name']
 
    def __str__(self):
        return self.name
 
    def save(self, *args, **kwargs):
        # Enforce: only one current school year
        if self.is_current:
            SchoolYear.objects.exclude(pk=self.pk).filter(is_current=True).update(is_current=False)
        super().save(*args, **kwargs)
 
    # AFTER
    @classmethod
    def get_current(cls):
        """Return the current school year, or None if not set or if it has expired."""
        from django.utils import timezone
        sy = cls.objects.filter(is_current=True).first()
        if sy and sy.end_date and sy.end_date < timezone.now().date():
            return None
        return sy
    
class Semester(models.Model):
    """
    A half of a SchoolYear. Admins create these manually (they know exact
    start/end dates). Exactly one Semester system-wide can be is_current=True;
    activating a semester also marks its parent SchoolYear as current.
    """
    SEMESTER_CHOICES = [(1, 'Semester 1'), (2, 'Semester 2')]

    school_year = models.ForeignKey(
        'SchoolYear', on_delete=models.CASCADE, related_name='semesters'
    )
    number = models.PositiveSmallIntegerField(choices=SEMESTER_CHOICES)
    is_current = models.BooleanField(
        default=False,
        help_text='Only one semester system-wide should be current at a time.'
    )
    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [['school_year', 'number']]
        ordering = ['school_year__name', 'number']

    def __str__(self):
        return f"{self.school_year.name} — Semester {self.number}"

    def save(self, *args, **kwargs):
        if self.is_current:
            # Enforce single current semester system-wide
            Semester.objects.exclude(pk=self.pk).filter(is_current=True).update(is_current=False)
        super().save(*args, **kwargs)
        if self.is_current:
            # Keep SchoolYear.is_current in sync with whichever year owns the current semester
            SchoolYear.objects.exclude(pk=self.school_year_id).filter(is_current=True).update(is_current=False)
            SchoolYear.objects.filter(pk=self.school_year_id).update(is_current=True)

    @classmethod
    def get_current(cls):
        """Return the current semester, or None if not set or if it has expired."""
        sem = cls.objects.select_related('school_year').filter(is_current=True).first()
        if sem and sem.end_date and sem.end_date < timezone.now().date():
            return None
        return sem

class TeacherProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='teacher_profile')
    department = models.ForeignKey(Department, on_delete=models.SET_NULL, null=True, related_name='teachers')
    subjects = models.ManyToManyField(Subject, blank=True, related_name='assigned_teachers')
    employee_id = models.CharField(max_length=50, unique=True)
    phone = models.CharField(max_length=20, blank=True)
    is_active = models.BooleanField(default=True)
    is_archived = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.user.get_full_name()} - {self.employee_id}"

class TeacherSubjectAssignment(models.Model):
    """
    TRANSITIONAL VERSION — step 1 of the semester migration.
    Keeps school_year so existing rows/queries still work, adds a nullable
    semester FK that step 2's data migration will populate.
    """
    teacher = models.ForeignKey(
        'TeacherProfile', on_delete=models.CASCADE, related_name='subject_assignments'
    )
    subject = models.ForeignKey(
        'Subject', on_delete=models.CASCADE, related_name='teacher_assignments'
    )
    school_year = models.ForeignKey(
        'SchoolYear', on_delete=models.CASCADE, related_name='assignments'
    )
    semester = models.ForeignKey(
        'Semester', on_delete=models.CASCADE, related_name='assignments'
    )
    assigned_by = models.ForeignKey(
        'auth.User', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='teacher_subject_assignments_made'
    )
    assigned_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [['teacher', 'subject', 'semester']]
        ordering = ['semester__school_year__name', 'semester__number', 'subject__code']

    def __str__(self):
        return (
            f"{self.teacher.user.get_full_name()} — "
            f"{self.subject.code} ({self.school_year.name})"
        )

    @property
    def school_year(self):
        """Back-compat shim — some old code/templates may still read .school_year"""
        return self.semester.school_year

# ============================================================================
# NEW: SubAdminProfile
# One sub-admin per department enforced by OneToOneField on department.
# The sub-admin user is a regular Django User (is_staff=False, is_superuser=False).
# Role is determined by the existence of this profile.
# ============================================================================
class SubAdminProfile(models.Model):
    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name='subadmin_profile'
    )
    # OneToOneField enforces 1 sub-admin per department at the DB level
    department = models.OneToOneField(
        Department,
        on_delete=models.CASCADE,
        related_name='subadmin',
        null=True,
        blank=True
    )
    is_active = models.BooleanField(default=True)
    is_archived = models.BooleanField(default=False)
    assigned_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='assigned_subadmins'
    )
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        dept_name = self.department.name if self.department else "Unassigned"
        return f"SubAdmin: {self.user.get_full_name()} — {dept_name}"


class Program(models.Model):
    name        = models.CharField(max_length=255)
    code        = models.CharField(max_length=20)
    description = models.TextField(blank=True)
    department  = models.ForeignKey(Department, on_delete=models.CASCADE, related_name='programs')
    subjects    = models.ManyToManyField('Subject', blank=True, related_name='programs')
    is_active   = models.BooleanField(default=True)
    is_archived = models.BooleanField(default=False)
    created_at  = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering      = ['name']
        unique_together = [['code', 'department']]

    def __str__(self):
        return f"{self.code} - {self.name}"

    def save(self, *args, **kwargs):
        self.code = self.code.upper()
        super().save(*args, **kwargs)

class Curriculum(models.Model):
    """
    A versioned curriculum for a program.
    Each time the curriculum changes, a new Curriculum is created.
    Old curricula are preserved (students enrolled under them keep their version).
    Only one curriculum per program can be 'active' at a time.
    """
    program     = models.ForeignKey(
        Program, on_delete=models.CASCADE, related_name='curricula'
    )
    code        = models.CharField(
        max_length=50,
        help_text='e.g. CUR-001, BSCS-2024. Must be unique within the program.'
    )
    school_year = models.CharField(
        max_length=20,
        help_text='e.g. 2024-2025'
    )
    description = models.TextField(blank=True)
    is_active   = models.BooleanField(
        default=False,
        help_text='Only one curriculum per program should be active at a time.'
    )
    is_draft    = models.BooleanField(
        default=True,
        help_text='Draft = still being edited. Saved = finalized (but editable until replaced).'
    )
    created_by  = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='created_curricula'
    )
    created_at  = models.DateTimeField(auto_now_add=True)
    saved_at    = models.DateTimeField(null=True, blank=True)
 
    class Meta:
        ordering        = ['-created_at']
        unique_together = [['program', 'code']]
        verbose_name        = 'Curriculum'
        verbose_name_plural = 'Curricula'
 
    def __str__(self):
        status = 'Active' if self.is_active else ('Draft' if self.is_draft else 'Archived')
        return f"{self.program.code} › {self.code} ({self.school_year}) [{status}]"
 
    def save(self, *args, **kwargs):
        self.code = self.code.upper()
        super().save(*args, **kwargs)
 
    def activate(self):
        """Set this curriculum as active, deactivate all others for this program."""
        Curriculum.objects.filter(program=self.program, is_active=True).update(is_active=False)
        self.is_active = True
        self.is_draft  = False
        self.saved_at  = timezone.now()
        self.save()

class ProgramCurriculum(models.Model):
    YEAR_CHOICES = [
        (1, '1st Year'),
        (2, '2nd Year'),
        (3, '3rd Year'),
        (4, '4th Year'),
    ]
    SEMESTER_CHOICES = [
        (1, '1st Semester'),
        (2, '2nd Semester'),
    ]
 
    # NEW: link to a specific curriculum version (nullable so old rows survive migration)
    curriculum = models.ForeignKey(
        'Curriculum',
        on_delete=models.CASCADE,
        related_name='entries',
        null=True,
        blank=True,
    )
    program    = models.ForeignKey(Program,  on_delete=models.CASCADE, related_name='curriculum_entries')
    subject    = models.ForeignKey('Subject', on_delete=models.CASCADE, related_name='curriculum_entries')
    year_level = models.IntegerField(choices=YEAR_CHOICES)
    semester   = models.IntegerField(choices=SEMESTER_CHOICES)
    created_at = models.DateTimeField(auto_now_add=True)
 
    class Meta:
        ordering        = ['year_level', 'semester', 'subject__code']
        # OLD unique_together was ['program', 'subject'] — one subject per program ever.
        # NEW: a subject can appear in different curricula for the same program,
        #       but only once per curriculum.
        unique_together = [['curriculum', 'subject']]
        verbose_name        = 'Program Curriculum Entry'
        verbose_name_plural = 'Program Curriculum Entries'
 
    def __str__(self):
        cur_code = self.curriculum.code if self.curriculum else 'legacy'
        return (
            f"{self.program.code} › {cur_code} › "
            f"Year {self.year_level} Sem {self.semester} › "
            f"{self.subject.code}"
        )


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
        ('program_created', 'Program Created'),
        ('program_updated', 'Program Updated'),
        ('program_deleted', 'Program Deleted'),
        ('questionnaire_uploaded', 'Questionnaire Uploaded'),
        ('user_login', 'User Login'),
        ('system', 'System Activity'),
        ('subadmin_created', 'Sub-Admin Created'),
        ('subadmin_updated', 'Sub-Admin Updated'),
        ('subadmin_deleted', 'Sub-Admin Deleted'),
    ]

    activity_type = models.CharField(max_length=50, choices=ACTIVITY_TYPES)
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='activities')
    description = models.TextField()
    metadata = models.JSONField(default=dict, blank=True)
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
            'subadmin_created': 'bi-person-gear',
            'subadmin_updated': 'bi-person-gear',
            'subadmin_deleted': 'bi-person-dash',
        }
        return icons.get(self.activity_type, 'bi-info-circle')

    def get_color(self):
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
            'subadmin_created': 'success',
            'subadmin_updated': 'primary',
            'subadmin_deleted': 'danger',
        }
        return colors.get(self.activity_type, 'secondary')

    @classmethod
    def create_activity(cls, activity_type, description, user=None, metadata=None):
        return cls.objects.create(
            activity_type=activity_type,
            user=user,
            description=description,
            metadata=metadata or {}
        )

    def is_login_activity(self):
        return self.activity_type == 'user_login'

    @property
    def time(self):
        return self.created_at