# ============================================================================
# FILE: accounts/views.py
# ============================================================================

from django.utils import timezone
from datetime import timedelta
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import login, logout, authenticate
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib import messages
from django.db.models import Q
from .models import ActivityLog, TeacherProfile, Department, Subject
from .forms import TeacherCreationForm, TeacherEditForm, DepartmentForm, SubjectForm
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from .forms import DepartmentForm, SubjectForm 


import logging
logger = logging.getLogger(__name__)

def is_admin(user):
    return user.is_authenticated and user.is_staff

def log_activity(activity_type, description, user=None, metadata=None):
    """Helper function to log activities"""
    from .models import ActivityLog
    ActivityLog.objects.create(
        activity_type=activity_type,
        user=user,
        description=description,
        metadata=metadata or {}
    )

def log_teacher_activity(teacher, action, user=None):
    """Log teacher-related activities"""
    description = f"Teacher {teacher.user.get_full_name()} ({teacher.employee_id}) was {action}"
    log_activity(f'teacher_{action}', description, user)

def log_department_activity(department, action, user=None):
    """Log department-related activities"""
    description = f"Department {department.name} ({department.code}) was {action}"
    log_activity(f'department_{action}', description, user)

def log_subject_activity(subject, action, user=None):
    """Log subject-related activities"""
    description = f"Subject {subject.name} ({subject.code}) was {action}"
    log_activity(f'subject_{action}', description, user)

# accounts/views.py - Updated login_view function

def login_view(request):
    if request.user.is_authenticated:
        return redirect('home')
    
    if request.method == 'POST':
        username = request.POST.get('username')
        password = request.POST.get('password')
        user = authenticate(request, username=username, password=password)
        
        if user is not None:
            login(request, user)
            
            # LOG LOGIN ACTIVITY with role information
            from .models import ActivityLog
            user_role = "Administrator" if user.is_staff else "Teacher"
            ActivityLog.objects.create(
                activity_type='user_login',
                user=user,
                description=f"{user_role} {user.get_full_name()} logged in to the system"
            )
            
            if user.is_staff:
                return redirect('accounts:admin_dashboard')
            else:
                return redirect('accounts:teacher_dashboard')
        else:
            messages.error(request, 'Invalid username or password')
    
    return render(request, 'accounts/login.html')

@login_required
def logout_view(request):
    logout(request)
    messages.success(request, 'Logged out successfully')
    return redirect('home')

