# ============================================================================
# FILE: accounts/views.py
# ============================================================================

from django.utils import timezone
from datetime import timedelta
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import login, logout, authenticate
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib import messages
from django.db.models import Q, Count
from .models import ActivityLog, TeacherProfile, Department, Subject, SubAdminProfile
from .forms import (
    TeacherCreationForm, TeacherEditForm,
    DepartmentForm, SubjectForm,
    SubAdminCreationForm, SubAdminEditForm,
    SubAdminTeacherCreationForm, SubAdminTeacherEditForm,
)
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.db import OperationalError

import logging
logger = logging.getLogger(__name__)


# ============================================================================
# ROLE HELPER FUNCTIONS
# ============================================================================

def is_admin(user):
    """Superadmin check — existing function, do NOT rename."""
    return user.is_authenticated and user.is_staff


def is_subadmin(user):
    """Sub-admin check — has an active SubAdminProfile."""
    return (
        user.is_authenticated
        and not user.is_staff
        and hasattr(user, 'subadmin_profile')
        and user.subadmin_profile.is_active
    )


def is_any_admin(user):
    """Either superadmin or sub-admin."""
    return is_admin(user) or is_subadmin(user)


def get_subadmin_department(user):
    """Safely get the sub-admin's department. Returns None if not a sub-admin."""
    try:
        return user.subadmin_profile.department
    except SubAdminProfile.DoesNotExist:
        return None


# ============================================================================
# ACTIVITY LOG HELPERS
# ============================================================================

def log_activity(activity_type, description, user=None, metadata=None):
    ActivityLog.objects.create(
        activity_type=activity_type,
        user=user,
        description=description,
        metadata=metadata or {}
    )


# ============================================================================
# AUTH VIEWS
# ============================================================================

def login_view(request):
    if request.user.is_authenticated:
        return redirect('home')

    if request.method == 'POST':
        username = request.POST.get('username')
        password = request.POST.get('password')

        try:
            user = authenticate(request, username=username, password=password)

            if user is not None:
                login(request, user)

                user_role = "Administrator" if user.is_staff else "Teacher"
                if hasattr(user, 'subadmin_profile'):
                    user_role = "Sub-Admin"

                ActivityLog.objects.create(
                    activity_type='user_login',
                    user=user,
                    description=f"{user_role} {user.get_full_name()} logged in to the system"
                )

                # ── Role-based redirect ──
                if user.is_staff:
                    return redirect('accounts:admin_dashboard')
                elif hasattr(user, 'subadmin_profile') and user.subadmin_profile.is_active:
                    return redirect('accounts:subadmin_dashboard')
                else:
                    return redirect('accounts:teacher_dashboard')
            else:
                messages.error(request, 'Invalid username or password')

        except OperationalError:
            messages.error(request, 'Please check your internet connection and try again.')
        except Exception:
            messages.error(request, 'An unexpected error occurred. Please try again.')

    return render(request, 'accounts/login.html')


@login_required
def logout_view(request):
    logout(request)
    messages.success(request, 'Logged out successfully')
    return redirect('home')


# ============================================================================
# SUPERADMIN DASHBOARD
# ============================================================================

