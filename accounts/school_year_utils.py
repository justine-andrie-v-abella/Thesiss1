# accounts/school_year_utils.py

from .models import SchoolYear

SESSION_KEY = 'view_year_pk'


def resolve_view_year(request):
    """
    Single source of truth for 'which school year is this request viewing'.

    Priority:
      1. Explicit ?year=<pk> or ?year=current on THIS request → also saved to session.
      2. No ?year= param this request → fall back to whatever was last saved in session.
      3. Nothing saved yet → current school year.
    """
    current_year = SchoolYear.get_current()
    year_param = request.GET.get('year', None)

    if year_param is not None:
        if year_param in ('', 'current'):
            request.session[SESSION_KEY] = None
            view_year = current_year
        else:
            view_year = SchoolYear.objects.filter(pk=year_param).first() or current_year
            request.session[SESSION_KEY] = view_year.pk if view_year else None
    else:
        saved_pk = request.session.get(SESSION_KEY)
        if saved_pk:
            view_year = SchoolYear.objects.filter(pk=saved_pk).first() or current_year
        else:
            view_year = current_year

    return current_year, view_year