@login_required
@user_passes_test(is_admin)
def admin_dashboard(request):
    from questionnaires.models import Questionnaire, Download
    from django.db.models import Count
    from django.db.models.functions import TruncDate
    import json
    
    # Basic stats
    total_teachers = TeacherProfile.objects.count()
    active_teachers = TeacherProfile.objects.filter(is_active=True).count()
    total_departments = Department.objects.count()
    total_subjects = Subject.objects.count()
    
    # Get department filter if provided
    selected_department = request.GET.get('department', 'all')
    
    # Filter questionnaires by department if selected
    questionnaires_qs = Questionnaire.objects.all()
    if selected_department != 'all':
        questionnaires_qs = questionnaires_qs.filter(department_id=selected_department)
    
    # Activity stats
    total_uploads = questionnaires_qs.count()
    total_downloads = Download.objects.filter(
        questionnaire__in=questionnaires_qs
    ).count() if selected_department != 'all' else Download.objects.count()
    total_questionnaires = questionnaires_qs.count()
    
    # Get all departments for dropdown
    departments = Department.objects.all().order_by('name')
    
    # Department statistics for table
    department_stats = []
    max_downloads = 1  # For calculating popularity percentage
    
    for dept in departments:
        dept_questionnaires = Questionnaire.objects.filter(department=dept)
        upload_count = dept_questionnaires.count()
        download_count = Download.objects.filter(
            questionnaire__in=dept_questionnaires
        ).count()
        
        if download_count > max_downloads:
            max_downloads = download_count
        
        department_stats.append({
            'department_name': dept.name,
            'questionnaire_count': upload_count,
            'upload_count': upload_count,
            'download_count': download_count,
            'popularity_percent': 0  # Will calculate after loop
        })
    
    # Calculate popularity percentages
    for stat in department_stats:
        if max_downloads > 0:
            stat['popularity_percent'] = int((stat['download_count'] / max_downloads) * 100)
    
    # Sort by questionnaire count descending
    department_stats.sort(key=lambda x: x['questionnaire_count'], reverse=True)
    
    # Activity chart data (last 7 days)
    activity_chart_data = get_activity_chart_data(selected_department)
    
    # Department distribution chart data
    department_chart_data = get_department_chart_data()
    
    context = {
        'total_teachers': total_teachers,
        'active_teachers': active_teachers,
        'total_departments': total_departments,
        'total_subjects': total_subjects,
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
            logger.info(f"Teacher created: {teacher.user.get_full_name()}")
            
            # DIRECT ACTIVITY LOGGING - SIMPLE VERSION
            try:
                from .models import ActivityLog
                logger.info(f"Before creating activity - ActivityLog model imported")
                
                activity = ActivityLog.objects.create(
                    activity_type='teacher_created',
                    user=request.user,
                    description=f"Teacher {teacher.user.get_full_name()} ({teacher.employee_id}) was created"
                )
                logger.info(f"Activity created: {activity.id} - {activity.description}")
                logger.info(f"Total activities now: {ActivityLog.objects.count()}")
                
            except Exception as e:
                logger.error(f"Error creating activity: {e}")
            
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
            
            # LOG ACTIVITY
            from .models import ActivityLog
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
        
        # LOG ACTIVITY BEFORE DELETING
        from .models import ActivityLog
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

@login_required
@user_passes_test(is_admin)
def manage_departments(request):
    departments = Department.objects.all()
    
    if request.method == 'POST':
        form = DepartmentForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, 'Department added successfully')
            return redirect('accounts:manage_departments')
    else:
        form = DepartmentForm()
    
    context = {'departments': departments, 'form': form}
    return render(request, 'admin_dashboard/manage_departments.html', context)

@login_required
@user_passes_test(is_admin)
def edit_department(request, pk):
    department = get_object_or_404(Department, pk=pk)
    
    if request.method == 'POST':
        form = DepartmentForm(request.POST, instance=department)
        if form.is_valid():
            department = form.save()
            
            # LOG ACTIVITY
            from .models import ActivityLog
            ActivityLog.objects.create(
                activity_type='department_updated',
                user=request.user,
                description=f"Department {department.name} ({department.code}) was updated"
            )
            
            messages.success(request, 'Department updated successfully')
            return redirect('accounts:manage_departments')
    else:
        form = DepartmentForm(instance=department)
    
    return render(request, 'admin_dashboard/edit_department.html', {'form': form, 'department': department})

@login_required
@user_passes_test(is_admin)
def delete_department(request, pk):
    department = get_object_or_404(Department, pk=pk)
    if request.method == 'POST':
        department_name = f"{department.name} ({department.code})"
        
        # LOG ACTIVITY BEFORE DELETING
        from .models import ActivityLog
        ActivityLog.objects.create(
            activity_type='department_deleted',
            user=request.user,
            description=f"Department {department_name} was deleted"
        )
        
        department.delete()
        messages.success(request, 'Department deleted successfully')
        return redirect('accounts:manage_departments')
    
    return render(request, 'admin_dashboard/delete_department.html', {'department': department})

