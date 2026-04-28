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
    path('archive-teacher/<int:pk>/', views.archive_teacher, name='archive_teacher'),
    path('unarchive-teacher/<int:pk>/', views.unarchive_teacher, name='unarchive_teacher'),
    path('permanent-delete-teacher/<int:pk>/', views.permanent_delete_teacher, name='permanent_delete_teacher'),

    # Department Management
    path('manage-departments/', views.manage_departments, name='manage_departments'),
    path('add-department/', views.add_department, name='add_department'),
    path('edit-department/<int:pk>/', views.edit_department, name='edit_department'),
    path('delete-department/<int:pk>/', views.delete_department, name='delete_department'),
    path('archive-department/<int:pk>/', views.archive_department, name='archive_department'),
    path('unarchive-department/<int:pk>/', views.unarchive_department, name='unarchive_department'),
    path('permanent-delete-department/<int:pk>/', views.permanent_delete_department, name='permanent_delete_department'),

    # Subject Management
    path('manage-subjects/', views.manage_subjects, name='manage_subjects'),
    path('add-subject/', views.add_subject, name='add_subject'),
    path('edit-subject/<int:pk>/', views.edit_subject, name='edit_subject'),
    path('delete-subject/<int:pk>/', views.delete_subject, name='delete_subject'),
    path('archive-subject/<int:pk>/', views.archive_subject, name='archive_subject'),
    path('unarchive-subject/<int:pk>/', views.unarchive_subject, name='unarchive_subject'),
    path('permanent-delete-subject/<int:pk>/', views.permanent_delete_subject, name='permanent_delete_subject'),

    # Sub-Admin Management (superadmin creates/assigns sub-admins)
    path('manage-subadmins/', views.manage_subadmins, name='manage_subadmins'),
    path('add-subadmin/', views.add_subadmin, name='add_subadmin'),
    path('edit-subadmin/<int:pk>/', views.edit_subadmin, name='edit_subadmin'),
    path('delete-subadmin/<int:pk>/', views.delete_subadmin, name='delete_subadmin'),
    path('archive-subadmin/<int:pk>/', views.archive_subadmin, name='archive_subadmin'),
    path('unarchive-subadmin/<int:pk>/', views.unarchive_subadmin, name='unarchive_subadmin'),
    path('permanent-delete-subadmin/<int:pk>/', views.permanent_delete_subadmin, name='permanent_delete_subadmin'),

    # ── Sub-Admin ────────────────────────────────────────────────────────────

    path('subadmin-dashboard/', views.subadmin_dashboard, name='subadmin_dashboard'),

    # Teacher Management (sub-admin — their department only)
    path('subadmin/teachers/', views.subadmin_manage_teachers, name='subadmin_manage_teachers'),
    path('subadmin/teachers/add/', views.subadmin_add_teacher, name='subadmin_add_teacher'),
    path('subadmin/teachers/edit/<int:pk>/', views.subadmin_edit_teacher, name='subadmin_edit_teacher'),
    path('subadmin/teachers/delete/<int:pk>/', views.subadmin_delete_teacher, name='subadmin_delete_teacher'),
    path('subadmin/teachers/archive/<int:pk>/', views.subadmin_archive_teacher, name='subadmin_archive_teacher'),
    path('subadmin/teachers/unarchive/<int:pk>/', views.subadmin_unarchive_teacher, name='subadmin_unarchive_teacher'),
    path('subadmin/teachers/permanent-delete/<int:pk>/', views.subadmin_permanent_delete_teacher, name='subadmin_permanent_delete_teacher'),

    # ── Teacher ──────────────────────────────────────────────────────────────

    path('teacher-dashboard/', views.teacher_dashboard, name='teacher_dashboard'),

    # ── Shared ───────────────────────────────────────────────────────────────

    path('mark-all-notifications-read/', views.mark_all_notifications_read, name='mark_all_notifications_read'),
    # Subject Management (sub-admin — their department only)
    path('subadmin/subjects/',                          views.subadmin_manage_subjects,          name='subadmin_manage_subjects'),
    path('subadmin/subjects/add/',                      views.subadmin_add_subject,              name='subadmin_add_subject'),
    path('subadmin/subjects/<int:pk>/edit/',            views.subadmin_edit_subject,             name='subadmin_edit_subject'),
    path('subadmin/subjects/<int:pk>/delete/',          views.subadmin_delete_subject,           name='subadmin_delete_subject'),
    path('subadmin/subjects/<int:pk>/archive/',         views.subadmin_archive_subject,          name='subadmin_archive_subject'),
    path('subadmin/subjects/<int:pk>/unarchive/',       views.subadmin_unarchive_subject,        name='subadmin_unarchive_subject'),
    path('subadmin/subjects/<int:pk>/permanent-delete/', views.subadmin_permanent_delete_subject, name='subadmin_permanent_delete_subject'),

    # Browse Questionnaires (sub-admin — department-scoped)
    path('subadmin/questionnaires/',                    views.subadmin_browse_questionnaires, name='subadmin_browse_questionnaires'),

    # ── Program Management (superadmin) ─────────────────────────────────────
    path('departments/<int:pk>/programs/',                            views.department_detail,            name='department_detail'),
    path('departments/<int:dept_pk>/programs/add/',                   views.add_program,                  name='add_program'),
    path('programs/<int:pk>/edit/',                                   views.edit_program,                 name='edit_program'),
    path('programs/<int:pk>/delete/',                                 views.delete_program,               name='delete_program'),
    path('programs/<int:pk>/subjects/',                               views.program_detail,               name='program_detail'),
    path('programs/<int:prog_pk>/subjects/add/',                      views.add_subject_to_program,        name='add_subject_to_program'),
    path('programs/<int:prog_pk>/subjects/bulk-add/',                 views.bulk_add_subjects_to_program,  name='bulk_add_subjects_to_program'),
    path('programs/<int:prog_pk>/subjects/<int:subj_pk>/remove/',     views.remove_subject_from_program,   name='remove_subject_from_program'),

    # ── Program Management (sub-admin) ──────────────────────────────────────
    path('subadmin/programs/',                                        views.subadmin_manage_programs,              name='subadmin_manage_programs'),
    path('subadmin/programs/add/',                                    views.subadmin_add_program,                  name='subadmin_add_program'),
    path('subadmin/programs/<int:pk>/edit/',                          views.subadmin_edit_program,                 name='subadmin_edit_program'),
    path('subadmin/programs/<int:pk>/delete/',                        views.subadmin_delete_program,               name='subadmin_delete_program'),
    path('subadmin/programs/<int:pk>/subjects/',                      views.subadmin_program_detail,               name='subadmin_program_detail'),
    path('subadmin/programs/<int:prog_pk>/subjects/add/',             views.subadmin_add_subject_to_program,            name='subadmin_add_subject_to_program'),
    path('subadmin/programs/<int:prog_pk>/subjects/bulk-add/',        views.subadmin_bulk_add_subjects_to_program,      name='subadmin_bulk_add_subjects_to_program'),
    path('subadmin/programs/<int:prog_pk>/subjects/<int:subj_pk>/remove/', views.subadmin_remove_subject_from_program, name='subadmin_remove_subject_from_program'),

    path('profile/update/', views.update_profile, name='update_profile'),
    path('profile/change-password/', views.change_credentials, name='change_credentials'),

    # ── AJAX helpers ─────────────────────────────────────────────────────────
    path('ajax/subjects-by-dept/', views.get_subjects_by_department, name='get_subjects_by_department'),
]