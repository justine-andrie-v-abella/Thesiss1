# accounts/school_year_utils.py

from .models import SchoolYear, Semester

SESSION_KEY = 'view_semester_pk'


def resolve_view_semester(request):
    """
    Single source of truth for 'which semester is this request viewing'.

    Priority:
      1. Explicit ?semester=<pk> or ?semester=current on THIS request → also saved to session.
      2. No ?semester= param this request → fall back to whatever was last saved in session.
      3. Nothing saved yet → current semester.
    """
    current_semester = Semester.get_current()
    sem_param = request.GET.get('semester', None)

    if sem_param is not None:
        if sem_param in ('', 'current'):
            request.session[SESSION_KEY] = None
            view_semester = current_semester
        else:
            view_semester = Semester.objects.select_related('school_year').filter(pk=sem_param).first() or current_semester
            request.session[SESSION_KEY] = view_semester.pk if view_semester else None
    else:
        saved_pk = request.session.get(SESSION_KEY)
        if saved_pk:
            view_semester = Semester.objects.select_related('school_year').filter(pk=saved_pk).first() or current_semester
        else:
            view_semester = current_semester

    return current_semester, view_semester