@login_required
@user_passes_test(is_admin)
def delete_subject(request, pk):
    subject = get_object_or_404(Subject, pk=pk)
    
    print("=== DELETE SUBJECT START ===")
    print(f"Subject to delete: {subject.name} ({subject.code})")
    print(f"Request method: {request.method}")
    print(f"User: {request.user}")
    
    if request.method == 'POST':
        print("POST request confirmed - proceeding with deletion")
        
        subject_name = f"{subject.name} ({subject.code})"
        
        # LOG ACTIVITY BEFORE DELETING
        try:
            from .models import ActivityLog
            print("1. ActivityLog model imported successfully")
            
            # Check current activity count
            current_count = ActivityLog.objects.count()
            print(f"2. Current ActivityLog count: {current_count}")
            
            # Create the activity
            print("3. Creating activity...")
            activity = ActivityLog.objects.create(
                activity_type='subject_deleted',
                user=request.user,
                description=f"Subject {subject_name} was deleted"
            )
            print(f"4. Activity created successfully! ID: {activity.id}")
            print(f"5. Activity description: {activity.description}")
            
            # Verify it was saved
            new_count = ActivityLog.objects.count()
            print(f"6. New ActivityLog count: {new_count}")
            
        except Exception as e:
            print(f"ERROR creating activity: {str(e)}")
            import traceback
            traceback.print_exc()
        
        # Delete the subject
        print("7. Deleting subject from database...")
        subject.delete()
        print("8. Subject deleted successfully")
        
        messages.success(request, 'Subject deleted successfully')
        print("9. Redirecting to manage_subjects")
        return redirect('accounts:manage_subjects')
    
    print("Rendering delete confirmation page")
    return render(request, 'admin_dashboard/delete_subject.html', {'subject': subject})

@login_required
@user_passes_test(is_admin)
def manage_subjects(request):
    subjects = Subject.objects.prefetch_related('departments').all()
    
    if request.method == 'POST':
        form = SubjectForm(request.POST)
        if form.is_valid():
            subject = form.save()
            
            print("=== SUBJECT CREATION DEBUG ===")
            print(f"Subject created: {subject.name} ({subject.code})")
            
            # LOG ACTIVITY - DIRECT APPROACH
            from .models import ActivityLog
            try:
                activity = ActivityLog.objects.create(
                    activity_type='subject_created',
                    user=request.user,
                    description=f"Subject {subject.name} ({subject.code}) was created"
                )
                print(f"Activity logged: {activity.description}")
            except Exception as e:
                print(f"Error logging activity: {e}")
            
            messages.success(request, 'Subject added successfully')
            return redirect('accounts:manage_subjects')
    else:
        form = SubjectForm()
    
    context = {'subjects': subjects, 'form': form}
    return render(request, 'admin_dashboard/manage_subjects.html', context)

@login_required
@user_passes_test(is_admin)
def edit_subject(request, pk):
    subject = get_object_or_404(Subject, pk=pk)
    
    print("=== EDIT SUBJECT DEBUG ===")
    print(f"Editing subject: {subject.name} ({subject.code})")
    
    if request.method == 'POST':
        form = SubjectForm(request.POST, instance=subject)
        if form.is_valid():
            subject = form.save()
            
            print("Subject updated successfully")
            
            # LOG ACTIVITY - DIRECT APPROACH
            from .models import ActivityLog
            try:
                activity = ActivityLog.objects.create(
                    activity_type='subject_updated',
                    user=request.user,
                    description=f"Subject {subject.name} ({subject.code}) was updated"
                )
                print(f"Activity logged: {activity.description}")
            except Exception as e:
                print(f"Error logging activity: {e}")
            
            messages.success(request, 'Subject updated successfully')
            return redirect('accounts:manage_subjects')
    else:
        form = SubjectForm(instance=subject)
    
    return render(request, 'admin_dashboard/edit_subject.html', {'form': form, 'subject': subject})

@login_required
@user_passes_test(is_admin)
def delete_subject(request, pk):
    subject = get_object_or_404(Subject, pk=pk)
    
    print("=== DELETE SUBJECT DEBUG ===")
    print(f"Subject to delete: {subject.name} ({subject.code})")
    
    if request.method == 'POST':
        print("POST request received - processing deletion")
        
        subject_name = f"{subject.name} ({subject.code})"
        
        # LOG ACTIVITY - DIRECT APPROACH
        from .models import ActivityLog
        try:
            activity = ActivityLog.objects.create(
                activity_type='subject_deleted',
                user=request.user,
                description=f"Subject {subject_name} was deleted"
            )
            print(f"Activity logged: {activity.description}")
        except Exception as e:
            print(f"Error logging activity: {e}")
        
        subject.delete()
        print("Subject deleted from database")
        
        messages.success(request, 'Subject deleted successfully')
        return redirect('accounts:manage_subjects')
    
    return render(request, 'admin_dashboard/delete_subject.html', {'subject': subject})

