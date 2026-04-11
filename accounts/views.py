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
from django.core.mail import send_mail
from django.conf import settings

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
# CACHE HELPER
# ============================================================================

def bust_dashboard_cache():
    """Call this after any create/update/delete to keep dashboard fresh."""
    from django.core.cache import cache
    from .models import Department
    cache.delete('admin_dashboard_stats_all')
    for dept in Department.objects.values_list('id', flat=True):
        cache.delete(f'admin_dashboard_stats_{dept}')


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
# EMAIL HELPER
# Centralised so both superadmin and sub-admin views can call it.
# ============================================================================

def send_teacher_invite_email(teacher, plain_password):
    full_name  = teacher.user.get_full_name()
    username   = teacher.user.username
    email      = teacher.user.email
    site_url   = getattr(settings, 'SITE_URL', 'http://localhost:2000')
    login_url  = f"{site_url}/accounts/login/"

    subject = "Your Teacher Account Has Been Created"

    message = f"""Hello {full_name},

An account has been created for you on our system.

Your login credentials
──────────────────────
Username : {username}
Password : {plain_password}

Please log in and change your password as soon as possible.

Login here: {login_url}

If you did not expect this email, please contact your administrator immediately.

— System Administration
"""

    try:
        send_mail(
            subject=subject,
            message=message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[email],
            fail_silently=False,
        )
        return True
    except Exception as e:
        print(f"EMAIL ERROR: {e}")
        logger.error(f"Failed to send invite email to {email}: {e}")
        return False


def send_credentials_updated_email(user, new_username=None, new_password=None):
    site_url  = getattr(settings, 'SITE_URL', 'http://localhost:2000')
    login_url = f"{site_url}/accounts/login/"
    changes   = []

    if new_username:
        changes.append(f"  New username : {new_username}")
    if new_password:
        changes.append(f"  New password : {new_password}")

    if not changes:
        return

    message = f"""Hello {user.get_full_name()},

An administrator has updated your login credentials.

Updated details
───────────────
{chr(10).join(changes)}

Please log in with your new credentials as soon as possible.

Login here: {login_url}

If you did not authorise this change, contact your administrator immediately.

— System Administration
"""

    try:
        send_mail(
            subject="Your Login Credentials Have Been Updated",
            message=message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[user.email],
            fail_silently=True,
        )
    except Exception as e:
        logger.error(f"Failed to send credential-update email to {user.email}: {e}")


def send_subadmin_invite_email(subadmin, plain_password):
    full_name  = subadmin.user.get_full_name()
    username   = subadmin.user.username
    email      = subadmin.user.email
    department = subadmin.department.name
    site_url   = getattr(settings, 'SITE_URL', 'http://localhost:2000')
    login_url  = f"{site_url}/accounts/login/"

    subject = "Your Sub-Admin Account Has Been Created"

    message = f"""Hello {full_name},

A sub-admin account has been created for you on our system.

Department  : {department}

Your login credentials
──────────────────────
Username : {username}
Password : {plain_password}

Please log in and change your password as soon as possible.

Login here: {login_url}

If you did not expect this email, please contact your administrator immediately.

— System Administration
"""

    try:
        send_mail(
            subject=subject,
            message=message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[email],
            fail_silently=False,
        )
        return True
    except Exception as e:
        logger.error(f"Failed to send sub-admin invite email to {email}: {e}")
        return False


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
    from django.core.cache import cache
    import json

    selected_department = request.GET.get('department', 'all')

    stats_key = f'admin_dashboard_stats_{selected_department}'
    cached    = cache.get(stats_key)

    if cached:
        context = cached
    else:
        total_teachers    = TeacherProfile.objects.count()
        active_teachers   = TeacherProfile.objects.filter(is_active=True).count()
        total_departments = Department.objects.count()
        total_subjects    = Subject.objects.count()
        total_subadmins   = SubAdminProfile.objects.filter(is_active=True).count()

        questionnaires_qs = Questionnaire.objects.all()
        if selected_department != 'all':
            questionnaires_qs = questionnaires_qs.filter(department_id=selected_department)

        total_uploads        = questionnaires_qs.count()
        total_downloads      = Download.objects.filter(
            questionnaire__in=questionnaires_qs
        ).count() if selected_department != 'all' else Download.objects.count()
        total_questionnaires = questionnaires_qs.count()

        departments      = Department.objects.all().order_by('name')
        department_stats = []
        max_downloads    = 1

        for dept in departments:
            dept_questionnaires = Questionnaire.objects.filter(department=dept)
            upload_count        = dept_questionnaires.count()
            download_count      = Download.objects.filter(
                questionnaire__in=dept_questionnaires
            ).count()

            if download_count > max_downloads:
                max_downloads = download_count

            department_stats.append({
                'department_name':     dept.name,
                'questionnaire_count': upload_count,
                'upload_count':        upload_count,
                'download_count':      download_count,
                'popularity_percent':  0,
            })

        for stat in department_stats:
            if max_downloads > 0:
                stat['popularity_percent'] = int(
                    (stat['download_count'] / max_downloads) * 100
                )

        department_stats.sort(key=lambda x: x['questionnaire_count'], reverse=True)

        activity_chart_data   = get_activity_chart_data(selected_department)
        department_chart_data = get_department_chart_data()

        context = {
            'total_teachers':        total_teachers,
            'active_teachers':       active_teachers,
            'total_departments':     total_departments,
            'total_subjects':        total_subjects,
            'total_subadmins':       total_subadmins,
            'total_uploads':         total_uploads,
            'total_downloads':       total_downloads,
            'total_questionnaires':  total_questionnaires,
            'departments':           departments,
            'department_stats':      department_stats,
            'activity_chart_data':   json.dumps(activity_chart_data),
            'department_chart_data': json.dumps(department_chart_data),
            'selected_department':   selected_department,
        }

        cache.set(stats_key, context, timeout=60)

    return render(request, 'admin_dashboard/dashboard.html', context)


# ============================================================================
# SUPERADMIN — TEACHER MANAGEMENT
# ============================================================================

@login_required
@user_passes_test(is_admin)
def manage_teachers(request):
    teachers = TeacherProfile.objects.select_related('user', 'department').filter(is_archived=False)

    search_query = request.GET.get('search', '')
    if search_query:
        teachers = teachers.filter(
            Q(user__first_name__icontains=search_query) |
            Q(user__last_name__icontains=search_query) |
            Q(employee_id__icontains=search_query)
        )

    archived_teachers = TeacherProfile.objects.select_related('user', 'department').filter(is_archived=True)
    departments = Department.objects.all().order_by('name')
    form = TeacherCreationForm()

    context = {
        'teachers':          teachers,
        'archived_teachers': archived_teachers,
        'search_query':      search_query,
        'departments':       departments,
        'form':              form,
    }
    return render(request, 'admin_dashboard/manage_teachers.html', context)


