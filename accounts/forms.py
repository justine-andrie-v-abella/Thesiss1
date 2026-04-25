# ============================================================================
# FILE: accounts/forms.py
# ============================================================================

import re
import dns.resolver
from django import forms
from django.contrib.auth.models import User
from django.core.validators import validate_email
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db.models import Q
from .models import TeacherProfile, Department, Subject, SubAdminProfile, Program


# ============================================================================
# SHARED VALIDATION HELPERS
# Called by multiple forms below — defined once to keep things DRY.
# ============================================================================

def validate_name_field(value, field_label):
    """
    Rejects digits and special characters that cannot appear in a real name.
    Allows: letters (including accented), spaces, hyphens, apostrophes, periods.
    Examples that pass  : O'Brien, Mary-Jane, José, Santos Jr.
    Examples that fail  : John123, Smith!, <script>
    """
    value = value.strip()
    if not value:
        raise forms.ValidationError(f"{field_label} is required.")
    if not re.match(r"^[A-Za-zÀ-ÖØ-öø-ÿ\s\-'\.]+$", value):
        raise forms.ValidationError(
            f"{field_label} may only contain letters, spaces, hyphens (-), "
            "apostrophes ('), or periods (.). Numbers and special characters are not allowed."
        )
    return value


def validate_email_domain(email):
    """
    1. Runs Django's built-in format check.
    2. Performs an MX-record DNS lookup to confirm the domain can receive mail.
    Raises forms.ValidationError on failure; returns the lowercased email on success.
    """
    email = email.strip().lower()

    # Step 1 — format check
    try:
        validate_email(email)
    except DjangoValidationError:
        raise forms.ValidationError("Enter a valid email address (e.g. teacher@school.edu).")

    # Step 2 — MX record check
    domain = email.split('@')[1]
    try:
        dns.resolver.resolve(domain, 'MX')
    except dns.resolver.NXDOMAIN:
        raise forms.ValidationError(
            f"The domain '{domain}' does not exist. Please check the email address."
        )
    except dns.resolver.NoAnswer:
        raise forms.ValidationError(
            f"The domain '{domain}' cannot receive emails (no MX records found)."
        )
    except dns.exception.DNSException:
        # Network hiccup — fail open so a temporary DNS outage doesn't
        # block all teacher creation. Remove this except block if you'd
        # rather fail closed.
        pass

    return email


# ============================================================================
# TEACHER CREATION FORM  (used by superadmin)
# ============================================================================

class TeacherCreationForm(forms.ModelForm):
    first_name  = forms.CharField(max_length=30, required=True)
    last_name   = forms.CharField(max_length=30, required=True)
    email       = forms.EmailField(required=True)
    username    = forms.CharField(max_length=150, required=True)
    password    = forms.CharField(widget=forms.PasswordInput, required=True)

    employee_id = forms.CharField(max_length=50, required=True)
    department  = forms.ModelChoiceField(queryset=Department.objects.all(), required=True)
    phone       = forms.CharField(max_length=20, required=False)

    class Meta:
        model  = TeacherProfile
        fields = ['employee_id', 'department', 'phone']

    # ── Name validation ──────────────────────────────────────────────────────

    def clean_first_name(self):
        return validate_name_field(self.cleaned_data.get('first_name', ''), 'First name')

    def clean_last_name(self):
        return validate_name_field(self.cleaned_data.get('last_name', ''), 'Last name')

    # ── Email validation (format + MX record) ────────────────────────────────

    def clean_email(self):
        email = validate_email_domain(self.cleaned_data.get('email', ''))
        if User.objects.filter(email=email).exists():
            raise forms.ValidationError("A user with this email address already exists.")
        return email

    # ── Username uniqueness ───────────────────────────────────────────────────

    def clean_username(self):
        username = self.cleaned_data.get('username', '').strip()
        if User.objects.filter(username=username).exists():
            raise forms.ValidationError("This username is already taken.")
        return username

    # ── Employee ID uniqueness ────────────────────────────────────────────────

    def clean_employee_id(self):
        eid = self.cleaned_data.get('employee_id', '').strip().upper()
        if TeacherProfile.objects.filter(employee_id=eid).exists():
            raise forms.ValidationError("A teacher with this Employee ID already exists.")
        return eid

    # ── Save ─────────────────────────────────────────────────────────────────

    def save(self, commit=True):
        user = User.objects.create_user(
            username   = self.cleaned_data['username'],
            email      = self.cleaned_data['email'],
            password   = self.cleaned_data['password'],
            first_name = self.cleaned_data['first_name'],
            last_name  = self.cleaned_data['last_name'],
        )

        teacher = TeacherProfile(
            user        = user,
            employee_id = self.cleaned_data['employee_id'],
            department  = self.cleaned_data['department'],
            phone       = self.cleaned_data.get('phone', ''),
        )

        if commit:
            teacher.save()

        return teacher


