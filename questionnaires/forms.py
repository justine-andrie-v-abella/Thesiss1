# ============================================================================
# FILE: questionnaires/forms.py
# ============================================================================

from django import forms
from .models import Questionnaire, QuestionType
from accounts.models import Department, Subject


class QuestionnaireUploadForm(forms.ModelForm):
    ALLOWED_EXTENSIONS = ['pdf', 'docx', 'doc', 'xlsx', 'xls', 'txt']

    subject = forms.ModelChoiceField(
        queryset=Subject.objects.none(),
        required=True,
        label="Subject",
    )

    exam_type = forms.ChoiceField(
        choices=[('', '-- Select Exam Type --')] + Questionnaire.EXAM_TYPE_CHOICES,
        required=True,
        label="Exam Type",
        widget=forms.Select(attrs={
            'id': 'id_exam_type',
            'class': (
                'w-full px-4 py-3 border-2 border-gray-300 rounded-lg '
                'focus:outline-none focus:border-orange-500 transition-colors'
            ),
        }),
    )

    question_types = forms.ModelMultipleChoiceField(
        queryset=QuestionType.objects.filter(is_active=True),
        widget=forms.CheckboxSelectMultiple,
        required=False,
        label="Filter Question Types (Optional)",
        help_text="Leave empty to extract all question types",
    )

    auto_extract = forms.BooleanField(
        required=False,
        initial=True,
        label="Enable AI extraction",
    )

    class Meta:
        model  = Questionnaire
        fields = ['title', 'description', 'subject', 'exam_type', 'file']
        widgets = {
            'description': forms.Textarea(attrs={'rows': 3}),
        }

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)

        if self.user and hasattr(self.user, 'teacher_profile'):
            teacher = self.user.teacher_profile
            self.fields['subject'].queryset = Subject.objects.filter(
                departments=teacher.department
            )

    def clean_exam_type(self):
        value = self.cleaned_data.get('exam_type')
        if not value:
            raise forms.ValidationError('Please select an exam type.')
        valid = [k for k, _ in Questionnaire.EXAM_TYPE_CHOICES]
        if value not in valid:
            raise forms.ValidationError('Invalid exam type selected.')
        return value

    def clean_file(self):
        file = self.cleaned_data.get('file')
        if file:
            ext = file.name.split('.')[-1].lower()
            if ext not in self.ALLOWED_EXTENSIONS:
                raise forms.ValidationError(
                    f'File type not allowed. Allowed types: {", ".join(self.ALLOWED_EXTENSIONS)}'
                )
            if file.size > 10 * 1024 * 1024:
                raise forms.ValidationError('File size must be under 10MB')
        return file


class QuestionnaireEditForm(forms.ModelForm):
    exam_type = forms.ChoiceField(
        choices=[('', '-- Select Exam Type --')] + Questionnaire.EXAM_TYPE_CHOICES,
        required=True,
        label="Exam Type",
        widget=forms.Select(attrs={
            'class': (
                'w-full px-4 py-3 border-2 border-gray-300 rounded-lg '
                'focus:outline-none focus:border-orange-500 transition-colors'
            ),
        }),
    )

    class Meta:
        model  = Questionnaire
        fields = ['title', 'description', 'exam_type']
        widgets = {
            'description': forms.Textarea(attrs={'rows': 3}),
        }


class QuestionnaireFilterForm(forms.Form):
    department = forms.ModelChoiceField(
        queryset=Department.objects.all(),
        required=False,
        empty_label="All Departments",
    )
    subject = forms.ModelChoiceField(
        queryset=Subject.objects.all(),
        required=False,
        empty_label="All Subjects",
    )
    exam_type = forms.ChoiceField(
        choices=[('', 'All Exam Types')] + Questionnaire.EXAM_TYPE_CHOICES,
        required=False,
        label="Exam Type",
    )
    search = forms.CharField(required=False, max_length=200)