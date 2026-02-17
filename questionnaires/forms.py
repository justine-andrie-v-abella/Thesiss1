# ============================================================================
# FILE: questionnaires/forms.py
# ============================================================================

from django import forms
from .models import Questionnaire, QuestionType
from accounts.models import Department, Subject

class QuestionnaireUploadForm(forms.ModelForm):
    ALLOWED_EXTENSIONS = ['pdf', 'docx', 'doc', 'xlsx', 'xls', 'txt']
    
    department = forms.ModelChoiceField(
        queryset=Department.objects.all(),
        required=True,
        label="Department"
    )
    
    subject = forms.ModelChoiceField(
        queryset=Subject.objects.none(),
        required=True,
        label="Subject"
    )
    
    # Optional type filter - if empty, extracts ALL types
    question_types = forms.ModelMultipleChoiceField(
        queryset=QuestionType.objects.filter(is_active=True),
        widget=forms.CheckboxSelectMultiple,
        required=False,  # Optional - empty means extract all types
        label="Filter Question Types (Optional)",
        help_text="Leave empty to extract all question types"
    )
    
    auto_extract = forms.BooleanField(
        required=False,
        initial=True,
        label="Enable AI extraction",
    )
    
    class Meta:
        model = Questionnaire
        fields = ['title', 'description', 'department', 'subject', 'file']
        widgets = {
            'description': forms.Textarea(attrs={'rows': 3}),
        }
    
    def __init__(self, *args, **kwargs):
        user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)
        
        if user and hasattr(user, 'teacher_profile'):
            teacher = user.teacher_profile
            self.fields['department'].initial = teacher.department
            # Show subjects that belong to the teacher's department
            self.fields['subject'].queryset = Subject.objects.filter(departments=teacher.department)
        
        # If a department is selected in POST data, filter subjects accordingly
        if 'department' in self.data:
            try:
                department_id = int(self.data.get('department'))
                self.fields['subject'].queryset = Subject.objects.filter(departments__id=department_id)
            except (ValueError, TypeError):
                pass
    
    def clean_file(self):
        file = self.cleaned_data.get('file')
        if file:
            ext = file.name.split('.')[-1].lower()
            if ext not in self.ALLOWED_EXTENSIONS:
                raise forms.ValidationError(
                    f'File type not allowed. Allowed types: {", ".join(self.ALLOWED_EXTENSIONS)}'
                )
            
            # Check file size (max 10MB)
            if file.size > 10 * 1024 * 1024:
                raise forms.ValidationError('File size must be under 10MB')
        
        return file
    
    def clean(self):
        # No validation needed - question_types is optional
        # Empty = extract all types
        return super().clean()


class QuestionnaireEditForm(forms.ModelForm):
    class Meta:
        model = Questionnaire
        fields = ['title', 'description']
        widgets = {
            'description': forms.Textarea(attrs={'rows': 3}),
        }


class QuestionnaireFilterForm(forms.Form):
    department = forms.ModelChoiceField(
        queryset=Department.objects.all(),
        required=False,
        empty_label="All Departments"
    )
    subject = forms.ModelChoiceField(
        queryset=Subject.objects.all(),
        required=False,
        empty_label="All Subjects"
    )
    search = forms.CharField(required=False, max_length=200)