# ============================================================================
# TEACHER CREATION FORM — SubAdmin version
# Department is locked to the sub-admin's own department.
# ============================================================================

class SubAdminTeacherCreationForm(forms.ModelForm):
    first_name  = forms.CharField(max_length=30, required=True)
    last_name   = forms.CharField(max_length=30, required=True)
    email       = forms.EmailField(required=True)
    username    = forms.CharField(max_length=150, required=True)
    password    = forms.CharField(widget=forms.PasswordInput, required=True)

    employee_id = forms.CharField(max_length=50, required=True)
    phone       = forms.CharField(max_length=20, required=False)

    class Meta:
        model  = TeacherProfile
        fields = ['employee_id', 'phone']

    def __init__(self, *args, department=None, **kwargs):
        super().__init__(*args, **kwargs)
        self._locked_department = department

    # ── Name validation ──────────────────────────────────────────────────────

    def clean_first_name(self):
        return validate_name_field(self.cleaned_data.get('first_name', ''), 'First name')

    def clean_last_name(self):
        return validate_name_field(self.cleaned_data.get('last_name', ''), 'Last name')

    # ── Email validation ──────────────────────────────────────────────────────

    def clean_email(self):
        email = validate_email_domain(self.cleaned_data.get('email', ''))
        if User.objects.filter(email=email).exists():
            raise forms.ValidationError("A user with this email address already exists.")
        return email

    # ── Username uniqueness ───────────────────────────────────────────────────

    def clean_username(self):
        username = self.cleaned_data.get('username', '').strip()
        if User.objects.filter(username=username).exists():
            raise forms.ValidationError("This username is already taken.")
        return username

    # ── Employee ID uniqueness ────────────────────────────────────────────────

    def clean_employee_id(self):
        eid = self.cleaned_data.get('employee_id', '').strip().upper()
        if TeacherProfile.objects.filter(employee_id=eid).exists():
            raise forms.ValidationError("A teacher with this Employee ID already exists.")
        return eid

    # ── Save ─────────────────────────────────────────────────────────────────

    def save(self, commit=True):
        user = User.objects.create_user(
            username   = self.cleaned_data['username'],
            email      = self.cleaned_data['email'],
            password   = self.cleaned_data['password'],
            first_name = self.cleaned_data['first_name'],
            last_name  = self.cleaned_data['last_name'],
        )

        teacher = TeacherProfile(
            user        = user,
            employee_id = self.cleaned_data['employee_id'],
            department  = self._locked_department,
            phone       = self.cleaned_data.get('phone', ''),
        )

        if commit:
            teacher.save()

        return teacher


# ============================================================================
# TEACHER EDIT FORM  (used by superadmin)
# Adds: name validation, email MX check, username change, optional password reset.
# ============================================================================

class TeacherEditForm(forms.ModelForm):
    first_name   = forms.CharField(max_length=30, required=True)
    last_name    = forms.CharField(max_length=30, required=True)
    email        = forms.EmailField(required=True)

    # Login credential fields — shown in the edit modal
    username     = forms.CharField(max_length=150, required=True)
    new_password = forms.CharField(
        widget   = forms.PasswordInput,
        required = False,
        help_text = "Leave blank to keep the current password.",
    )

    class Meta:
        model  = TeacherProfile
        fields = ['employee_id', 'department', 'phone']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.user:
            self.fields['first_name'].initial = self.instance.user.first_name
            self.fields['last_name'].initial  = self.instance.user.last_name
            self.fields['email'].initial      = self.instance.user.email
            self.fields['username'].initial   = self.instance.user.username

    # ── Name validation ──────────────────────────────────────────────────────

    def clean_first_name(self):
        return validate_name_field(self.cleaned_data.get('first_name', ''), 'First name')

    def clean_last_name(self):
        return validate_name_field(self.cleaned_data.get('last_name', ''), 'Last name')

    # ── Email validation ──────────────────────────────────────────────────────

    def clean_email(self):
        email = validate_email_domain(self.cleaned_data.get('email', ''))
        # Allow the teacher to keep their own email; only reject if someone else owns it.
        qs = User.objects.filter(email=email)
        if self.instance and self.instance.pk:
            qs = qs.exclude(pk=self.instance.user.pk)
        if qs.exists():
            raise forms.ValidationError("This email address is already used by another account.")
        return email

    # ── Username uniqueness ───────────────────────────────────────────────────

    def clean_username(self):
        username = self.cleaned_data.get('username', '').strip()
        qs = User.objects.filter(username=username)
        if self.instance and self.instance.pk:
            qs = qs.exclude(pk=self.instance.user.pk)
        if qs.exists():
            raise forms.ValidationError("This username is already taken.")
        return username