@login_required
@user_passes_test(is_admin)
def add_teacher(request):
    if request.method == 'POST':
        form = TeacherCreationForm(request.POST)
        if form.is_valid():
            plain_password = form.cleaned_data['password']
            test_email = form.cleaned_data['email']

            try:
                from django.core.mail import get_connection
                connection = get_connection()
                connection.open()
                connection.close()
            except Exception as e:
                logger.error(f"Email connection failed: {e}")
                messages.error(
                    request,
                    "Cannot add teacher: the email server is unreachable or credentials are invalid. "
                    "Please check your email settings before adding a teacher."
                )
                teachers    = TeacherProfile.objects.select_related('user', 'department').all()
                departments = Department.objects.all().order_by('name')
                return render(request, 'admin_dashboard/manage_teachers.html', {
                    'teachers':     teachers,
                    'search_query': '',
                    'departments':  departments,
                    'form':         form,
                })

            teacher = form.save()

            ActivityLog.objects.create(
                activity_type='teacher_created',
                user=request.user,
                description=f"Teacher {teacher.user.get_full_name()} ({teacher.employee_id}) was created"
            )

            email_sent = send_teacher_invite_email(teacher, plain_password)

            if not email_sent:
                user = teacher.user
                teacher.delete()
                user.delete()
                messages.error(
                    request,
                    f"Teacher was NOT added. The welcome email to {test_email} could not be sent. "
                    f"Please verify your email server settings."
                )
                teachers    = TeacherProfile.objects.select_related('user', 'department').all()
                departments = Department.objects.all().order_by('name')
                return render(request, 'admin_dashboard/manage_teachers.html', {
                    'teachers':     teachers,
                    'search_query': '',
                    'departments':  departments,
                    'form':         form,
                })

            bust_dashboard_cache()  # ✅ only after successful save + email
            messages.success(
                request,
                f"Teacher added successfully. A welcome email with login credentials "
                f"has been sent to {teacher.user.email}."
            )
            return redirect('accounts:manage_teachers')

        else:
            teachers    = TeacherProfile.objects.select_related('user', 'department').all()
            departments = Department.objects.all().order_by('name')
            return render(request, 'admin_dashboard/manage_teachers.html', {
                'teachers':     teachers,
                'search_query': '',
                'departments':  departments,
                'form':         form,
            })

    return redirect('accounts:manage_teachers')


@login_required
@user_passes_test(is_admin)
def edit_teacher(request, pk):
    teacher = get_object_or_404(TeacherProfile, pk=pk)

    if request.method == 'POST':
        form = TeacherEditForm(request.POST, instance=teacher)
        if form.is_valid():
            old_username       = teacher.user.username
            new_username       = form.cleaned_data['username']
            plain_new_password = form.cleaned_data.get('new_password', '').strip()

            username_changed = new_username != old_username
            password_changed = bool(plain_new_password)

            teacher = form.save()

            teacher.user.first_name = form.cleaned_data['first_name']
            teacher.user.last_name  = form.cleaned_data['last_name']
            teacher.user.email      = form.cleaned_data['email']
            teacher.user.username   = new_username

            if password_changed:
                teacher.user.set_password(plain_new_password)

            teacher.user.save()

            send_credentials_updated_email(
                user         = teacher.user,
                new_username = new_username if username_changed else None,
                new_password = plain_new_password if password_changed else None,
            )

            ActivityLog.objects.create(
                activity_type='teacher_updated',
                user=request.user,
                description=(
                    f"Teacher {teacher.user.get_full_name()} ({teacher.employee_id}) "
                    f"profile was updated"
                    + (" [username changed]" if username_changed else "")
                    + (" [password changed]" if password_changed else "")
                )
            )
            messages.success(request, 'Teacher updated successfully.')
            return redirect('accounts:manage_teachers')

        else:
            messages.error(request, 'Please correct the errors in the form.')
            return render(request, 'admin_dashboard/edit_teacher.html', {
                'form': form, 'teacher': teacher
            })

    else:
        form = TeacherEditForm(instance=teacher)

    return render(request, 'admin_dashboard/edit_teacher.html', {
        'form': form, 'teacher': teacher
    })


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
        bust_dashboard_cache()
        messages.success(request, 'Teacher deleted successfully')
        return redirect('accounts:manage_teachers')
    return render(request, 'admin_dashboard/delete_teacher.html', {'teacher': teacher})


@login_required
@user_passes_test(is_admin)
def archive_teacher(request, pk):
    teacher = get_object_or_404(TeacherProfile, pk=pk)
    if request.method == 'POST':
        teacher.is_archived = True
        teacher.save()
        ActivityLog.objects.create(
            activity_type='teacher_updated',
            user=request.user,
            description=f"Teacher {teacher.user.get_full_name()} ({teacher.employee_id}) was archived"
        )
        bust_dashboard_cache()
        messages.success(request, f'Teacher "{teacher.user.get_full_name()}" has been archived.')
        return redirect('accounts:manage_teachers')
    return JsonResponse({'error': 'Invalid request'}, status=400)


@login_required
@user_passes_test(is_admin)
def unarchive_teacher(request, pk):
    teacher = get_object_or_404(TeacherProfile, pk=pk, is_archived=True)
    if request.method == 'POST':
        teacher.is_archived = False
        teacher.save()
        ActivityLog.objects.create(
            activity_type='teacher_updated',
            user=request.user,
            description=f"Teacher {teacher.user.get_full_name()} ({teacher.employee_id}) was restored"
        )
        bust_dashboard_cache()
        messages.success(request, f'Teacher "{teacher.user.get_full_name()}" has been restored.')
        return redirect('accounts:manage_teachers')
    return JsonResponse({'error': 'Invalid request'}, status=400)


@login_required
@user_passes_test(is_admin)
def permanent_delete_teacher(request, pk):
    teacher = get_object_or_404(TeacherProfile, pk=pk, is_archived=True)
    if request.method == 'POST':
        teacher_name = teacher.user.get_full_name()
        employee_id  = teacher.employee_id
        user = teacher.user
        ActivityLog.objects.create(
            activity_type='teacher_deleted',
            user=request.user,
            description=f"Teacher {teacher_name} ({employee_id}) was permanently deleted"
        )
        teacher.delete()
        user.delete()
        bust_dashboard_cache()
        messages.success(request, f'Teacher "{teacher_name}" has been permanently deleted.')
        return redirect('accounts:manage_teachers')
    return JsonResponse({'error': 'Invalid request'}, status=400)