@login_required
def teacher_dashboard(request):
    if request.user.is_staff:
        return redirect('accounts:admin_dashboard')
    
    teacher = get_object_or_404(TeacherProfile, user=request.user)
    my_uploads = teacher.questionnaires.count()
    
    context = {
        'teacher': teacher,
        'my_uploads': my_uploads,
    }
    return render(request, 'teacher_dashboard/dashboard.html', context)

@login_required
@user_passes_test(is_admin)
def test_activity(request):
    """Test view to manually create an activity"""
    from .models import ActivityLog
    
    print("=== TEST ACTIVITY START ===")
    
    # Create a test activity
    activity = ActivityLog.objects.create(
        activity_type='system',
        user=request.user,
        description='Test activity created manually'
    )
    
    print(f"Test activity created: {activity.id}")
    print(f"Total activities now: {ActivityLog.objects.count()}")
    
    # Redirect to dashboard to see if it appears
    return redirect('accounts:admin_dashboard')


@login_required
@require_POST
def mark_all_notifications_read(request):
    """Mark all unread notifications as read for the current user"""
    try:
        if request.user.is_staff:
            # Admin: Mark ALL activities as read
            updated_count = ActivityLog.objects.filter(
                is_read=False
            ).update(is_read=True)
        else:
            # Teacher: Mark only their activities as read
            updated_count = ActivityLog.objects.filter(
                user=request.user,
                is_read=False
            ).update(is_read=True)
        
        return JsonResponse({
            'success': True,
            'message': f'{updated_count} notifications marked as read'
        })
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)
        
def get_activity_chart_data(department_filter='all'):
    """Get upload/download activity data for the chart"""
    from questionnaires.models import Questionnaire, Download
    from django.db.models.functions import TruncDate
    
    # Get data for last 7 days
    today = timezone.now().date()
    date_range = [today - timedelta(days=i) for i in range(6, -1, -1)]
    
    labels = [d.strftime('%b %d') for d in date_range]
    uploads = []
    downloads = []
    
    for date in date_range:
        # Count uploads for this date
        upload_qs = Questionnaire.objects.filter(
            uploaded_at__date=date
        )
        if department_filter != 'all':
            upload_qs = upload_qs.filter(department_id=department_filter)
        
        upload_count = upload_qs.count()
        uploads.append(upload_count)
        
        # Count downloads for this date
        download_qs = Download.objects.filter(
            downloaded_at__date=date
        )
        if department_filter != 'all':
            download_qs = download_qs.filter(
                questionnaire__department_id=department_filter
            )
        
        download_count = download_qs.count()
        downloads.append(download_count)
    
    return {
        'labels': labels,
        'uploads': uploads,
        'downloads': downloads
    }


def get_department_chart_data():
    """Get questionnaire distribution by department for pie chart"""
    from questionnaires.models import Questionnaire
    from django.db.models import Count
    
    departments = Department.objects.annotate(
        questionnaire_count=Count('questionnaires')
    ).filter(questionnaire_count__gt=0).order_by('-questionnaire_count')
    
    labels = [dept.name for dept in departments]
    values = [dept.questionnaire_count for dept in departments]
    
    return {
        'labels': labels,
        'values': values
    }
# ============================================================================
# CLEANED UP DEPARTMENT AND SUBJECT VIEWS WITH ACTIVITY LOGGING
# Replace the duplicate department/subject functions in your views.py with these
# ============================================================================

# ============================================================================
# DEPARTMENT VIEWS (Remove all duplicate department functions and use these)
# ============================================================================

@login_required
@user_passes_test(is_admin)
def add_department(request):
    """View to add a new department (separate page)"""
    if request.method == 'POST':
        form = DepartmentForm(request.POST)
        if form.is_valid():
            department = form.save()
            
            # LOG ACTIVITY
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
    
    context = {'form': form}
    return render(request, 'admin_dashboard/add_department.html', context)


