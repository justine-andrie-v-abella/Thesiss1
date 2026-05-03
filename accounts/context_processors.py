from django.core.cache import cache
from .models import ActivityLog

SAFE_DEFAULTS = {
    'recent_activities': [],
    'unread_notification_count': 0,
    'user_is_superadmin': False,
    'user_is_subadmin': False,
    'subadmin_department': None,
}


def notifications_context(request):
    try:
        if not request.user.is_authenticated:
            return SAFE_DEFAULTS.copy()

        user = request.user
        is_superadmin = user.is_staff

        has_active_subadmin = (
            not user.is_staff
            and hasattr(user, 'subadmin_profile')
            and user.subadmin_profile.is_active
        )
        has_active_teacher = (
            not user.is_staff
            and hasattr(user, 'teacher_profile')
            and user.teacher_profile.is_active
        )

        # For dual-role users, respect the session's active_role choice.
        # A dual-role user who chose 'teacher' should see teacher navigation,
        # not sub-admin navigation.
        if has_active_subadmin and has_active_teacher:
            active_role = getattr(request, 'session', {}).get('active_role', '')
            is_subadmin = (active_role != 'teacher')  # default to subadmin if no choice
        else:
            is_subadmin = has_active_subadmin

        # ── Cache keys per user ──────────────────────────────────────────
        activities_key = f'activities_{user.id}_{"super" if is_superadmin else "other"}'
        unread_key     = f'unread_count_{user.id}_{"super" if is_superadmin else "other"}'

        all_activities = cache.get(activities_key)
        unread_count   = cache.get(unread_key)

        # Only query DB if cache is empty
        if all_activities is None or unread_count is None:
            if is_superadmin:
                all_activities = list(
                    ActivityLog.objects
                    .all()
                    .select_related('user')
                    .order_by('-created_at')[:50]
                )
                unread_count = ActivityLog.objects.filter(is_read=False).count()

            elif is_subadmin:
                all_activities = list(
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
                all_activities = list(
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

            # Cache for 30 seconds — short enough for near-real-time feel
            cache.set(activities_key, all_activities, timeout=30)
            cache.set(unread_key, unread_count, timeout=30)

        # ── Format activities (no DB hit, pure Python) ───────────────────
        formatted_activities = []
        for activity in all_activities:
            atype = activity.activity_type
            desc  = activity.description.lower()

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
                title = (
                    activity.get_activity_type_display()
                    if hasattr(activity, 'get_activity_type_display')
                    else 'Activity'
                )

            formatted_activities.append({
                'id':            activity.id,
                'title':         title,
                'description':   activity.description,
                'time':          activity.created_at,
                'read':          activity.is_read,
                'icon':          icon,
                'color':         color,
                'activity_type': atype,
                'user':          activity.user.get_full_name() if activity.user else 'System',
            })

        return {
            'recent_activities':        formatted_activities,
            'unread_notification_count': unread_count,
            'user_is_superadmin':        is_superadmin,
            'user_is_subadmin':          is_subadmin,
            'subadmin_department': (
                user.subadmin_profile.department if is_subadmin else None
            ),
        }

    except Exception:
        return SAFE_DEFAULTS.copy()