@login_required
@user_passes_test(is_admin)
def admin_dashboard(request):
    from questionnaires.models import Questionnaire, Download
    import json

    total_teachers = TeacherProfile.objects.count()
    active_teachers = TeacherProfile.objects.filter(is_active=True).count()
    total_departments = Department.objects.count()
    total_subjects = Subject.objects.count()
    total_subadmins = SubAdminProfile.objects.filter(is_active=True).count()  # NEW

    selected_department = request.GET.get('department', 'all')

    questionnaires_qs = Questionnaire.objects.all()
    if selected_department != 'all':
        questionnaires_qs = questionnaires_qs.filter(department_id=selected_department)

    total_uploads = questionnaires_qs.count()
    total_downloads = Download.objects.filter(
        questionnaire__in=questionnaires_qs
    ).count() if selected_department != 'all' else Download.objects.count()
    total_questionnaires = questionnaires_qs.count()

    departments = Department.objects.all().order_by('name')

    department_stats = []
    max_downloads = 1

    for dept in departments:
        dept_questionnaires = Questionnaire.objects.filter(department=dept)
        upload_count = dept_questionnaires.count()
        download_count = Download.objects.filter(questionnaire__in=dept_questionnaires).count()

        if download_count > max_downloads:
            max_downloads = download_count

        department_stats.append({
            'department_name': dept.name,
            'questionnaire_count': upload_count,
            'upload_count': upload_count,
            'download_count': download_count,
            'popularity_percent': 0
        })

    for stat in department_stats:
        if max_downloads > 0:
            stat['popularity_percent'] = int((stat['download_count'] / max_downloads) * 100)

    department_stats.sort(key=lambda x: x['questionnaire_count'], reverse=True)

    activity_chart_data = get_activity_chart_data(selected_department)
    department_chart_data = get_department_chart_data()

    context = {
        'total_teachers': total_teachers,
        'active_teachers': active_teachers,
        'total_departments': total_departments,
        'total_subjects': total_subjects,
        'total_subadmins': total_subadmins,
        'total_uploads': total_uploads,
        'total_downloads': total_downloads,
        'total_questionnaires': total_questionnaires,
        'departments': departments,
        'department_stats': department_stats,
        'activity_chart_data': json.dumps(activity_chart_data),
        'department_chart_data': json.dumps(department_chart_data),
        'selected_department': selected_department,
    }
    return render(request, 'admin_dashboard/dashboard.html', context)


# ============================================================================
# SUPERADMIN — TEACHER MANAGEMENT (unchanged, scoped to all departments)
# ============================================================================

@login_required
@user_passes_test(is_admin)
def manage_teachers(request):
    teachers = TeacherProfile.objects.select_related('user', 'department').all()

    search_query = request.GET.get('search', '')
    if search_query:
        teachers = teachers.filter(
            Q(user__first_name__icontains=search_query) |
            Q(user__last_name__icontains=search_query) |
            Q(employee_id__icontains=search_query)
        )

    context = {'teachers': teachers, 'search_query': search_query}
    return render(request, 'admin_dashboard/manage_teachers.html', context)


@login_required
@user_passes_test(is_admin)
def add_teacher(request):
    if request.method == 'POST':
        form = TeacherCreationForm(request.POST)
        if form.is_valid():
            teacher = form.save()
            ActivityLog.objects.create(
                activity_type='teacher_created',
                user=request.user,
                description=f"Teacher {teacher.user.get_full_name()} ({teacher.employee_id}) was created"
            )
            messages.success(request, 'Teacher added successfully')
            return redirect('accounts:manage_teachers')
    else:
        form = TeacherCreationForm()
    return render(request, 'admin_dashboard/add_teacher.html', {'form': form})


@login_required
@user_passes_test(is_admin)
def edit_teacher(request, pk):
    teacher = get_object_or_404(TeacherProfile, pk=pk)

    if request.method == 'POST':
        form = TeacherEditForm(request.POST, instance=teacher)
        if form.is_valid():
            teacher = form.save()
            teacher.user.first_name = form.cleaned_data['first_name']
            teacher.user.last_name = form.cleaned_data['last_name']
            teacher.user.email = form.cleaned_data['email']
            teacher.user.save()

            ActivityLog.objects.create(
                activity_type='teacher_updated',
                user=request.user,
                description=f"Teacher {teacher.user.get_full_name()} ({teacher.employee_id}) profile was updated"
            )
            messages.success(request, 'Teacher updated successfully')
            return redirect('accounts:manage_teachers')
    else:
        form = TeacherEditForm(instance=teacher)
    return render(request, 'admin_dashboard/edit_teacher.html', {'form': form, 'teacher': teacher})


@login_required
@user_passes_test(is_admin)
def delete_teacher(request, pk):
    teacher = get_object_or_404(TeacherProfile, pk=pk)
    if request.method == 'POST':
        teacher_name = f"{teacher.user.get_full_name()} ({teacher.employee_id})"
        user = teacher.user

        ActivityLog.objects.create(
            activity_type='teacher_deleted',
            user=request.user,
            description=f"Teacher {teacher_name} was deleted from the system"
        )
        teacher.delete()
        user.delete()
        messages.success(request, 'Teacher deleted successfully')
        return redirect('accounts:manage_teachers')
    return render(request, 'admin_dashboard/delete_teacher.html', {'teacher': teacher})


