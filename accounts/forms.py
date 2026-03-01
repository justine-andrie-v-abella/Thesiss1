# ============================================================================
# FILE: accounts/forms.py
# ============================================================================

from django import forms
from django.contrib.auth.models import User
from django.db.models import Q
from .models import TeacherProfile, Department, Subject, SubAdminProfile


class TeacherCreationForm(forms.ModelForm):
    first_name = forms.CharField(max_length=30, required=True)
    last_name = forms.CharField(max_length=30, required=True)
    email = forms.EmailField(required=True)
    username = forms.CharField(max_length=150, required=True)
    password = forms.CharField(widget=forms.PasswordInput, required=True)

    employee_id = forms.CharField(max_length=50, required=True)
    department = forms.ModelChoiceField(queryset=Department.objects.all(), required=True)
    phone = forms.CharField(max_length=20, required=False)

    class Meta:
        model = TeacherProfile
        fields = ['employee_id', 'department', 'phone']

    def save(self, commit=True):
        user = User.objects.create_user(
            username=self.cleaned_data['username'],
            email=self.cleaned_data['email'],
            password=self.cleaned_data['password'],
            first_name=self.cleaned_data['first_name'],
            last_name=self.cleaned_data['last_name']
        )

        teacher = TeacherProfile(
            user=user,
            employee_id=self.cleaned_data['employee_id'],
            department=self.cleaned_data['department'],
            phone=self.cleaned_data.get('phone', '')
        )

        if commit:
            teacher.save()

        return teacher


# ============================================================================
# NEW: SubAdmin version of TeacherCreationForm
# The department field is locked to the sub-admin's department —
# it is passed in as an argument and rendered as a hidden/read-only field.
# ============================================================================
class SubAdminTeacherCreationForm(forms.ModelForm):
    first_name = forms.CharField(max_length=30, required=True)
    last_name = forms.CharField(max_length=30, required=True)
    email = forms.EmailField(required=True)
    username = forms.CharField(max_length=150, required=True)
    password = forms.CharField(widget=forms.PasswordInput, required=True)

    employee_id = forms.CharField(max_length=50, required=True)
    phone = forms.CharField(max_length=20, required=False)

    class Meta:
        model = TeacherProfile
        fields = ['employee_id', 'phone']

    def __init__(self, *args, department=None, **kwargs):
        super().__init__(*args, **kwargs)
        # Store the department so save() can use it
        self._locked_department = department

    def save(self, commit=True):
        user = User.objects.create_user(
            username=self.cleaned_data['username'],
            email=self.cleaned_data['email'],
            password=self.cleaned_data['password'],
            first_name=self.cleaned_data['first_name'],
            last_name=self.cleaned_data['last_name']
        )

        teacher = TeacherProfile(
            user=user,
            employee_id=self.cleaned_data['employee_id'],
            department=self._locked_department,
            phone=self.cleaned_data.get('phone', '')
        )

        if commit:
            teacher.save()

        return teacher


class TeacherEditForm(forms.ModelForm):
    first_name = forms.CharField(max_length=30, required=True)
    last_name = forms.CharField(max_length=30, required=True)
    email = forms.EmailField(required=True)

    class Meta:
        model = TeacherProfile
        fields = ['employee_id', 'department', 'phone', 'is_active']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.user:
            self.fields['first_name'].initial = self.instance.user.first_name
            self.fields['last_name'].initial = self.instance.user.last_name
            self.fields['email'].initial = self.instance.user.email


# ============================================================================
# NEW: SubAdmin version of TeacherEditForm
# Department is locked — sub-admins cannot move teachers to other departments.
# ============================================================================
class SubAdminTeacherEditForm(forms.ModelForm):
    first_name = forms.CharField(max_length=30, required=True)
    last_name = forms.CharField(max_length=30, required=True)
    email = forms.EmailField(required=True)

    class Meta:
        model = TeacherProfile
        # No 'department' field — it stays locked to the sub-admin's department
        fields = ['employee_id', 'phone', 'is_active']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.user:
            self.fields['first_name'].initial = self.instance.user.first_name
            self.fields['last_name'].initial = self.instance.user.last_name
            self.fields['email'].initial = self.instance.user.email