# ============================================================================
# SUPERADMIN — DEPARTMENT MANAGEMENT
# ============================================================================

@login_required
@user_passes_test(is_admin)
def manage_departments(request):
    departments = Department.objects.filter(is_archived=False).order_by('name')

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

    archived_departments = Department.objects.filter(is_archived=True).order_by('name')
    context = {'departments': departments, 'archived_departments': archived_departments, 'form': form}
    return render(request, 'admin_dashboard/manage_departments.html', context)


@login_required
@user_passes_test(is_admin)
def add_department(request):
    if request.method == 'POST':
        form = DepartmentForm(request.POST)
        if form.is_valid():
            department = form.save()
            bust_dashboard_cache()
            ActivityLog.objects.create(
                activity_type='department_created',
                user=request.user,
                description=f"Department {department.name} ({department.code}) was created"
            )
            return JsonResponse({'success': True, 'message': f'Department "{department.name}" has been added successfully!'})
        else:
            return JsonResponse({'success': False, 'errors': form.errors})
    return redirect('accounts:manage_departments')


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
            bust_dashboard_cache()
            ActivityLog.objects.create(
                activity_type='department_updated',
                user=request.user,
                description=f"Department {old_name} ({old_code}) was updated to {updated_department.name} ({updated_department.code})"
            )
            return JsonResponse({'success': True, 'message': f'Department "{updated_department.name}" has been updated successfully!'})
        else:
            return JsonResponse({'success': False, 'errors': form.errors})

    return redirect('accounts:manage_departments')


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
        bust_dashboard_cache()  # ✅
        messages.success(request, f'Department "{department_name}" has been deleted successfully!')
        return redirect('accounts:manage_departments')

    return render(request, 'admin_dashboard/delete_department.html', {'department': department})


@login_required
@user_passes_test(is_admin)
def archive_department(request, pk):
    department = get_object_or_404(Department, pk=pk)

    if request.method == 'POST':
        department.is_archived = True
        department.save()
        ActivityLog.objects.create(
            activity_type='department_updated',
            user=request.user,
            description=f"Department {department.name} ({department.code}) was archived"
        )
        bust_dashboard_cache()
        messages.success(request, f'Department "{department.name}" has been archived successfully!')
        return redirect('accounts:manage_departments')

    return JsonResponse({'error': 'Invalid request'}, status=400)


@login_required
@user_passes_test(is_admin)
def permanent_delete_department(request, pk):
    department = get_object_or_404(Department, pk=pk, is_archived=True)

    if request.method == 'POST':
        department_name = department.name
        department_code = department.code
        department.delete()
        ActivityLog.objects.create(
            activity_type='department_deleted',
            user=request.user,
            description=f"Department {department_name} ({department_code}) was permanently deleted"
        )
        bust_dashboard_cache()
        messages.success(request, f'Department "{department_name}" has been permanently deleted.')
        return redirect('accounts:manage_departments')

    return JsonResponse({'error': 'Invalid request'}, status=400)


@login_required
@user_passes_test(is_admin)
def unarchive_department(request, pk):
    department = get_object_or_404(Department, pk=pk)

    if request.method == 'POST':
        department.is_archived = False
        department.save()
        ActivityLog.objects.create(
            activity_type='department_updated',
            user=request.user,
            description=f"Department {department.name} ({department.code}) was unarchived"
        )
        bust_dashboard_cache()
        messages.success(request, f'Department "{department.name}" has been restored successfully!')
        return redirect('accounts:manage_departments')

    return JsonResponse({'error': 'Invalid request'}, status=400)


# ============================================================================
# SUPERADMIN — SUBJECT MANAGEMENT
# ============================================================================

@login_required
@user_passes_test(is_admin)
def manage_subjects(request):
    subjects          = Subject.objects.prefetch_related('departments').filter(is_archived=False)
    archived_subjects = Subject.objects.prefetch_related('departments').filter(is_archived=True)
    all_departments   = list(Department.objects.all().order_by('name'))
    form              = SubjectForm()
    form.fields['departments'].queryset = Department.objects.all().order_by('name')

    context = {
        'subjects':          subjects,
        'archived_subjects': archived_subjects,
        'all_departments':   all_departments,
        'form':              form,
    }
    return render(request, 'admin_dashboard/manage_subjects.html', context)


@login_required
@user_passes_test(is_admin)
def add_subject(request):
    if request.method == 'POST':
        form = SubjectForm(request.POST)
        if form.is_valid():
            subject = form.save()
            bust_dashboard_cache()  # ✅
            ActivityLog.objects.create(
                activity_type='subject_created',
                user=request.user,
                description=f"Subject {subject.name} ({subject.code}) was created"
            )
            messages.success(request, f'Subject "{subject.name}" ({subject.code}) has been added successfully!')
            return redirect('accounts:manage_subjects')
        else:
            messages.error(request, 'Please correct the errors in the form.')
            subjects        = Subject.objects.prefetch_related('departments').all()
            all_departments = list(Department.objects.all().order_by('name'))
            form.fields['departments'].queryset = Department.objects.all().order_by('name')
            return render(request, 'admin_dashboard/manage_subjects.html', {
                'subjects':        subjects,
                'all_departments': all_departments,
                'form':            form,
            })
    return redirect('accounts:manage_subjects')


@login_required
@user_passes_test(is_admin)
def edit_subject(request, pk):
    subject  = get_object_or_404(Subject, pk=pk)
    old_name = subject.name
    old_code = subject.code

    if request.method == 'POST':
        form = SubjectForm(request.POST, instance=subject)
        if form.is_valid():
            updated_subject = form.save()
            bust_dashboard_cache()  # ✅
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
        bust_dashboard_cache()
        messages.success(request, f'Subject "{subject_name}" ({subject_code}) has been deleted successfully!')
        return redirect('accounts:manage_subjects')
    return render(request, 'admin_dashboard/delete_subject.html', {'subject': subject})


@login_required
@user_passes_test(is_admin)
def archive_subject(request, pk):
    subject = get_object_or_404(Subject, pk=pk)
    if request.method == 'POST':
        subject.is_archived = True
        subject.save()
        ActivityLog.objects.create(
            activity_type='subject_updated',
            user=request.user,
            description=f"Subject {subject.name} ({subject.code}) was archived"
        )
        bust_dashboard_cache()
        messages.success(request, f'Subject "{subject.name}" has been archived.')
        return redirect('accounts:manage_subjects')
    return JsonResponse({'error': 'Invalid request'}, status=400)