# ============================================================================
# SUPERADMIN — DEPARTMENT MANAGEMENT
# ============================================================================

@login_required
@user_passes_test(is_admin)
def manage_departments(request):
    departments = Department.objects.all().order_by('name')

    if request.method == 'POST':
        form = DepartmentForm(request.POST)
        if form.is_valid():
            department = form.save()
            ActivityLog.objects.create(
                activity_type='department_created',
                user=request.user,
                description=f"Department {department.name} ({department.code}) was created"
            )
            messages.success(request, f'Department "{department.name}" has been added successfully!')
            return redirect('accounts:manage_departments')
        else:
            messages.error(request, 'Please correct the errors in the form.')
    else:
        form = DepartmentForm()

    context = {'departments': departments, 'form': form}
    return render(request, 'admin_dashboard/manage_departments.html', context)


@login_required
@user_passes_test(is_admin)
def add_department(request):
    if request.method == 'POST':
        form = DepartmentForm(request.POST)
        if form.is_valid():
            department = form.save()
            ActivityLog.objects.create(
                activity_type='department_created',
                user=request.user,
                description=f"Department {department.name} ({department.code}) was created"
            )
            messages.success(request, f'Department "{department.name}" has been added successfully!')
            return redirect('accounts:manage_departments')
        else:
            messages.error(request, 'Please correct the errors in the form.')
    else:
        form = DepartmentForm()
    return render(request, 'admin_dashboard/add_department.html', {'form': form})


@login_required
@user_passes_test(is_admin)
def edit_department(request, pk):
    department = get_object_or_404(Department, pk=pk)
    old_name = department.name
    old_code = department.code

    if request.method == 'POST':
        form = DepartmentForm(request.POST, instance=department)
        if form.is_valid():
            updated_department = form.save()
            ActivityLog.objects.create(
                activity_type='department_updated',
                user=request.user,
                description=f"Department {old_name} ({old_code}) was updated to {updated_department.name} ({updated_department.code})"
            )
            messages.success(request, f'Department "{updated_department.name}" has been updated successfully!')
            return redirect('accounts:manage_departments')
        else:
            messages.error(request, 'Please correct the errors in the form.')
    else:
        form = DepartmentForm(instance=department)

    return render(request, 'admin_dashboard/edit_department.html', {'form': form, 'department': department})


@login_required
@user_passes_test(is_admin)
def delete_department(request, pk):
    department = get_object_or_404(Department, pk=pk)

    if request.method == 'POST':
        department_name = department.name
        department_code = department.code

        ActivityLog.objects.create(
            activity_type='department_deleted',
            user=request.user,
            description=f"Department {department_name} ({department_code}) was deleted"
        )
        department.delete()
        messages.success(request, f'Department "{department_name}" has been deleted successfully!')
        return redirect('accounts:manage_departments')

    return render(request, 'admin_dashboard/delete_department.html', {'department': department})


# ============================================================================
# SUPERADMIN — SUBJECT MANAGEMENT
# ============================================================================

@login_required
@user_passes_test(is_admin)
def manage_subjects(request):
    subjects = Subject.objects.prefetch_related('departments').all().order_by('name')

    if request.method == 'POST':
        form = SubjectForm(request.POST)
        if form.is_valid():
            subject = form.save()
            ActivityLog.objects.create(
                activity_type='subject_created',
                user=request.user,
                description=f"Subject {subject.name} ({subject.code}) was created"
            )
            messages.success(request, f'Subject "{subject.name}" ({subject.code}) has been added successfully!')
            return redirect('accounts:manage_subjects')
        else:
            messages.error(request, 'Please correct the errors in the form.')
    else:
        form = SubjectForm()

    context = {'subjects': subjects, 'form': form}
    return render(request, 'admin_dashboard/manage_subjects.html', context)


