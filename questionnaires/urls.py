# ============================================================================
# FILE: questionnaires/urls.py
# ============================================================================

from django.urls import path
from . import views

app_name = 'questionnaires'

urlpatterns = [
    # Upload and management
    path('upload/', views.upload_questionnaire, name='upload_questionnaire'),
    path('generate/', views.generate_questionnaire, name='generate_questionnaire'),
    path('my-uploads/', views.my_uploads, name='my_uploads'),
    path('browse/', views.browse_questionnaires, name='browse_questionnaires'),
    path('all/', views.all_questionnaires, name='all_questionnaires'),
    path('edit/<int:pk>/', views.edit_questionnaire, name='edit_questionnaire'),
    path('delete/<int:pk>/', views.delete_questionnaire, name='delete_questionnaire'),
    path('download/<int:pk>/', views.download_questionnaire, name='download_questionnaire'),
    
    # AI Extraction
    path('review-extracted/<int:pk>/', views.review_extracted_questions, name='review_extracted'),
    path('retry-extraction/<int:pk>/', views.retry_extraction, name='retry_extraction'),
    
    # AJAX
    path('get-subjects/', views.get_subjects_ajax, name='get_subjects'),
    
    # Download questionnaire
    path('download/<int:pk>/', views.download_questionnaire, name='download_questionnaire'),
    
    # Preview questionnaire (optional)
    path('preview/<int:pk>/', views.preview_questionnaire, name='preview_questionnaire'),
    
    path('get-questions/<int:pk>/', views.get_questions_json, name='get_questions_json'),
    path('download/<int:pk>/', views.download_questionnaire, name='download_questionnaire'),


]
