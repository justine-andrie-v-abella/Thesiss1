from pathlib import Path
import os
import dj_database_url
from decouple import config

BASE_DIR = Path(__file__).resolve().parent.parent

# Use config() to read from .env file
SECRET_KEY = config('SECRET_KEY', default='django-insecure-fallback-key')

DEBUG = config('DEBUG', default=True, cast=bool)

ALLOWED_HOSTS = [
                'localhost',
                '127.0.0.1',
                'qvrbmzwj-2000.asse.devtunnels.ms',
                '.vercel.app',
                 ]
CSRF_TRUSTED_ORIGINS = ['https://qvrbmzwj-2000.asse.devtunnels.ms/',
                        'https://*.vercel.app',
                        ]


INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'accounts',
    'questionnaires',
]

# ── Cloud storage app (django-storages) ─────────────────────────────────────
# Added conditionally below, once we know whether USE_S3 is on, so that
# local dev without any bucket configured still works normally.
USE_S3 = config('USE_S3', default=False, cast=bool)
if USE_S3:
    INSTALLED_APPS += ['storages']

MIDDLEWARE = [
    'accounts.middleware.SessionDatabaseErrorMiddleware',  # ← FIRST
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'accounts.middleware.DatabaseErrorMiddleware', 
]

ROOT_URLCONF = 'test_banking_system.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'accounts.context_processors.notifications_context',
                'accounts.context_processors.school_year_context',  
            ],
        },
    },
]

WSGI_APPLICATION = 'test_banking_system.wsgi.application'

DATABASES = {
    "default": dj_database_url.parse(
        config('DATABASE_URL')
    )
}

DATABASES["default"]["CONN_MAX_AGE"] = 60
DATABASES["default"]["OPTIONS"] = {
    "sslmode": "require",
}
DATABASES["default"]["DISABLE_SERVER_SIDE_CURSORS"] = True

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "unique-snowflake",
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'Asia/Manila'
USE_I18N = True
USE_TZ = True

STATIC_URL = '/static/'
STATICFILES_DIRS = [BASE_DIR / 'static']
# Static files (CSS/JS bundled with your repo) are read-only and served fine
# from Vercel as-is — this is NOT the same problem as MEDIA below, so it's
# left untouched.

# ============================================================================
# MEDIA / FILE STORAGE
# ----------------------------------------------------------------------------
# Vercel's serverless filesystem is read-only outside of /tmp, and /tmp does
# not persist between requests or survive redeploys. Local FileSystemStorage
# (the Django default) CANNOT be used for user uploads or generated files in
# that environment — this is why uploads and generated docx/pdf files were
# failing/disappearing.
#
# USE_S3=True switches MEDIA storage to an S3-compatible bucket (works with
# AWS S3 as-is, or Cloudflare R2 / Backblaze B2 / DigitalOcean Spaces by also
# setting AWS_S3_ENDPOINT_URL). Set USE_S3=False (or leave unset) for local
# development, where writing to BASE_DIR/media works fine.
# ============================================================================

if USE_S3:
    AWS_ACCESS_KEY_ID     = config('AWS_ACCESS_KEY_ID')
    AWS_SECRET_ACCESS_KEY = config('AWS_SECRET_ACCESS_KEY')
    AWS_STORAGE_BUCKET_NAME = config('AWS_STORAGE_BUCKET_NAME')
    AWS_S3_REGION_NAME    = config('AWS_S3_REGION_NAME', default='auto')

    # Leave AWS_S3_ENDPOINT_URL unset for real AWS S3.
    # For Cloudflare R2, set it to: https://<ACCOUNT_ID>.r2.cloudflarestorage.com
    AWS_S3_ENDPOINT_URL = config('AWS_S3_ENDPOINT_URL', default=None)

    AWS_DEFAULT_ACL       = None
    AWS_S3_FILE_OVERWRITE = False
    AWS_QUERYSTRING_AUTH  = True   # signed, expiring URLs — set False only if the bucket is public
    AWS_S3_OBJECT_PARAMETERS = {
        'CacheControl': 'max-age=86400',
    }

    STORAGES = {
    "default": {
        "BACKEND": "storages.backends.s3boto3.S3Boto3Storage",
    },
    "staticfiles": {
        "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage",
    },
}

    if AWS_S3_ENDPOINT_URL:
        MEDIA_URL = f'{AWS_S3_ENDPOINT_URL}/{AWS_STORAGE_BUCKET_NAME}/'
    else:
        MEDIA_URL = f'https://{AWS_STORAGE_BUCKET_NAME}.s3.amazonaws.com/'

    # MEDIA_ROOT is irrelevant once DEFAULT_FILE_STORAGE points at S3, but
    # Django expects the setting to exist.
    MEDIA_ROOT = BASE_DIR / 'media'
else:
    MEDIA_URL  = 'media/'
    MEDIA_ROOT = BASE_DIR / 'media'
    STORAGES = {
        "default": {
            "BACKEND": "django.core.files.storage.FileSystemStorage",
        },
        "staticfiles": {
            "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage",
        },
    }

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

LOGIN_URL = 'accounts:login'
LOGIN_REDIRECT_URL = 'home'
LOGOUT_REDIRECT_URL = 'home'

# Anthropic API Configuration (reads from .env file)
ANTHROPIC_API_KEY = config('ANTHROPIC_API_KEY', default='')

# Google Gemini API Configuration (FREE)
GEMINI_API_KEY = config('GEMINI_API_KEY', default='')

# File upload settings
FILE_UPLOAD_MAX_MEMORY_SIZE = 10485760  # 10MB
DATA_UPLOAD_MAX_MEMORY_SIZE = 10485760  # 10MB

# Allowed file extensions for questionnaires
ALLOWED_FILE_EXTENSIONS = ['.pdf', '.docx', '.doc', '.xlsx', '.xls', '.txt']

# ============================================================================
# EMAIL CONFIGURATION (Gmail SMTP)
# ============================================================================
EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
EMAIL_HOST = 'smtp.gmail.com'
EMAIL_PORT = 587
EMAIL_USE_TLS = True
EMAIL_HOST_USER = config('EMAIL_HOST_USER', default='')
EMAIL_HOST_PASSWORD = config('EMAIL_HOST_PASSWORD', default='')  # Use Gmail App Password
DEFAULT_FROM_EMAIL = config('EMAIL_HOST_USER', default='')
SITE_URL = config('SITE_URL', default='http://localhost:2000')