@login_required
@user_passes_test(is_admin)
def add_subject(request):
    if request.method == 'POST':
        form = SubjectForm(request.POST)
        if form.is_valid():
            subject = form.save()
            ActivityLog.objects.create(
                activity_type='subject_created',
                user=request.user,
                description=f"Subject {subject.name} ({subject.code}) was created"
            )
            messages.success(request, f'Subject "{subject.name}" ({subject.code}) has been added successfully!')
            return redirect('accounts:manage_subjects')
        else:
            messages.error(request, 'Please correct the errors in the form.')
    else:
        form = SubjectForm()
    return render(request, 'admin_dashboard/add_subject.html', {'form': form})


@login_required
@user_passes_test(is_admin)
def edit_subject(request, pk):
    subject = get_object_or_404(Subject, pk=pk)
    old_name = subject.name
    old_code = subject.code

    if request.method == 'POST':
        form = SubjectForm(request.POST, instance=subject)
        if form.is_valid():
            updated_subject = form.save()
            ActivityLog.objects.create(
                activity_type='subject_updated',
                user=request.user,
                description=f"Subject {old_name} ({old_code}) was updated to {updated_subject.name} ({updated_subject.code})"
            )
            messages.success(request, f'Subject "{updated_subject.name}" ({updated_subject.code}) has been updated successfully!')
            return redirect('accounts:manage_subjects')
        else:
            messages.error(request, 'Please correct the errors in the form.')
    else:
        form = SubjectForm(instance=subject)

    return render(request, 'admin_dashboard/edit_subject.html', {'form': form, 'subject': subject})


@login_required
@user_passes_test(is_admin)
def delete_subject(request, pk):
    subject = get_object_or_404(Subject, pk=pk)

    if request.method == 'POST':
        subject_name = subject.name
        subject_code = subject.code

        ActivityLog.objects.create(
            activity_type='subject_deleted',
            user=request.user,
            description=f"Subject {subject_name} ({subject_code}) was deleted"
        )
        subject.delete()
        messages.success(request, f'Subject "{subject_name}" ({subject_code}) has been deleted successfully!')
        return redirect('accounts:manage_subjects')

    return render(request, 'admin_dashboard/delete_subject.html', {'subject': subject})


# ============================================================================
# SUPERADMIN — SUB-ADMIN MANAGEMENT  (NEW)
# ============================================================================

@login_required
@user_passes_test(is_admin)
def manage_subadmins(request):
    """List all sub-admins across all departments."""
    subadmins = SubAdminProfile.objects.select_related('user', 'department', 'assigned_by').all()

    context = {'subadmins': subadmins}
    return render(request, 'admin_dashboard/manage_subadmins.html', context)


@login_required
@user_passes_test(is_admin)
def add_subadmin(request):
    """Superadmin creates a new sub-admin and assigns them to a department."""
    if request.method == 'POST':
        form = SubAdminCreationForm(request.POST)
        if form.is_valid():
            subadmin = form.save(assigned_by=request.user)
            ActivityLog.objects.create(
                activity_type='subadmin_created',
                user=request.user,
                description=(
                    f"Sub-Admin {subadmin.user.get_full_name()} was created "
                    f"and assigned to {subadmin.department.name}"
                )
            )
            messages.success(
                request,
                f'Sub-Admin "{subadmin.user.get_full_name()}" has been created and assigned to {subadmin.department.name}.'
            )
            return redirect('accounts:manage_subadmins')
        else:
            messages.error(request, 'Please correct the errors in the form.')
    else:
        form = SubAdminCreationForm()

    return render(request, 'admin_dashboard/add_subadmin.html', {'form': form})