# ============================================================================
# TEACHER EDIT FORM — SubAdmin version
# Same as TeacherEditForm but department is locked (not editable).
# ============================================================================

class SubAdminTeacherEditForm(forms.ModelForm):
    first_name   = forms.CharField(max_length=30, required=True)
    last_name    = forms.CharField(max_length=30, required=True)
    email        = forms.EmailField(required=True)

    username     = forms.CharField(max_length=150, required=True)
    new_password = forms.CharField(
        widget   = forms.PasswordInput,
        required = False,
        help_text = "Leave blank to keep the current password.",
    )

    class Meta:
        model  = TeacherProfile
        fields = ['employee_id', 'phone']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.user:
            self.fields['first_name'].initial = self.instance.user.first_name
            self.fields['last_name'].initial  = self.instance.user.last_name
            self.fields['email'].initial      = self.instance.user.email
            self.fields['username'].initial   = self.instance.user.username

    def clean_first_name(self):
        return validate_name_field(self.cleaned_data.get('first_name', ''), 'First name')

    def clean_last_name(self):
        return validate_name_field(self.cleaned_data.get('last_name', ''), 'Last name')

    def clean_email(self):
        email = validate_email_domain(self.cleaned_data.get('email', ''))
        qs = User.objects.filter(email=email)
        if self.instance and self.instance.pk:
            qs = qs.exclude(pk=self.instance.user.pk)
        if qs.exists():
            raise forms.ValidationError("This email address is already used by another account.")
        return email

    def clean_username(self):
        username = self.cleaned_data.get('username', '').strip()
        qs = User.objects.filter(username=username)
        if self.instance and self.instance.pk:
            qs = qs.exclude(pk=self.instance.user.pk)
        if qs.exists():
            raise forms.ValidationError("This username is already taken.")
        return username


# ============================================================================
# DEPARTMENT FORM
# ============================================================================

class DepartmentForm(forms.ModelForm):
    class Meta:
        model   = Department
        fields  = ['name', 'code', 'description']
        widgets = {
            'name':        forms.TextInput(attrs={'class': 'form-control'}),
            'code':        forms.TextInput(attrs={'class': 'form-control'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 4}),
        }


# ============================================================================
# SUBJECT FORM
# ============================================================================

class SubjectForm(forms.ModelForm):
    class Meta:
        model   = Subject
        fields  = ['departments', 'code', 'name', 'description']
        widgets = {
            'departments': forms.CheckboxSelectMultiple(),
            'code':        forms.TextInput(attrs={'class': 'form-control'}),
            'name':        forms.TextInput(attrs={'class': 'form-control'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 4}),
        }

    def clean_code(self):
        code = self.cleaned_data.get('code', '').upper().strip()
        return code  # dept-level validation done in clean()

    def clean(self):
        cleaned_data = super().clean()
        code = cleaned_data.get('code', '').upper().strip()
        departments = cleaned_data.get('departments')

        if not code or not departments:
            return cleaned_data

        # Check if any selected department already has a subject with this code
        conflicting_depts = []
        for dept in departments:
            qs = Subject.objects.filter(code=code, departments=dept)
            if self.instance.pk:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                conflicting_depts.append(dept.code)

        if conflicting_depts:
            raise forms.ValidationError(
                f'A subject with code "{code}" already exists in: '
                f'{", ".join(conflicting_depts)}.'
            )

        return cleaned_data


# ============================================================================
# SUB-ADMIN CREATION FORM  (used by superadmin)
# ============================================================================