@login_required
@user_passes_test(is_admin)
def manage_departments(request):
    """View to list all departments"""
    departments = Department.objects.all().order_by('name')
    
    if request.method == 'POST':
        form = DepartmentForm(request.POST)
        if form.is_valid():
            department = form.save()
            
            # LOG ACTIVITY
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
    
    context = {
        'departments': departments,
        'form': form
    }
    return render(request, 'admin_dashboard/manage_departments.html', context)


@login_required
@user_passes_test(is_admin)
def edit_department(request, pk):
    """View to edit a department"""
    department = get_object_or_404(Department, pk=pk)
    old_name = department.name
    old_code = department.code
    
    if request.method == 'POST':
        form = DepartmentForm(request.POST, instance=department)
        if form.is_valid():
            updated_department = form.save()
            
            # LOG ACTIVITY
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
    
    context = {
        'form': form,
        'department': department
    }
    return render(request, 'admin_dashboard/edit_department.html', context)


@login_required
@user_passes_test(is_admin)
def delete_department(request, pk):
    """View to delete a department"""
    department = get_object_or_404(Department, pk=pk)
    
    if request.method == 'POST':
        department_name = department.name
        department_code = department.code
        
        # LOG ACTIVITY BEFORE DELETING
        ActivityLog.objects.create(
            activity_type='department_deleted',
            user=request.user,
            description=f"Department {department_name} ({department_code}) was deleted"
        )
        
        department.delete()
        messages.success(request, f'Department "{department_name}" has been deleted successfully!')
        return redirect('accounts:manage_departments')
    
    context = {
        'department': department
    }
    return render(request, 'admin_dashboard/delete_department.html', context)


# ============================================================================
# SUBJECT VIEWS (Remove all duplicate subject functions and use these)
# ============================================================================

@login_required
@user_passes_test(is_admin)
def add_subject(request):
    """View to add a new subject (separate page)"""
    if request.method == 'POST':
        form = SubjectForm(request.POST)
        if form.is_valid():
            subject = form.save()
            
            # LOG ACTIVITY
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
    
    context = {'form': form}
    return render(request, 'admin_dashboard/add_subject.html', context)


@login_required
@user_passes_test(is_admin)
def manage_subjects(request):
    """View to list all subjects"""
    subjects = Subject.objects.prefetch_related('departments').all().order_by('name')
    
    if request.method == 'POST':
        form = SubjectForm(request.POST)
        if form.is_valid():
            subject = form.save()
            
            # LOG ACTIVITY
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
    
    context = {
        'subjects': subjects,
        'form': form
    }
    return render(request, 'admin_dashboard/manage_subjects.html', context)


@login_required
@user_passes_test(is_admin)
def edit_subject(request, pk):
    """View to edit a subject"""
    subject = get_object_or_404(Subject, pk=pk)
    old_name = subject.name
    old_code = subject.code
    
    if request.method == 'POST':
        form = SubjectForm(request.POST, instance=subject)
        if form.is_valid():
            updated_subject = form.save()
            
            # LOG ACTIVITY
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
    
    context = {
        'form': form,
        'subject': subject
    }
    return render(request, 'admin_dashboard/edit_subject.html', context)


@login_required
@user_passes_test(is_admin)
def delete_subject(request, pk):
    """View to delete a subject"""
    subject = get_object_or_404(Subject, pk=pk)
    
    if request.method == 'POST':
        subject_name = subject.name
        subject_code = subject.code
        
        # LOG ACTIVITY BEFORE DELETING
        ActivityLog.objects.create(
            activity_type='subject_deleted',
            user=request.user,
            description=f"Subject {subject_name} ({subject_code}) was deleted"
        )
        
        subject.delete()
        messages.success(request, f'Subject "{subject_name}" ({subject_code}) has been deleted successfully!')
        return redirect('accounts:manage_subjects')
    
    context = {
        'subject': subject
    }
    return render(request, 'admin_dashboard/delete_subject.html', context)