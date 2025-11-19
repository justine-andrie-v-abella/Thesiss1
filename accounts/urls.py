from django.urls import path
from . import views

app_name = 'accounts'

urlpatterns = [
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
    
    # Admin URLs
    path('admin-dashboard/', views.admin_dashboard, name='admin_dashboard'),
    path('manage-teachers/', views.manage_teachers, name='manage_teachers'),
    path('add-teacher/', views.add_teacher, name='add_teacher'),
    path('edit-teacher/<int:pk>/', views.edit_teacher, name='edit_teacher'),
    path('delete-teacher/<int:pk>/', views.delete_teacher, name='delete_teacher'),
    
    path('manage-departments/', views.manage_departments, name='manage_departments'),
    path('edit-department/<int:pk>/', views.edit_department, name='edit_department'),
    path('delete-department/<int:pk>/', views.delete_department, name='delete_department'),
    
    path('manage-subjects/', views.manage_subjects, name='manage_subjects'),
    path('edit-subject/<int:pk>/', views.edit_subject, name='edit_subject'),
    path('delete-subject/<int:pk>/', views.delete_subject, name='delete_subject'),
    
    # Teacher URLs
    path('teacher-dashboard/', views.teacher_dashboard, name='teacher_dashboard'),
    path('test-activity/', views.test_activity, name='test_activity'),
]
