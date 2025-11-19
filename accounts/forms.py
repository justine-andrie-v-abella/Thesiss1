# ============================================================================
# FILE: accounts/forms.py
# ============================================================================

from django import forms
from django.contrib.auth.models import User
from .models import TeacherProfile, Department, Subject

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

class DepartmentForm(forms.ModelForm):
    class Meta:
        model = Department
        fields = ['name', 'code', 'description']

class SubjectForm(forms.ModelForm):
    class Meta:
        model = Subject
        fields = ['departments', 'code', 'name', 'description']  # Should be 'departments' not 'department'
        widgets = {
            'description': forms.Textarea(attrs={'rows': 3}),
            'departments': forms.CheckboxSelectMultiple(),
        }
