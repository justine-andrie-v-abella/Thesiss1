# ============================================================================
# FILE: accounts/context_processors.py
# ============================================================================

from .models import ActivityLog


def notifications_context(request):
    """
    Inject notification data into every template.

    Roles:
      - Superadmin (is_staff)  → sees ALL activities system-wide
      - Sub-admin              → sees only activities they personally performed
      - Teacher                → sees only their own activities (no login events)
    """
    if not request.user.is_authenticated:
        return {'recent_activities': [], 'unread_notification_count': 0}

    user = request.user

    # ── Determine role ───────────────────────────────────────────────────────
    is_superadmin = user.is_staff
    is_subadmin = (
        not user.is_staff
        and hasattr(user, 'subadmin_profile')
        and user.subadmin_profile.is_active
    )

    # ── Query activities based on role ───────────────────────────────────────
    if is_superadmin:
        # Superadmin: every activity in the system
        all_activities = (
            ActivityLog.objects
            .all()
            .select_related('user')
            .order_by('-created_at')[:50]
        )
        unread_count = ActivityLog.objects.filter(is_read=False).count()

    elif is_subadmin:
        # Sub-admin: only actions they personally took (excludes login noise)
        all_activities = (
            ActivityLog.objects
            .filter(user=user)
            .exclude(activity_type='user_login')
            .select_related('user')
            .order_by('-created_at')[:50]
        )
        unread_count = (
            ActivityLog.objects
            .filter(user=user, is_read=False)
            .exclude(activity_type='user_login')
            .count()
        )

    else:
        # Teacher: their own activities, no login events
        all_activities = (
            ActivityLog.objects
            .filter(user=user)
            .exclude(activity_type='user_login')
            .select_related('user')
            .order_by('-created_at')[:50]
        )
        unread_count = (
            ActivityLog.objects
            .filter(user=user, is_read=False)
            .exclude(activity_type='user_login')
            .count()
        )

    # ── Format for templates ─────────────────────────────────────────────────
    formatted_activities = []
    for activity in all_activities:
        atype = activity.activity_type
        desc = activity.description.lower()

        if atype == 'user_login' or 'logged in' in desc:
            icon, color, title = 'bi-box-arrow-in-right', 'green', 'User Login'
        elif 'subadmin' in atype:
            icon, color, title = 'bi-person-gear', 'indigo', 'Sub-Admin Activity'
        elif 'created' in atype:
            icon, color, title = 'bi-plus-circle-fill', 'green', 'New Addition'
        elif 'updated' in atype or 'edited' in atype:
            icon, color, title = 'bi-pencil-fill', 'blue', 'Update'
        elif 'deleted' in atype:
            icon, color, title = 'bi-trash-fill', 'red', 'Deletion'
        elif 'upload' in atype:
            icon, color, title = 'bi-cloud-upload-fill', 'purple', 'Upload'
        elif 'teacher' in atype:
            icon, color, title = 'bi-person-badge-fill', 'blue', 'Teacher Activity'
        elif 'department' in atype:
            icon, color, title = 'bi-building', 'indigo', 'Department Activity'
        elif 'subject' in atype:
            icon, color, title = 'bi-book-fill', 'purple', 'Subject Activity'
        else:
            icon, color = 'bi-info-circle-fill', 'gray'
            title = activity.get_activity_type_display() if hasattr(activity, 'get_activity_type_display') else 'Activity'

        formatted_activities.append({
            'id': activity.id,
            'title': title,
            'description': activity.description,
            'time': activity.created_at,
            'read': activity.is_read,
            'icon': icon,
            'color': color,
            'activity_type': atype,
            'user': activity.user.get_full_name() if activity.user else 'System',
        })

    # ── Inject role flags for templates ──────────────────────────────────────
    return {
        'recent_activities': formatted_activities,
        'unread_notification_count': unread_count,
        'user_is_superadmin': is_superadmin,
        'user_is_subadmin': is_subadmin,
        # Convenience: the sub-admin's department (None for other roles)
        'subadmin_department': (
            user.subadmin_profile.department if is_subadmin else None
        ),
    }