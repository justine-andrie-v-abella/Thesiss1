from django.shortcuts import render
from django.db import OperationalError

try:
    import psycopg2
    PSYCOPG2_AVAILABLE = True
except ImportError:
    PSYCOPG2_AVAILABLE = False


def is_db_error(e):
    if isinstance(e, OperationalError):
        return True
    if PSYCOPG2_AVAILABLE:
        import psycopg2
        if isinstance(e, psycopg2.OperationalError):
            return True
    keywords = [
        'could not translate host name',
        'connection refused',
        'could not connect to server',
        'name or service not known',
        'timeout expired',
        'no route to host',
    ]
    return any(kw in str(e).lower() for kw in keywords)


class DatabaseErrorMiddleware:
    """Catches DB errors from views and context processors."""
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        try:
            response = self.get_response(request)
            return response
        except Exception as e:
            if is_db_error(e):
                return render(request, 'errors/db_error.html', {
                    'error_message': str(e),
                }, status=503)
            raise


class SessionDatabaseErrorMiddleware:
    """
    Catches DB errors that happen BEFORE views run —
    specifically during session/auth loading.
    Must be placed ABOVE SessionMiddleware in settings.
    """
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)

    def process_exception(self, request, exception):
        if is_db_error(exception):
            return render(request, 'errors/db_error.html', {
                'error_message': str(exception),
            }, status=503)
        return None