@login_required
@user_passes_test(is_admin)
def unarchive_subject(request, pk):
    subject = get_object_or_404(Subject, pk=pk, is_archived=True)
    if request.method == 'POST':
        subject.is_archived = False
        subject.save()
        ActivityLog.objects.create(
            activity_type='subject_updated',
            user=request.user,
            description=f"Subject {subject.name} ({subject.code}) was restored"
        )
        bust_dashboard_cache()
        messages.success(request, f'Subject "{subject.name}" has been restored.')
        return redirect('accounts:manage_subjects')
    return JsonResponse({'error': 'Invalid request'}, status=400)


@login_required
@user_passes_test(is_admin)
def permanent_delete_subject(request, pk):
    subject = get_object_or_404(Subject, pk=pk, is_archived=True)
    if request.method == 'POST':
        subject_name = subject.name
        subject_code = subject.code
        ActivityLog.objects.create(
            activity_type='subject_deleted',
            user=request.user,
            description=f"Subject {subject_name} ({subject_code}) was permanently deleted"
        )
        subject.delete()
        bust_dashboard_cache()
        messages.success(request, f'Subject "{subject_name}" has been permanently deleted.')
        return redirect('accounts:manage_subjects')
    return JsonResponse({'error': 'Invalid request'}, status=400)


# ============================================================================
# SUPERADMIN — SUB-ADMIN MANAGEMENT
# ============================================================================

@login_required
@user_passes_test(is_admin)
def manage_subadmins(request):
    subadmins          = SubAdminProfile.objects.select_related('user', 'department', 'assigned_by').filter(is_archived=False)
    archived_subadmins = SubAdminProfile.objects.select_related('user', 'department', 'assigned_by').filter(is_archived=True)
    all_departments    = Department.objects.all().order_by('name')
    form               = SubAdminCreationForm()

    context = {
        'subadmins':          subadmins,
        'archived_subadmins': archived_subadmins,
        'all_departments':    all_departments,
        'form':               form,
    }
    return render(request, 'admin_dashboard/manage_subadmins.html', context)


@login_required
@user_passes_test(is_admin)
def add_subadmin(request):
    if request.method == 'POST':
        form = SubAdminCreationForm(request.POST)
        if form.is_valid():
            plain_password = form.cleaned_data['password']
            test_email = form.cleaned_data['email']

            try:
                from django.core.mail import get_connection
                connection = get_connection()
                connection.open()
                connection.close()
                logger.info(f"Email connection test successful for {test_email}")
            except Exception as e:
                logger.error(f"Email connection failed: {e}")
                messages.error(
                    request,
                    "Cannot add sub-admin: the email server is unreachable or credentials are invalid. "
                    "Please check your email settings before adding a sub-admin."
                )
                subadmins = SubAdminProfile.objects.select_related('user', 'department', 'assigned_by').all()
                all_departments = Department.objects.all().order_by('name')
                return render(request, 'admin_dashboard/manage_subadmins.html', {
                    'subadmins': subadmins,
                    'all_departments': all_departments,
                    'form': form,
                })

            subadmin = form.save(assigned_by=request.user)

            ActivityLog.objects.create(
                activity_type='subadmin_created',
                user=request.user,
                description=(
                    f"Sub-Admin {subadmin.user.get_full_name()} was created "
                    f"for department {subadmin.department.name}"
                )
            )

            email_sent = send_subadmin_invite_email(subadmin, plain_password)

            if not email_sent:
                user = subadmin.user
                subadmin.delete()
                user.delete()
                messages.error(
                    request,
                    f"Sub-Admin was NOT added. The welcome email to {test_email} could not be sent. "
                    f"Please verify your email server settings."
                )
                subadmins = SubAdminProfile.objects.select_related('user', 'department', 'assigned_by').all()
                all_departments = Department.objects.all().order_by('name')
                return render(request, 'admin_dashboard/manage_subadmins.html', {
                    'subadmins': subadmins,
                    'all_departments': all_departments,
                    'form': form,
                })

            bust_dashboard_cache()  # ✅ only after successful save + email
            messages.success(
                request,
                f"Sub-Admin added successfully. A welcome email with login credentials "
                f"has been sent to {subadmin.user.email}."
            )
            return redirect('accounts:manage_subadmins')

        else:
            subadmins = SubAdminProfile.objects.select_related('user', 'department', 'assigned_by').all()
            all_departments = Department.objects.all().order_by('name')
            return render(request, 'admin_dashboard/manage_subadmins.html', {
                'subadmins': subadmins,
                'all_departments': all_departments,
                'form': form,
            })

    return redirect('accounts:manage_subadmins')


@login_required
@user_passes_test(is_admin)
def edit_subadmin(request, pk):
    subadmin = get_object_or_404(SubAdminProfile, pk=pk)

    if request.method == 'POST':
        first_name   = request.POST.get('first_name', '').strip()
        last_name    = request.POST.get('last_name', '').strip()
        email        = request.POST.get('email', '').strip()
        username     = request.POST.get('username', '').strip()
        new_password = request.POST.get('new_password', '').strip()
        dept_pk      = request.POST.get('department', '').strip()
        is_active    = request.POST.get('is_active') == 'on'

        errors = []

        if not first_name:
            errors.append('First name is required.')
        if not last_name:
            errors.append('Last name is required.')
        if not email:
            errors.append('Email address is required.')
        elif '@' not in email:
            errors.append('Enter a valid email address.')
        if not username:
            errors.append('Username is required.')
        if not dept_pk:
            errors.append('Please select a department.')

        from django.contrib.auth.models import User as _User

        if username and _User.objects.filter(username=username).exclude(pk=subadmin.user.pk).exists():
            errors.append('That username is already in use by another account.')

        if email and _User.objects.filter(email=email).exclude(pk=subadmin.user.pk).exists():
            errors.append('That email address is already in use by another account.')

        if errors:
            for error in errors:
                messages.error(request, error)
            return redirect('accounts:manage_subadmins')

        user = subadmin.user
        old_username     = user.username
        username_changed = username != old_username
        password_changed = bool(new_password)

        user.first_name = first_name
        user.last_name  = last_name
        user.email      = email
        user.username   = username

        if password_changed:
            user.set_password(new_password)

        user.save()

        try:
            subadmin.department = Department.objects.get(pk=dept_pk)
        except Department.DoesNotExist:
            messages.error(request, 'Selected department does not exist.')
            return redirect('accounts:manage_subadmins')

        subadmin.is_active = is_active
        subadmin.save()

        if username_changed or password_changed:
            send_credentials_updated_email(
                user         = user,
                new_username = username if username_changed else None,
                new_password = new_password if password_changed else None,
            )

        ActivityLog.objects.create(
            activity_type='subadmin_updated',
            user=request.user,
            description=(
                f"Sub-Admin {user.get_full_name()} was updated"
                + (" [username changed]" if username_changed else "")
                + (" [password changed]" if password_changed else "")
            )
        )

        messages.success(request, f'{user.get_full_name()} has been updated successfully.')

    return redirect('accounts:manage_subadmins')