@login_required
@user_passes_test(is_admin)
def edit_subadmin(request, pk):
    """Superadmin edits a sub-admin's details or re-assigns their department."""
    subadmin = get_object_or_404(SubAdminProfile, pk=pk)
    old_dept = subadmin.department.name if subadmin.department else "None"

    if request.method == 'POST':
        form = SubAdminEditForm(request.POST, instance=subadmin)
        if form.is_valid():
            updated = form.save()
            new_dept = updated.department.name if updated.department else "None"
            ActivityLog.objects.create(
                activity_type='subadmin_updated',
                user=request.user,
                description=(
                    f"Sub-Admin {updated.user.get_full_name()} was updated. "
                    f"Department: {old_dept} → {new_dept}"
                )
            )
            messages.success(request, f'Sub-Admin "{updated.user.get_full_name()}" has been updated.')
            return redirect('accounts:manage_subadmins')
        else:
            messages.error(request, 'Please correct the errors in the form.')
    else:
        form = SubAdminEditForm(instance=subadmin)

    return render(request, 'admin_dashboard/edit_subadmin.html', {'form': form, 'subadmin': subadmin})


@login_required
@user_passes_test(is_admin)
def delete_subadmin(request, pk):
    """Superadmin removes a sub-admin (deletes profile + user account)."""
    subadmin = get_object_or_404(SubAdminProfile, pk=pk)

    if request.method == 'POST':
        name = subadmin.user.get_full_name()
        dept_name = subadmin.department.name if subadmin.department else "N/A"
        user = subadmin.user

        ActivityLog.objects.create(
            activity_type='subadmin_deleted',
            user=request.user,
            description=f"Sub-Admin {name} (Department: {dept_name}) was removed"
        )
        subadmin.delete()
        user.delete()
        messages.success(request, f'Sub-Admin "{name}" has been removed.')
        return redirect('accounts:manage_subadmins')

    return render(request, 'admin_dashboard/delete_subadmin.html', {'subadmin': subadmin})


# ============================================================================
# SUB-ADMIN DASHBOARD  (NEW)
# ============================================================================

@login_required
@user_passes_test(is_subadmin)
def subadmin_dashboard(request):
    """
    Sub-admin's home page. Shows only their department's data.
    """
    subadmin = request.user.subadmin_profile
    department = subadmin.department

    # Teachers in this department only
    total_teachers = TeacherProfile.objects.filter(department=department).count()
    active_teachers = TeacherProfile.objects.filter(department=department, is_active=True).count()

    # Recent activities — only teacher actions performed by this sub-admin
    recent_activities = ActivityLog.objects.filter(
        user=request.user
    ).exclude(
        activity_type='user_login'
    ).order_by('-created_at')[:15]

    context = {
        'subadmin': subadmin,
        'department': department,
        'total_teachers': total_teachers,
        'active_teachers': active_teachers,
        'recent_activities': recent_activities,
    }
    return render(request, 'subadmin_dashboard/dashboard.html', context)


# ============================================================================
# SUB-ADMIN — TEACHER MANAGEMENT  (NEW)
# All views are scoped to the sub-admin's department only.
# ============================================================================

@login_required
@user_passes_test(is_subadmin)
def subadmin_manage_teachers(request):
    """List teachers in the sub-admin's department only."""
    department = request.user.subadmin_profile.department

    teachers = TeacherProfile.objects.select_related('user', 'department').filter(
        department=department
    )

    search_query = request.GET.get('search', '')
    if search_query:
        teachers = teachers.filter(
            Q(user__first_name__icontains=search_query) |
            Q(user__last_name__icontains=search_query) |
            Q(employee_id__icontains=search_query)
        )

    context = {
        'teachers': teachers,
        'search_query': search_query,
        'department': department,
    }
    return render(request, 'subadmin_dashboard/manage_teachers.html', context)


@login_required
@user_passes_test(is_subadmin)
def subadmin_add_teacher(request):
    """Sub-admin adds a teacher — department is automatically their own."""
    department = request.user.subadmin_profile.department

    if request.method == 'POST':
        form = SubAdminTeacherCreationForm(request.POST, department=department)
        if form.is_valid():
            teacher = form.save()
            ActivityLog.objects.create(
                activity_type='teacher_created',
                user=request.user,
                description=(
                    f"Teacher {teacher.user.get_full_name()} ({teacher.employee_id}) "
                    f"was added to {department.name} by Sub-Admin {request.user.get_full_name()}"
                )
            )
            messages.success(request, 'Teacher added successfully.')
            return redirect('accounts:subadmin_manage_teachers')
        else:
            messages.error(request, 'Please correct the errors in the form.')
    else:
        form = SubAdminTeacherCreationForm(department=department)

    context = {
        'form': form,
        'department': department,
    }
    return render(request, 'subadmin_dashboard/add_teacher.html', context)