class DepartmentForm(forms.ModelForm):
    class Meta:
        model = Department
        fields = ['name', 'code', 'description']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'code': forms.TextInput(attrs={'class': 'form-control'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 4}),
        }


class SubjectForm(forms.ModelForm):
    class Meta:
        model = Subject
        fields = ['departments', 'code', 'name', 'description']
        widgets = {
            'departments': forms.CheckboxSelectMultiple(),
            'code': forms.TextInput(attrs={'class': 'form-control'}),
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 4}),
        }


# ============================================================================
# NEW: Sub-admin management forms (used by superadmin)
# ============================================================================

class SubAdminCreationForm(forms.ModelForm):
    """
    Used by the superadmin to create a new sub-admin account.
    Creates a Django User + SubAdminProfile in one go.
    """
    first_name = forms.CharField(
        max_length=30,
        required=True,
        widget=forms.TextInput(attrs={'class': 'form-control'})
    )
    last_name = forms.CharField(
        max_length=30,
        required=True,
        widget=forms.TextInput(attrs={'class': 'form-control'})
    )
    email = forms.EmailField(
        required=True,
        widget=forms.EmailInput(attrs={'class': 'form-control'})
    )
    username = forms.CharField(
        max_length=150,
        required=True,
        widget=forms.TextInput(attrs={'class': 'form-control'})
    )
    password = forms.CharField(
        widget=forms.PasswordInput(attrs={'class': 'form-control'}),
        required=True
    )
    department = forms.ModelChoiceField(
        # Only show departments that don't already have a sub-admin assigned
        queryset=Department.objects.filter(subadmin__isnull=True),
        required=True,
        widget=forms.Select(attrs={'class': 'form-select'})
    )

    class Meta:
        model = SubAdminProfile
        fields = ['department']

    def clean_username(self):
        username = self.cleaned_data['username']
        if User.objects.filter(username=username).exists():
            raise forms.ValidationError("This username is already taken.")
        return username

    def clean_email(self):
        email = self.cleaned_data['email']
        if User.objects.filter(email=email).exists():
            raise forms.ValidationError("A user with this email already exists.")
        return email

    def save(self, commit=True, assigned_by=None):
        user = User.objects.create_user(
            username=self.cleaned_data['username'],
            email=self.cleaned_data['email'],
            password=self.cleaned_data['password'],
            first_name=self.cleaned_data['first_name'],
            last_name=self.cleaned_data['last_name'],
            is_staff=False,         # Sub-admin is NOT a Django staff user
            is_superuser=False,
        )

        subadmin = SubAdminProfile(
            user=user,
            department=self.cleaned_data['department'],
            assigned_by=assigned_by,
            is_active=True,
        )

        if commit:
            subadmin.save()

        return subadmin


class SubAdminEditForm(forms.ModelForm):
    """
    Used by the superadmin to edit an existing sub-admin.
    Allows changing the department assignment and active status.
    """
    first_name = forms.CharField(
        max_length=30,
        required=True,
        widget=forms.TextInput(attrs={'class': 'form-control'})
    )
    last_name = forms.CharField(
        max_length=30,
        required=True,
        widget=forms.TextInput(attrs={'class': 'form-control'})
    )
    email = forms.EmailField(
        required=True,
        widget=forms.EmailInput(attrs={'class': 'form-control'})
    )

    class Meta:
        model = SubAdminProfile
        fields = ['department', 'is_active']
        widgets = {
            'department': forms.Select(attrs={'class': 'form-select'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.user:
            self.fields['first_name'].initial = self.instance.user.first_name
            self.fields['last_name'].initial = self.instance.user.last_name
            self.fields['email'].initial = self.instance.user.email

        # Allow the current department even if it already has this sub-admin assigned
        # (without this, the dropdown would exclude the current department)
        if self.instance and self.instance.pk:
            self.fields['department'].queryset = Department.objects.filter(
                Q(subadmin__isnull=True) | Q(subadmin=self.instance)
            )

    def save(self, commit=True):
        subadmin = super().save(commit=False)
        # Update the linked User record
        subadmin.user.first_name = self.cleaned_data['first_name']
        subadmin.user.last_name = self.cleaned_data['last_name']
        subadmin.user.email = self.cleaned_data['email']

        if commit:
            subadmin.user.save()
            subadmin.save()

        return subadmin