@login_required
@user_passes_test(is_admin)
def delete_subadmin(request, pk):
    subadmin = get_object_or_404(SubAdminProfile, pk=pk)
    if request.method == 'POST':
        subadmin.user.delete()
        bust_dashboard_cache()
        messages.success(request, 'Sub-admin removed successfully.')
    return redirect('accounts:manage_subadmins')


@login_required
@user_passes_test(is_admin)
def archive_subadmin(request, pk):
    subadmin = get_object_or_404(SubAdminProfile, pk=pk)
    if request.method == 'POST':
        subadmin.is_archived = True
        subadmin.is_active = False
        subadmin.save()
        ActivityLog.objects.create(
            activity_type='subadmin_updated',
            user=request.user,
            description=f"Sub-admin {subadmin.user.get_full_name()} was archived"
        )
        bust_dashboard_cache()
        messages.success(request, f'Sub-admin "{subadmin.user.get_full_name()}" has been archived.')
        return redirect('accounts:manage_subadmins')
    return JsonResponse({'error': 'Invalid request'}, status=400)


@login_required
@user_passes_test(is_admin)
def unarchive_subadmin(request, pk):
    subadmin = get_object_or_404(SubAdminProfile, pk=pk, is_archived=True)
    if request.method == 'POST':
        subadmin.is_archived = False
        subadmin.is_active = True
        subadmin.save()
        ActivityLog.objects.create(
            activity_type='subadmin_updated',
            user=request.user,
            description=f"Sub-admin {subadmin.user.get_full_name()} was restored"
        )
        bust_dashboard_cache()
        messages.success(request, f'Sub-admin "{subadmin.user.get_full_name()}" has been restored.')
        return redirect('accounts:manage_subadmins')
    return JsonResponse({'error': 'Invalid request'}, status=400)


@login_required
@user_passes_test(is_admin)
def permanent_delete_subadmin(request, pk):
    subadmin = get_object_or_404(SubAdminProfile, pk=pk, is_archived=True)
    if request.method == 'POST':
        subadmin_name = subadmin.user.get_full_name()
        ActivityLog.objects.create(
            activity_type='subadmin_deleted',
            user=request.user,
            description=f"Sub-admin {subadmin_name} was permanently deleted"
        )
        subadmin.user.delete()
        bust_dashboard_cache()
        messages.success(request, f'Sub-admin "{subadmin_name}" has been permanently deleted.')
        return redirect('accounts:manage_subadmins')
    return JsonResponse({'error': 'Invalid request'}, status=400)


# ============================================================================
# SUB-ADMIN DASHBOARD
# ============================================================================

@login_required
@user_passes_test(is_subadmin)
def subadmin_dashboard(request):
    subadmin   = request.user.subadmin_profile
    department = subadmin.department

    total_teachers  = TeacherProfile.objects.filter(department=department).count()
    active_teachers = TeacherProfile.objects.filter(department=department, is_active=True).count()

    recent_activities = ActivityLog.objects.filter(
        user=request.user
    ).exclude(activity_type='user_login').order_by('-created_at')[:15]

    context = {
        'subadmin':          subadmin,
        'department':        department,
        'total_teachers':    total_teachers,
        'active_teachers':   active_teachers,
        'recent_activities': recent_activities,
    }
    return render(request, 'subadmin_dashboard/dashboard.html', context)


# ============================================================================
# SUB-ADMIN — TEACHER MANAGEMENT
# ============================================================================

@login_required
@user_passes_test(is_subadmin)
def subadmin_manage_teachers(request):
    department = request.user.subadmin_profile.department

    teachers = TeacherProfile.objects.select_related('user', 'department').filter(
        department=department, is_archived=False
    )

    search_query = request.GET.get('search', '')
    if search_query:
        teachers = teachers.filter(
            Q(user__first_name__icontains=search_query) |
            Q(user__last_name__icontains=search_query) |
            Q(employee_id__icontains=search_query)
        )

    archived_teachers = TeacherProfile.objects.select_related('user').filter(
        department=department, is_archived=True
    )

    context = {
        'teachers':          teachers,
        'archived_teachers': archived_teachers,
        'search_query':      search_query,
        'department':        department,
    }
    return render(request, 'subadmin_dashboard/manage_teachers.html', context)


@login_required
@user_passes_test(is_subadmin)
def subadmin_add_teacher(request):
    department = request.user.subadmin_profile.department

    if request.method == 'POST':
        form = SubAdminTeacherCreationForm(request.POST, department=department)
        if form.is_valid():
            plain_password = form.cleaned_data['password']
            test_email     = form.cleaned_data['email']

            try:
                from django.core.mail import get_connection
                connection = get_connection()
                connection.open()
                connection.close()
            except Exception as e:
                logger.error(f"Email connection failed: {e}")
                return JsonResponse({
                    'success': False,
                    'errors': {
                        '__all__': [
                            "Cannot add teacher: the email server is unreachable. "
                            "Please check your email settings."
                        ]
                    }
                })

            teacher = form.save()

            ActivityLog.objects.create(
                activity_type='teacher_created',
                user=request.user,
                description=(
                    f"Teacher {teacher.user.get_full_name()} ({teacher.employee_id}) "
                    f"was added to {department.name} by Sub-Admin {request.user.get_full_name()}"
                )
            )

            email_sent = send_teacher_invite_email(teacher, plain_password)

            if not email_sent:
                user = teacher.user
                teacher.delete()
                user.delete()
                return JsonResponse({
                    'success': False,
                    'errors': {
                        '__all__': [
                            f"Teacher was NOT added. The welcome email to {test_email} "
                            f"could not be sent. Please verify your email server settings."
                        ]
                    }
                })

            bust_dashboard_cache()
            return JsonResponse({
                'success': True,
                'message': f"Teacher added successfully. A welcome email has been sent to {teacher.user.email}."
            })

        else:
            return JsonResponse({'success': False, 'errors': form.errors})

    return redirect('accounts:subadmin_manage_teachers')