@login_required
@user_passes_test(is_subadmin)
def subadmin_edit_teacher(request, pk):
    """Sub-admin edits a teacher — only if the teacher belongs to their department."""
    department = request.user.subadmin_profile.department

    # 404 if the teacher doesn't belong to this sub-admin's department
    teacher = get_object_or_404(TeacherProfile, pk=pk, department=department)

    if request.method == 'POST':
        form = SubAdminTeacherEditForm(request.POST, instance=teacher)
        if form.is_valid():
            teacher = form.save()
            teacher.user.first_name = form.cleaned_data['first_name']
            teacher.user.last_name = form.cleaned_data['last_name']
            teacher.user.email = form.cleaned_data['email']
            teacher.user.save()

            ActivityLog.objects.create(
                activity_type='teacher_updated',
                user=request.user,
                description=(
                    f"Teacher {teacher.user.get_full_name()} ({teacher.employee_id}) "
                    f"was updated by Sub-Admin {request.user.get_full_name()}"
                )
            )
            messages.success(request, 'Teacher updated successfully.')
            return redirect('accounts:subadmin_manage_teachers')
        else:
            messages.error(request, 'Please correct the errors in the form.')
    else:
        form = SubAdminTeacherEditForm(instance=teacher)

    context = {
        'form': form,
        'teacher': teacher,
        'department': department,
    }
    return render(request, 'subadmin_dashboard/edit_teacher.html', context)


@login_required
@user_passes_test(is_subadmin)
def subadmin_delete_teacher(request, pk):
    """Sub-admin deletes a teacher — only if the teacher belongs to their department."""
    department = request.user.subadmin_profile.department

    # 404 if the teacher doesn't belong to this sub-admin's department
    teacher = get_object_or_404(TeacherProfile, pk=pk, department=department)

    if request.method == 'POST':
        teacher_name = f"{teacher.user.get_full_name()} ({teacher.employee_id})"
        user = teacher.user

        ActivityLog.objects.create(
            activity_type='teacher_deleted',
            user=request.user,
            description=(
                f"Teacher {teacher_name} was removed from {department.name} "
                f"by Sub-Admin {request.user.get_full_name()}"
            )
        )
        teacher.delete()
        user.delete()
        messages.success(request, 'Teacher deleted successfully.')
        return redirect('accounts:subadmin_manage_teachers')

    context = {
        'teacher': teacher,
        'department': department,
    }
    return render(request, 'subadmin_dashboard/delete_teacher.html', context)


# ============================================================================
# TEACHER DASHBOARD
# ============================================================================

@login_required
def teacher_dashboard(request):
    if request.user.is_staff:
        return redirect('accounts:admin_dashboard')
    if hasattr(request.user, 'subadmin_profile'):
        return redirect('accounts:subadmin_dashboard')

    teacher = get_object_or_404(TeacherProfile, user=request.user)

    from questionnaires.models import Questionnaire, Download

    my_uploads = teacher.questionnaires.count()
    total_downloads = Download.objects.filter(questionnaire__uploader=teacher).count()

    current_month = timezone.now().month
    current_year = timezone.now().year
    uploads_this_month = teacher.questionnaires.filter(
        uploaded_at__month=current_month,
        uploaded_at__year=current_year
    ).count()

    upload_stats = get_teacher_upload_stats(teacher)

    top_downloads = Questionnaire.objects.filter(
        uploader=teacher
    ).annotate(download_count=Count('downloads')).order_by('-download_count')[:3]

    recent_activities = get_teacher_recent_activities(teacher)[:15]

    context = {
        'teacher': teacher,
        'my_uploads': my_uploads,
        'total_downloads': total_downloads,
        'uploads_this_month': uploads_this_month,
        'upload_stats': upload_stats,
        'top_downloads': top_downloads,
        'recent_activities': recent_activities,
    }
    return render(request, 'teacher_dashboard/dashboard.html', context)


