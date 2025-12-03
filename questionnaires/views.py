# ============================================================================
# FILE: questionnaires/views.py
# ============================================================================

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib import messages
from django.db.models import Q, Count
from django.core.paginator import Paginator
from django.http import FileResponse, Http404
from .models import Questionnaire
from .forms import QuestionnaireUploadForm, QuestionnaireEditForm, QuestionnaireFilterForm
from accounts.models import TeacherProfile, Department, Subject

def is_admin(user):
    return user.is_authenticated and user.is_staff

def is_teacher(user):
    return user.is_authenticated and not user.is_staff and hasattr(user, 'teacher_profile')

@login_required
def upload_questionnaire(request):
    if request.user.is_staff:
        messages.error(request, 'Admins cannot upload questionnaires')
        return redirect('accounts:admin_dashboard')
    
    teacher = get_object_or_404(TeacherProfile, user=request.user)
    
    if request.method == 'POST':
        form = QuestionnaireUploadForm(request.POST, request.FILES, user=request.user)
        if form.is_valid():
            questionnaire = form.save(commit=False)
            questionnaire.uploader = teacher
            questionnaire.save()
            messages.success(request, 'Questionnaire uploaded successfully')
            return redirect('questionnaires:my_uploads')
    else:
        form = QuestionnaireUploadForm(user=request.user)
    
    return render(request, 'teacher_dashboard/upload_questionnaire.html', {'form': form})

@login_required
def my_uploads(request):
    if request.user.is_staff:
        return redirect('accounts:admin_dashboard')
    
    teacher = get_object_or_404(TeacherProfile, user=request.user)
    questionnaires = Questionnaire.objects.filter(uploader=teacher).select_related('department', 'subject')
    
    search_query = request.GET.get('search', '')
    if search_query:
        questionnaires = questionnaires.filter(
            Q(title__icontains=search_query) |
            Q(description__icontains=search_query) |
            Q(subject__name__icontains=search_query)
        )
    
    paginator = Paginator(questionnaires, 10)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    context = {
        'page_obj': page_obj,
        'search_query': search_query,
    }
    return render(request, 'teacher_dashboard/my_uploads.html', context)

@login_required
def edit_questionnaire(request, pk):
    questionnaire = get_object_or_404(Questionnaire, pk=pk)
    
    # Check permissions
    if request.user.is_staff:
        can_edit = True
    elif hasattr(request.user, 'teacher_profile'):
        can_edit = questionnaire.uploader == request.user.teacher_profile
    else:
        can_edit = False
    
    if not can_edit:
        messages.error(request, 'You do not have permission to edit this questionnaire')
        return redirect('questionnaires:browse_questionnaires')
    
    if request.method == 'POST':
        form = QuestionnaireEditForm(request.POST, instance=questionnaire)
        if form.is_valid():
            form.save()
            messages.success(request, 'Questionnaire updated successfully')
            if request.user.is_staff:
                return redirect('questionnaires:all_questionnaires')
            return redirect('questionnaires:my_uploads')
    else:
        form = QuestionnaireEditForm(instance=questionnaire)
    
    return render(request, 'teacher_dashboard/edit_questionnaire.html', {
        'form': form,
        'questionnaire': questionnaire
    })

@login_required
def delete_questionnaire(request, pk):
    questionnaire = get_object_or_404(Questionnaire, pk=pk)
    
    # Check permissions
    if request.user.is_staff:
        can_delete = True
    elif hasattr(request.user, 'teacher_profile'):
        can_delete = questionnaire.uploader == request.user.teacher_profile
    else:
        can_delete = False
    
    if not can_delete:
        messages.error(request, 'You do not have permission to delete this questionnaire')
        return redirect('questionnaires:browse_questionnaires')
    
    if request.method == 'POST':
        questionnaire.file.delete()
        questionnaire.delete()
        messages.success(request, 'Questionnaire deleted successfully')
        if request.user.is_staff:
            return redirect('questionnaires:all_questionnaires')
        return redirect('questionnaires:my_uploads')
    
    return render(request, 'teacher_dashboard/delete_questionnaire.html', {
        'questionnaire': questionnaire
    })

@login_required
def browse_questionnaires(request):
    if request.user.is_staff:
        return redirect('questionnaires:all_questionnaires')
    
    questionnaires = Questionnaire.objects.select_related('department', 'subject', 'uploader__user').all()
    
    # Filtering
    department_id = request.GET.get('department')
    subject_id = request.GET.get('subject')
    search_query = request.GET.get('search', '')
    
    if department_id:
        questionnaires = questionnaires.filter(department_id=department_id)
    
    if subject_id:
        questionnaires = questionnaires.filter(subject_id=subject_id)
    
    if search_query:
        questionnaires = questionnaires.filter(
            Q(title__icontains=search_query) |
            Q(description__icontains=search_query) |
            Q(subject__name__icontains=search_query) |
            Q(subject__code__icontains=search_query)
        )
    
    # Get statistics
    departments = Department.objects.annotate(count=Count('questionnaires'))
    subjects = Subject.objects.all()
    
    paginator = Paginator(questionnaires, 12)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    context = {
        'page_obj': page_obj,
        'departments': departments,
        'subjects': subjects,
        'selected_department': department_id,
        'selected_subject': subject_id,
        'search_query': search_query,
    }
    return render(request, 'teacher_dashboard/browse_questionnaires.html', context)

@login_required
@user_passes_test(is_admin)
def all_questionnaires(request):
    questionnaires = Questionnaire.objects.select_related('department', 'subject', 'uploader__user').all()
    
    # Filtering
    department_id = request.GET.get('department')
    subject_id = request.GET.get('subject')
    search_query = request.GET.get('search', '')
    
    if department_id:
        questionnaires = questionnaires.filter(department_id=department_id)
    
    if subject_id:
        questionnaires = questionnaires.filter(subject_id=subject_id)
    
    if search_query:
        questionnaires = questionnaires.filter(
            Q(title__icontains=search_query) |
            Q(description__icontains=search_query) |
            Q(subject__name__icontains=search_query) |
            Q(uploader__user__first_name__icontains=search_query) |
            Q(uploader__user__last_name__icontains=search_query)
        )
    
    departments = Department.objects.all()
    subjects = Subject.objects.all()
    
    paginator = Paginator(questionnaires, 12)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    context = {
        'page_obj': page_obj,
        'departments': departments,
        'subjects': subjects,
        'selected_department': department_id,
        'selected_subject': subject_id,
        'search_query': search_query,
    }
    return render(request, 'admin_dashboard/all_questionnaires.html', context)

def get_client_ip(request):
    """Get the client's IP address from the request"""
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        ip = x_forwarded_for.split(',')[0]
    else:
        ip = request.META.get('REMOTE_ADDR')
    return ip

@login_required
def download_questionnaire(request, pk):
    from .models import Download
    questionnaire = get_object_or_404(Questionnaire, pk=pk)
    
    # Create download record
    Download.objects.create(
        questionnaire=questionnaire,
        user=request.user if request.user.is_authenticated else None,
        ip_address=get_client_ip(request)
    )
    
    try:
        return FileResponse(
            questionnaire.file.open('rb'),
            as_attachment=True,
            filename=questionnaire.file.name.split('/')[-1]
        )
    except FileNotFoundError:
        raise Http404("File not found")