@login_required
@user_passes_test(is_subadmin)
def subadmin_edit_teacher(request, pk):
    department = request.user.subadmin_profile.department
    teacher    = get_object_or_404(TeacherProfile, pk=pk, department=department)

    if request.method == 'POST':
        form = SubAdminTeacherEditForm(request.POST, instance=teacher)
        if form.is_valid():
            old_username       = teacher.user.username
            new_username       = form.cleaned_data['username']
            plain_new_password = form.cleaned_data.get('new_password', '').strip()

            username_changed = new_username != old_username
            password_changed = bool(plain_new_password)

            teacher = form.save()
            teacher.user.first_name = form.cleaned_data['first_name']
            teacher.user.last_name  = form.cleaned_data['last_name']
            teacher.user.email      = form.cleaned_data['email']
            teacher.user.username   = new_username

            if password_changed:
                teacher.user.set_password(plain_new_password)

            teacher.user.save()

            send_credentials_updated_email(
                user         = teacher.user,
                new_username = new_username if username_changed else None,
                new_password = plain_new_password if password_changed else None,
            )

            ActivityLog.objects.create(
                activity_type='teacher_updated',
                user=request.user,
                description=(
                    f"Teacher {teacher.user.get_full_name()} ({teacher.employee_id}) "
                    f"was updated by Sub-Admin {request.user.get_full_name()}"
                    + (" [username changed]" if username_changed else "")
                    + (" [password changed]" if password_changed else "")
                )
            )
            return JsonResponse({'success': True, 'message': 'Teacher updated successfully.'})

        else:
            return JsonResponse({'success': False, 'errors': form.errors})

    return redirect('accounts:subadmin_manage_teachers')


@login_required
@user_passes_test(is_subadmin)
def subadmin_delete_teacher(request, pk):
    department = request.user.subadmin_profile.department
    teacher    = get_object_or_404(TeacherProfile, pk=pk, department=department)

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
        bust_dashboard_cache()
        messages.success(request, 'Teacher deleted successfully.')
        return redirect('accounts:subadmin_manage_teachers')

    return render(request, 'subadmin_dashboard/delete_teacher.html', {
        'teacher': teacher, 'department': department
    })


@login_required
@user_passes_test(is_subadmin)
def subadmin_archive_teacher(request, pk):
    department = request.user.subadmin_profile.department
    teacher    = get_object_or_404(TeacherProfile, pk=pk, department=department, is_archived=False)
    if request.method == 'POST':
        teacher.is_archived = True
        teacher.user.is_active = False
        teacher.user.save()
        teacher.save()
        ActivityLog.objects.create(
            activity_type='teacher_archived',
            user=request.user,
            description=(
                f"Teacher {teacher.user.get_full_name()} ({teacher.employee_id}) "
                f"was archived in {department.name} by Sub-Admin {request.user.get_full_name()}"
            )
        )
        bust_dashboard_cache()
        return JsonResponse({'success': True, 'message': 'Teacher archived successfully.'})
    return JsonResponse({'error': 'Invalid request'}, status=400)


@login_required
@user_passes_test(is_subadmin)
def subadmin_unarchive_teacher(request, pk):
    department = request.user.subadmin_profile.department
    teacher    = get_object_or_404(TeacherProfile, pk=pk, department=department, is_archived=True)
    if request.method == 'POST':
        teacher.is_archived = False
        teacher.user.is_active = True
        teacher.user.save()
        teacher.save()
        ActivityLog.objects.create(
            activity_type='teacher_restored',
            user=request.user,
            description=(
                f"Teacher {teacher.user.get_full_name()} ({teacher.employee_id}) "
                f"was restored in {department.name} by Sub-Admin {request.user.get_full_name()}"
            )
        )
        bust_dashboard_cache()
        return JsonResponse({'success': True, 'message': 'Teacher restored successfully.'})
    return JsonResponse({'error': 'Invalid request'}, status=400)