def get_teacher_upload_stats(teacher):
    from questionnaires.models import Questionnaire
    from dateutil.relativedelta import relativedelta

    stats = []
    today = timezone.now()

    for i in range(5, -1, -1):
        month_date = today - relativedelta(months=i)
        count = Questionnaire.objects.filter(
            uploader=teacher,
            uploaded_at__month=month_date.month,
            uploaded_at__year=month_date.year
        ).count()
        stats.append({'label': month_date.strftime('%b'), 'count': count, 'percentage': 0})

    max_count = max(s['count'] for s in stats) if stats else 0
    for stat in stats:
        if max_count == 0:
            stat['percentage'] = 10
        elif stat['count'] == 0:
            stat['percentage'] = 5
        else:
            stat['percentage'] = max(10, int((stat['count'] / max_count) * 100))

    return stats


def get_teacher_recent_activities(teacher):
    from questionnaires.models import Questionnaire, Download

    activities = []

    recent_uploads = Questionnaire.objects.filter(uploader=teacher).order_by('-uploaded_at')[:5]
    for quest in recent_uploads:
        activities.append({'type': 'upload', 'message': f'You uploaded "{quest.title}"', 'timestamp': quest.uploaded_at})

    recent_downloads = Download.objects.filter(
        questionnaire__uploader=teacher
    ).select_related('user', 'questionnaire').order_by('-downloaded_at')[:5]

    for download in recent_downloads:
        if download.user and download.user != teacher.user:
            downloader_name = download.user.get_full_name()
            activities.append({
                'type': 'download',
                'message': f'{downloader_name} downloaded your "{download.questionnaire.title}"',
                'timestamp': download.downloaded_at,
            })

    activity_logs = ActivityLog.objects.filter(
        user=teacher.user
    ).exclude(activity_type='user_login').order_by('-created_at')[:5]

    for log in activity_logs:
        activities.append({'type': 'system', 'message': log.description, 'timestamp': log.created_at})

    activities.sort(key=lambda x: x['timestamp'], reverse=True)
    return activities


# ============================================================================
# NOTIFICATIONS
# ============================================================================

@login_required
@require_POST
def mark_all_notifications_read(request):
    try:
        if request.user.is_staff:
            updated_count = ActivityLog.objects.filter(is_read=False).update(is_read=True)
        else:
            updated_count = ActivityLog.objects.filter(
                user=request.user, is_read=False
            ).update(is_read=True)

        return JsonResponse({'success': True, 'message': f'{updated_count} notifications marked as read'})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


# ============================================================================
# CHART HELPERS
# ============================================================================

def get_activity_chart_data(department_filter='all'):
    from questionnaires.models import Questionnaire, Download

    today = timezone.now().date()
    date_range = [today - timedelta(days=i) for i in range(6, -1, -1)]
    labels = [d.strftime('%b %d') for d in date_range]
    uploads = []
    downloads = []

    for date in date_range:
        upload_qs = Questionnaire.objects.filter(uploaded_at__date=date)
        if department_filter != 'all':
            upload_qs = upload_qs.filter(department_id=department_filter)
        uploads.append(upload_qs.count())

        download_qs = Download.objects.filter(downloaded_at__date=date)
        if department_filter != 'all':
            download_qs = download_qs.filter(questionnaire__department_id=department_filter)
        downloads.append(download_qs.count())

    return {'labels': labels, 'uploads': uploads, 'downloads': downloads}


def get_department_chart_data():
    from questionnaires.models import Questionnaire

    departments = Department.objects.annotate(
        questionnaire_count=Count('questionnaires')
    ).filter(questionnaire_count__gt=0).order_by('-questionnaire_count')

    return {
        'labels': [dept.name for dept in departments],
        'values': [dept.questionnaire_count for dept in departments],
    }


@login_required
@user_passes_test(is_admin)
def test_activity(request):
    ActivityLog.objects.create(
        activity_type='system',
        user=request.user,
        description='Test activity created manually'
    )
    return redirect('accounts:admin_dashboard')