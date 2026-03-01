# ============================================================================
# FILE: accounts/urls.py
# ============================================================================

from django.urls import path
from . import views

app_name = 'accounts'

urlpatterns = [
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),

    # ── Superadmin ──────────────────────────────────────────────────────────

    path('admin-dashboard/', views.admin_dashboard, name='admin_dashboard'),

    # Teacher Management (superadmin — all departments)
    path('manage-teachers/', views.manage_teachers, name='manage_teachers'),
    path('add-teacher/', views.add_teacher, name='add_teacher'),
    path('edit-teacher/<int:pk>/', views.edit_teacher, name='edit_teacher'),
    path('delete-teacher/<int:pk>/', views.delete_teacher, name='delete_teacher'),

    # Department Management
    path('manage-departments/', views.manage_departments, name='manage_departments'),
    path('add-department/', views.add_department, name='add_department'),
    path('edit-department/<int:pk>/', views.edit_department, name='edit_department'),
    path('delete-department/<int:pk>/', views.delete_department, name='delete_department'),

    # Subject Management
    path('manage-subjects/', views.manage_subjects, name='manage_subjects'),
    path('add-subject/', views.add_subject, name='add_subject'),
    path('edit-subject/<int:pk>/', views.edit_subject, name='edit_subject'),
    path('delete-subject/<int:pk>/', views.delete_subject, name='delete_subject'),

    # Sub-Admin Management (superadmin creates/assigns sub-admins)
    path('manage-subadmins/', views.manage_subadmins, name='manage_subadmins'),
    path('add-subadmin/', views.add_subadmin, name='add_subadmin'),
    path('edit-subadmin/<int:pk>/', views.edit_subadmin, name='edit_subadmin'),
    path('delete-subadmin/<int:pk>/', views.delete_subadmin, name='delete_subadmin'),

    # ── Sub-Admin ────────────────────────────────────────────────────────────

    path('subadmin-dashboard/', views.subadmin_dashboard, name='subadmin_dashboard'),

    # Teacher Management (sub-admin — their department only)
    path('subadmin/teachers/', views.subadmin_manage_teachers, name='subadmin_manage_teachers'),
    path('subadmin/teachers/add/', views.subadmin_add_teacher, name='subadmin_add_teacher'),
    path('subadmin/teachers/edit/<int:pk>/', views.subadmin_edit_teacher, name='subadmin_edit_teacher'),
    path('subadmin/teachers/delete/<int:pk>/', views.subadmin_delete_teacher, name='subadmin_delete_teacher'),

    # ── Teacher ──────────────────────────────────────────────────────────────

    path('teacher-dashboard/', views.teacher_dashboard, name='teacher_dashboard'),

    # ── Shared ───────────────────────────────────────────────────────────────

    path('mark-all-notifications-read/', views.mark_all_notifications_read, name='mark_all_notifications_read'),
    path('test-activity/', views.test_activity, name='test_activity'),
]