@login_required
@user_passes_test(is_subadmin)
def subadmin_permanent_delete_teacher(request, pk):
    department = request.user.subadmin_profile.department
    teacher    = get_object_or_404(TeacherProfile, pk=pk, department=department, is_archived=True)
    if request.method == 'POST':
        teacher_name = f"{teacher.user.get_full_name()} ({teacher.employee_id})"
        user = teacher.user
        ActivityLog.objects.create(
            activity_type='teacher_deleted',
            user=request.user,
            description=(
                f"Teacher {teacher_name} was permanently deleted from {department.name} "
                f"by Sub-Admin {request.user.get_full_name()}"
            )
        )
        teacher.delete()
        user.delete()
        bust_dashboard_cache()
        return JsonResponse({'success': True, 'message': 'Teacher permanently deleted.'})
    return JsonResponse({'error': 'Invalid request'}, status=400)


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

    my_uploads      = teacher.questionnaires.count()
    total_downloads = Download.objects.filter(questionnaire__uploader=teacher).count()

    current_month = timezone.now().month
    current_year  = timezone.now().year
    uploads_this_month = teacher.questionnaires.filter(
        uploaded_at__month=current_month,
        uploaded_at__year=current_year
    ).count()

    upload_stats      = get_teacher_upload_stats(teacher)
    top_downloads     = Questionnaire.objects.filter(
        uploader=teacher
    ).annotate(download_count=Count('downloads')).order_by('-download_count')[:3]
    recent_activities = get_teacher_recent_activities(teacher)[:15]

    context = {
        'teacher':            teacher,
        'my_uploads':         my_uploads,
        'total_downloads':    total_downloads,
        'uploads_this_month': uploads_this_month,
        'upload_stats':       upload_stats,
        'top_downloads':      top_downloads,
        'recent_activities':  recent_activities,
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
        activities.append({
            'type':      'upload',
            'message':   f'You uploaded "{quest.title}"',
            'timestamp': quest.uploaded_at,
        })

    recent_downloads = Download.objects.filter(
        questionnaire__uploader=teacher
    ).select_related('user', 'questionnaire').order_by('-downloaded_at')[:5]

    for download in recent_downloads:
        if download.user and download.user != teacher.user:
            activities.append({
                'type':      'download',
                'message':   f'{download.user.get_full_name()} downloaded your "{download.questionnaire.title}"',
                'timestamp': download.downloaded_at,
            })

    activity_logs = ActivityLog.objects.filter(
        user=teacher.user
    ).exclude(activity_type='user_login').order_by('-created_at')[:5]

    for log in activity_logs:
        activities.append({
            'type':      'system',
            'message':   log.description,
            'timestamp': log.created_at,
        })

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

        from django.core.cache import cache
        cache.delete(f'activities_{request.user.id}_{"super" if request.user.is_staff else "other"}')
        cache.delete(f'unread_count_{request.user.id}_{"super" if request.user.is_staff else "other"}')

        return JsonResponse({'success': True, 'message': f'{updated_count} notifications marked as read'})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


# ============================================================================
# CHART HELPERS
# ============================================================================

def get_activity_chart_data(department_filter='all'):
    from questionnaires.models import Questionnaire, Download

    today      = timezone.now().date()
    date_range = [today - timedelta(days=i) for i in range(6, -1, -1)]
    labels     = [d.strftime('%b %d') for d in date_range]
    uploads    = []
    downloads  = []

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


# ============================================================================
# SUB-ADMIN — SUBJECT MANAGEMENT
# ============================================================================

@login_required
@user_passes_test(is_subadmin)
def subadmin_manage_subjects(request):
    department   = request.user.subadmin_profile.department
    subjects     = Subject.objects.filter(departments=department, is_archived=False).order_by('code')
    search_query = request.GET.get('search', '')

    if search_query:
        subjects = subjects.filter(
            Q(name__icontains=search_query) |
            Q(code__icontains=search_query)
        )

    archived_subjects = Subject.objects.filter(departments=department, is_archived=True).order_by('code')

    from .forms import SubjectForm
    form = SubjectForm()

    context = {
        'subjects':          subjects,
        'archived_subjects': archived_subjects,
        'search_query':      search_query,
        'department':        department,
        'form':              form,
    }
    return render(request, 'subadmin_dashboard/manage_subjects.html', context)


@login_required
@user_passes_test(is_subadmin)
def subadmin_add_subject(request):
    department = request.user.subadmin_profile.department

    if request.method == 'POST':
        code        = request.POST.get('code', '').strip().upper()
        name        = request.POST.get('name', '').strip()
        description = request.POST.get('description', '').strip()

        errors = {}
        if not code:
            errors['code'] = ['Subject code is required.']
        elif Subject.objects.filter(code=code, departments=department).exists():
            errors['code'] = [f'A subject with code "{code}" already exists in {department.code}.']
        if not name:
            errors['name'] = ['Subject name is required.']

        if errors:
            return JsonResponse({'success': False, 'errors': errors})

        subject = Subject.objects.create(code=code, name=name, description=description)
        subject.departments.add(department)
        ActivityLog.objects.create(
            activity_type='subject_created',
            user=request.user,
            description=(
                f"Subject {subject.name} ({subject.code}) was created "
                f"and added to {department.name} by Sub-Admin {request.user.get_full_name()}"
            )
        )
        bust_dashboard_cache()
        return JsonResponse({'success': True, 'message': f'Subject "{subject.name}" ({subject.code}) added successfully.'})

    return redirect('accounts:subadmin_manage_subjects')


@login_required
@user_passes_test(is_subadmin)
def subadmin_edit_subject(request, pk):
    department = request.user.subadmin_profile.department
    subject    = get_object_or_404(Subject, pk=pk, departments=department)

    if request.method == 'POST':
        code        = request.POST.get('code', '').strip().upper()
        name        = request.POST.get('name', '').strip()
        description = request.POST.get('description', '').strip()

        errors = {}
        if not code:
            errors['code'] = ['Subject code is required.']
        elif Subject.objects.filter(code=code, departments=department).exclude(pk=pk).exists():
            errors['code'] = [f'A subject with code "{code}" already exists in {department.code}.']
        if not name:
            errors['name'] = ['Subject name is required.']

        if errors:
            return JsonResponse({'success': False, 'errors': errors})

        old_code = subject.code
        subject.code        = code
        subject.name        = name
        subject.description = description
        subject.save()
        ActivityLog.objects.create(
            activity_type='subject_updated',
            user=request.user,
            description=(
                f"Subject {old_code} updated to {subject.name} ({subject.code}) "
                f"in {department.name} by Sub-Admin {request.user.get_full_name()}"
            )
        )
        bust_dashboard_cache()
        return JsonResponse({'success': True, 'message': f'Subject "{subject.name}" updated successfully.'})

    return redirect('accounts:subadmin_manage_subjects')


@login_required
@user_passes_test(is_subadmin)
def subadmin_delete_subject(request, pk):
    department = request.user.subadmin_profile.department
    subject    = get_object_or_404(Subject, pk=pk, departments=department)

    if request.method == 'POST':
        subject_name = subject.name
        subject_code = subject.code

        other_departments = subject.departments.exclude(pk=department.pk)
        if other_departments.exists():
            subject.departments.remove(department)
            action = f"unlinked from {department.name}"
        else:
            subject.delete()
            action = "deleted"

        ActivityLog.objects.create(
            activity_type='subject_deleted',
            user=request.user,
            description=(
                f"Subject {subject_name} ({subject_code}) was {action} "
                f"by Sub-Admin {request.user.get_full_name()}"
            )
        )
        bust_dashboard_cache()
        messages.success(request, f'Subject "{subject_name}" ({subject_code}) removed successfully.')

    return redirect('accounts:subadmin_manage_subjects')


@login_required
@user_passes_test(is_subadmin)
def subadmin_archive_subject(request, pk):
    department = request.user.subadmin_profile.department
    subject    = get_object_or_404(Subject, pk=pk, departments=department, is_archived=False)
    if request.method == 'POST':
        subject.is_archived = True
        subject.save()
        ActivityLog.objects.create(
            activity_type='subject_archived',
            user=request.user,
            description=(
                f"Subject {subject.name} ({subject.code}) was archived in {department.name} "
                f"by Sub-Admin {request.user.get_full_name()}"
            )
        )
        bust_dashboard_cache()
        return JsonResponse({'success': True, 'message': f'Subject "{subject.name}" archived successfully.'})
    return JsonResponse({'error': 'Invalid request'}, status=400)


@login_required
@user_passes_test(is_subadmin)
def subadmin_unarchive_subject(request, pk):
    department = request.user.subadmin_profile.department
    subject    = get_object_or_404(Subject, pk=pk, departments=department, is_archived=True)
    if request.method == 'POST':
        subject.is_archived = False
        subject.save()
        ActivityLog.objects.create(
            activity_type='subject_restored',
            user=request.user,
            description=(
                f"Subject {subject.name} ({subject.code}) was restored in {department.name} "
                f"by Sub-Admin {request.user.get_full_name()}"
            )
        )
        bust_dashboard_cache()
        return JsonResponse({'success': True, 'message': f'Subject "{subject.name}" restored successfully.'})
    return JsonResponse({'error': 'Invalid request'}, status=400)


@login_required
@user_passes_test(is_subadmin)
def subadmin_permanent_delete_subject(request, pk):
    department = request.user.subadmin_profile.department
    subject    = get_object_or_404(Subject, pk=pk, departments=department, is_archived=True)
    if request.method == 'POST':
        subject_name = subject.name
        subject_code = subject.code
        subject.delete()
        ActivityLog.objects.create(
            activity_type='subject_deleted',
            user=request.user,
            description=(
                f"Subject {subject_name} ({subject_code}) was permanently deleted from {department.name} "
                f"by Sub-Admin {request.user.get_full_name()}"
            )
        )
        bust_dashboard_cache()
        return JsonResponse({'success': True, 'message': f'Subject "{subject_name}" permanently deleted.'})
    return JsonResponse({'error': 'Invalid request'}, status=400)


# ============================================================================
# SUB-ADMIN — BROWSE QUESTIONNAIRES
# ============================================================================

@login_required
@user_passes_test(is_subadmin)
def subadmin_browse_questionnaires(request):
    from questionnaires.models import Questionnaire
    from django.core.paginator import Paginator

    department = request.user.subadmin_profile.department

    questionnaires = Questionnaire.objects.filter(
        uploader__department=department
    ).select_related('subject', 'uploader__user', 'department')

    subjects = Subject.objects.filter(departments=department).order_by('code')
    teachers = TeacherProfile.objects.filter(
        department=department, is_active=True
    ).select_related('user').order_by('user__last_name')

    selected_subject = request.GET.get('subject', '')
    selected_teacher = request.GET.get('teacher', '')
    exam_type        = request.GET.get('exam_type', '')
    search_query     = request.GET.get('search', '')

    if selected_subject:
        questionnaires = questionnaires.filter(subject_id=selected_subject)
    if selected_teacher:
        questionnaires = questionnaires.filter(uploader_id=selected_teacher)
    if exam_type:
        questionnaires = questionnaires.filter(exam_type=exam_type)
    if search_query:
        questionnaires = questionnaires.filter(
            Q(title__icontains=search_query) |
            Q(description__icontains=search_query) |
            Q(subject__name__icontains=search_query) |
            Q(subject__code__icontains=search_query)
        )

    paginator   = Paginator(questionnaires, 9)
    page_number = request.GET.get('page', 1)
    page_obj    = paginator.get_page(page_number)

    context = {
        'page_obj':          page_obj,
        'department':        department,
        'subjects':          subjects,
        'teachers':          teachers,
        'selected_subject':  selected_subject,
        'selected_teacher':  selected_teacher,
        'exam_type':         exam_type,
        'search_query':      search_query,
        'exam_type_choices': Questionnaire.EXAM_TYPE_CHOICES,
    }
    return render(request, 'subadmin_dashboard/browse_questionnaires.html', context)


from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.models import User

@login_required
def update_profile(request):
    """Allow users to update their own profile information"""
    if request.method == 'POST':
        user       = request.user
        first_name = request.POST.get('first_name', '').strip()
        last_name  = request.POST.get('last_name', '').strip()
        email      = request.POST.get('email', '').strip()

        errors = []

        if not first_name:
            errors.append('First name is required.')
        if not last_name:
            errors.append('Last name is required.')
        if not email:
            errors.append('Email address is required.')
        elif '@' not in email:
            errors.append('Enter a valid email address.')
        elif User.objects.filter(email=email).exclude(pk=user.pk).exists():
            errors.append('This email is already in use by another account.')

        if errors:
            for error in errors:
                messages.error(request, error)
            return redirect(request.META.get('HTTP_REFERER', 'home'))

        user.first_name = first_name
        user.last_name  = last_name
        user.email      = email
        user.save()

        if hasattr(user, 'teacher_profile'):
            phone = request.POST.get('phone', '').strip()
            if phone:
                user.teacher_profile.phone = phone
                user.teacher_profile.save()

        ActivityLog.objects.create(
            activity_type='profile_updated',
            user=user,
            description=f"{user.get_full_name()} updated their profile information"
        )

        messages.success(request, 'Your profile has been updated successfully.')
        return redirect(request.META.get('HTTP_REFERER', 'home'))

    return redirect('home')


@login_required
def change_credentials(request):
    """Allow users to change their own username and/or password"""
    if request.method == 'POST':
        user             = request.user
        new_username     = request.POST.get('username', '').strip()
        current_password = request.POST.get('current_password', '')
        new_password     = request.POST.get('new_password', '').strip()
        confirm_password = request.POST.get('confirm_password', '').strip()

        errors  = []
        changes = []

        if not user.check_password(current_password):
            errors.append('Current password is incorrect.')

        username_changed = False
        if new_username and new_username != user.username:
            if User.objects.filter(username=new_username).exclude(pk=user.pk).exists():
                errors.append('This username is already taken.')
            else:
                username_changed = True
                changes.append(f"username changed to '{new_username}'")

        password_changed = False
        if new_password:
            if len(new_password) < 8:
                errors.append('Password must be at least 8 characters long.')
            elif new_password != confirm_password:
                errors.append('New passwords do not match.')
            else:
                if not any(char.isupper() for char in new_password):
                    errors.append('Password must contain at least one uppercase letter.')
                if not any(char.isdigit() for char in new_password):
                    errors.append('Password must contain at least one number.')
                if not any(char in '!@#$%^&*()_+-=[]{}|;:,.<>?' for char in new_password):
                    errors.append('Password must contain at least one special character.')
                else:
                    password_changed = True
                    changes.append("password changed")

        if errors:
            for error in errors:
                messages.error(request, error)
            return redirect(request.META.get('HTTP_REFERER', 'home'))

        if username_changed:
            user.username = new_username

        if password_changed:
            user.set_password(new_password)

        if username_changed or password_changed:
            user.save()

            if password_changed:
                update_session_auth_hash(request, user)

            user_role = "Administrator" if user.is_staff else "Teacher"
            if hasattr(user, 'subadmin_profile'):
                user_role = "Sub-Admin"

            ActivityLog.objects.create(
                activity_type='credentials_updated',
                user=user,
                description=f"{user_role} {user.get_full_name()} updated their login credentials: {', '.join(changes)}"
            )

            try:
                changes_list = "\n".join([f"  • {change}" for change in changes])
                send_mail(
                    subject="Your Login Credentials Have Been Updated",
                    message=f"""Hello {user.get_full_name()},

Your login credentials were successfully updated with the following changes:

{changes_list}

If you did not make these changes, please contact your administrator immediately.

— System Administration""",
                    from_email=settings.DEFAULT_FROM_EMAIL,
                    recipient_list=[user.email],
                    fail_silently=True,
                )
            except Exception as e:
                logger.error(f"Failed to send credential update email to {user.email}: {e}")

            messages.success(request, f'Your login credentials have been updated successfully: {", ".join(changes)}.')
        else:
            messages.info(request, 'No changes were made to your credentials.')

        return redirect(request.META.get('HTTP_REFERER', 'home'))

    return redirect('home')