class SubAdminCreationForm(forms.ModelForm):
    first_name = forms.CharField(
        max_length=30, required=True,
        widget=forms.TextInput(attrs={'class': 'form-control'})
    )
    last_name = forms.CharField(
        max_length=30, required=True,
        widget=forms.TextInput(attrs={'class': 'form-control'})
    )
    email = forms.EmailField(
        required=True,
        widget=forms.EmailInput(attrs={'class': 'form-control'})
    )
    username = forms.CharField(
        max_length=150, required=True,
        widget=forms.TextInput(attrs={'class': 'form-control'})
    )
    password = forms.CharField(
        widget=forms.PasswordInput(attrs={'class': 'form-control'}),
        required=True
    )
    department = forms.ModelChoiceField(
        queryset=Department.objects.filter(subadmin__isnull=True),
        required=True,
        widget=forms.Select(attrs={'class': 'form-select'})
    )

    class Meta:
        model  = SubAdminProfile
        fields = ['department']

    def clean_first_name(self):
        return validate_name_field(self.cleaned_data.get('first_name', ''), 'First name')

    def clean_last_name(self):
        return validate_name_field(self.cleaned_data.get('last_name', ''), 'Last name')

    def clean_username(self):
        username = self.cleaned_data['username']
        if User.objects.filter(username=username).exists():
            raise forms.ValidationError("This username is already taken.")
        return username

    def clean_email(self):
        email = validate_email_domain(self.cleaned_data.get('email', ''))
        if User.objects.filter(email=email).exists():
            raise forms.ValidationError("A user with this email already exists.")
        return email

    def save(self, commit=True, assigned_by=None):
        user = User.objects.create_user(
            username     = self.cleaned_data['username'],
            email        = self.cleaned_data['email'],
            password     = self.cleaned_data['password'],
            first_name   = self.cleaned_data['first_name'],
            last_name    = self.cleaned_data['last_name'],
            is_staff     = False,
            is_superuser = False,
        )

        subadmin = SubAdminProfile(
            user        = user,
            department  = self.cleaned_data['department'],
            assigned_by = assigned_by,
            is_active   = True,
        )

        if commit:
            subadmin.save()

        return subadmin


# ============================================================================
# SUB-ADMIN EDIT FORM  (used by superadmin)
# ============================================================================

class SubAdminEditForm(forms.ModelForm):
    first_name = forms.CharField(
        max_length=30, required=True,
        widget=forms.TextInput(attrs={'class': 'form-control'})
    )
    last_name = forms.CharField(
        max_length=30, required=True,
        widget=forms.TextInput(attrs={'class': 'form-control'})
    )
    email = forms.EmailField(
        required=True,
        widget=forms.EmailInput(attrs={'class': 'form-control'})
    )

    class Meta:
        model   = SubAdminProfile
        fields  = ['department', 'is_active']
        widgets = {
            'department': forms.Select(attrs={'class': 'form-select'}),
            'is_active':  forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.user:
            self.fields['first_name'].initial = self.instance.user.first_name
            self.fields['last_name'].initial  = self.instance.user.last_name
            self.fields['email'].initial      = self.instance.user.email

        if self.instance and self.instance.pk:
            self.fields['department'].queryset = Department.objects.filter(
                Q(subadmin__isnull=True) | Q(subadmin=self.instance)
            )

    def clean_first_name(self):
        return validate_name_field(self.cleaned_data.get('first_name', ''), 'First name')

    def clean_last_name(self):
        return validate_name_field(self.cleaned_data.get('last_name', ''), 'Last name')

    def clean_email(self):
        email = validate_email_domain(self.cleaned_data.get('email', ''))
        qs = User.objects.filter(email=email)
        if self.instance and self.instance.pk:
            qs = qs.exclude(pk=self.instance.user.pk)
        if qs.exists():
            raise forms.ValidationError("That email address is already in use by another account.")
        return email

    def save(self, commit=True):
        subadmin = super().save(commit=False)
        subadmin.user.first_name = self.cleaned_data['first_name']
        subadmin.user.last_name  = self.cleaned_data['last_name']
        subadmin.user.email      = self.cleaned_data['email']

        if commit:
            subadmin.user.save()
            subadmin.save()

        return subadmin


# ============================================================================
# PROGRAM FORM  (used by superadmin and sub-admin)
# ============================================================================

class ProgramForm(forms.ModelForm):
    class Meta:
        model   = Program
        fields  = ['name', 'code', 'description', 'is_active']
        widgets = {
            'name':        forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g., Bachelor of Science in Computer Science'}),
            'code':        forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g., BSCS', 'style': 'text-transform:uppercase'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 3, 'placeholder': 'Brief description of the program...'}),
            'is_active':   forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }

    def clean_code(self):
        return self.cleaned_data.get('code', '').upper().strip()

    def clean_name(self):
        name = self.cleaned_data.get('name', '').strip()
        if not name:
            raise forms.ValidationError('Program name is required.')
        return name