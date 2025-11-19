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
from .models import TeacherProfile, Department, Subject
from .forms import TeacherCreationForm, TeacherEditForm, DepartmentForm, SubjectForm

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

def login_view(request):
    if request.user.is_authenticated:
        return redirect('home')
    
    if request.method == 'POST':
        username = request.POST.get('username')
        password = request.POST.get('password')
        user = authenticate(request, username=username, password=password)
        
        if user is not None:
            login(request, user)
            
            # LOG LOGIN ACTIVITY
            from .models import ActivityLog
            ActivityLog.objects.create(
                activity_type='user_login',
                user=user,
                description=f"User {user.get_full_name()} logged in to the system"
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
    total_teachers = TeacherProfile.objects.count()
    active_teachers = TeacherProfile.objects.filter(is_active=True).count()
    total_departments = Department.objects.count()
    total_subjects = Subject.objects.count()
    
    # Get recent activities from ActivityLog model (last 24 hours)
    from .models import ActivityLog
    since = timezone.now() - timedelta(hours=24)
    recent_activities_db = ActivityLog.objects.filter(created_at__gte=since).select_related('user')[:10]
    
    # Format activities for template
    recent_activities = []
    for activity in recent_activities_db:
        recent_activities.append({
            'title': activity.get_activity_type_display(),
            'description': activity.description,
            'time': activity.created_at,
            'read': activity.is_read,
            'icon': activity.get_icon(),
            'color': activity.get_color()
        })
    
    # REMOVED THE FALLBACK SAMPLE DATA - let template handle empty case
    
    context = {
        'total_teachers': total_teachers,
        'active_teachers': active_teachers,
        'total_departments': total_departments,
        'total_subjects': total_subjects,
        'recent_activities': recent_activities,
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