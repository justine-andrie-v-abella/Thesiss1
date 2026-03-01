# ============================================================================
# FILE: questionnaires/views.py
# ============================================================================

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib import messages
from django.db.models import Q, Count
from django.core.paginator import Paginator
from django.http import FileResponse, Http404, JsonResponse
from django.views.decorators.http import require_POST
from .models import (
    Questionnaire, ExtractedQuestion, QuestionType,
    WorkspaceFolder, WorkspaceFolderQuestion,
)
from .forms import QuestionnaireUploadForm, QuestionnaireEditForm, QuestionnaireFilterForm
from accounts.models import TeacherProfile, Department, Subject, ActivityLog
from .services import QuestionnaireExtractor
from django.conf import settings

def get_extractor():
    """Get the appropriate AI extractor based on available API keys"""
    if hasattr(settings, 'GEMINI_API_KEY') and settings.GEMINI_API_KEY:
        from .services.gemini_extraction_service import GeminiQuestionnaireExtractor
        return GeminiQuestionnaireExtractor()
    elif hasattr(settings, 'ANTHROPIC_API_KEY') and settings.ANTHROPIC_API_KEY:
        from .services.extraction_service import QuestionnaireExtractor
        return QuestionnaireExtractor()
    else:
        raise ValueError("No AI API key configured. Please add GEMINI_API_KEY to your .env file.")

def is_admin(user):
    return user.is_authenticated and user.is_staff

def is_teacher(user):
    return user.is_authenticated and not user.is_staff and hasattr(user, 'teacher_profile')


# ============================================================================
# EXISTING VIEWS  (unchanged)
# ============================================================================

@login_required
def upload_questionnaire(request):
    if request.user.is_staff:
        messages.error(request, 'Admins cannot upload questionnaires')
        return redirect('accounts:admin_dashboard')

    teacher = get_object_or_404(TeacherProfile, user=request.user)

    if request.method == 'POST':
        form = QuestionnaireUploadForm(request.POST, request.FILES, user=request.user)

        if form.is_valid():
            questionnaire = form.save(commit=False)
            questionnaire.uploader         = teacher
            questionnaire.department       = teacher.department
            questionnaire.exam_type        = form.cleaned_data['exam_type']   # ← new
            questionnaire.extraction_status = 'processing'
            questionnaire.save()

            try:
                type_names = list(
                    QuestionType.objects.filter(is_active=True).values_list('name', flat=True)
                )

                extractor = get_extractor()
                created_questions = extractor.process_questionnaire(
                    questionnaire, type_names, mode='extract'
                )

                if not created_questions:
                    questionnaire.file.delete(save=False)
                    questionnaire.delete()
                    messages.error(
                        request,
                        'No questions were detected in your file. '
                        'Please upload a file that contains questions.',
                    )
                    return render(
                        request,
                        'teacher_dashboard/upload_questionnaire.html',
                        {'form': form},
                    )

                questionnaire.extraction_status = 'completed'
                questionnaire.is_extracted      = True
                questionnaire.save()

                ActivityLog.objects.create(
                    activity_type='questionnaire_uploaded',
                    user=request.user,
                    description=(
                        f'You uploaded "{questionnaire.title}" '
                        f'for {questionnaire.subject.code}'
                    ),
                )
                ActivityLog.objects.create(
                    activity_type='questions_extracted',
                    user=request.user,
                    description=(
                        f'Extracted {len(created_questions)} questions '
                        f'from "{questionnaire.title}"'
                    ),
                )

                messages.success(
                    request,
                    f'Extracted {len(created_questions)} questions! '
                    f'Now select the ones you want to keep.',
                )
                return redirect('questionnaires:review_extracted', pk=questionnaire.pk)

            except Exception as e:
                questionnaire.file.delete(save=False)
                questionnaire.delete()

                ActivityLog.objects.create(
                    activity_type='extraction_failed',
                    user=request.user,
                    description='Extraction failed — file was not saved.',
                )

                messages.error(
                    request,
                    f'AI extraction failed: {str(e)}. '
                    f'Your file was not saved. Please try again.',
                )
                return render(
                    request,
                    'teacher_dashboard/upload_questionnaire.html',
                    {'form': form},
                )
        else:
            messages.error(request, 'Please correct the errors below.')

    else:
        form = QuestionnaireUploadForm(user=request.user)

    return render(
        request,
        'teacher_dashboard/upload_questionnaire.html',
        {'form': form},
    )


@login_required
def generate_questionnaire(request):
    if request.user.is_staff:
        messages.error(request, 'Admins cannot generate questionnaires')
        return redirect('accounts:admin_dashboard')

    teacher = get_object_or_404(TeacherProfile, user=request.user)

    if request.method == 'POST':
        form = QuestionnaireUploadForm(request.POST, request.FILES, user=request.user)

        if form.is_valid():
            questionnaire = form.save(commit=False)
            questionnaire.uploader = teacher
            questionnaire.save()

            ActivityLog.objects.create(
                activity_type='questionnaire_uploaded',
                user=request.user,
                description=f'You uploaded "{questionnaire.title}" for AI extraction'
            )

            try:
                questionnaire.extraction_status = 'processing'
                questionnaire.save()

                question_types = form.cleaned_data.get('question_types')
                if question_types:
                    type_names = [qt.name for qt in question_types]
                else:
                    type_names = list(
                        QuestionType.objects.filter(is_active=True).values_list('name', flat=True)
                    )

                extractor = get_extractor()
                created_questions = extractor.process_questionnaire(questionnaire, type_names)

                questionnaire.extraction_status = 'completed'
                questionnaire.is_extracted = True
                questionnaire.save()

                ActivityLog.objects.create(
                    activity_type='questions_extracted',
                    user=request.user,
                    description=f'Successfully extracted {len(created_questions)} questions from "{questionnaire.title}"'
                )

                messages.success(request, f'Successfully extracted {len(created_questions)} questions!')
                return redirect('questionnaires:review_extracted', pk=questionnaire.pk)

            except Exception as e:
                questionnaire.extraction_status = 'failed'
                questionnaire.extraction_error = str(e)
                questionnaire.save()

                ActivityLog.objects.create(
                    activity_type='extraction_failed',
                    user=request.user,
                    description=f'Question extraction failed for "{questionnaire.title}"'
                )

                messages.error(request, f'AI extraction failed: {str(e)}. Please try again.')
                return render(request, 'teacher_dashboard/upload_questionnaire.html', {'form': form})
        else:
            messages.error(request, 'Please correct the errors below.')
    else:
        form = QuestionnaireUploadForm(user=request.user)

    return render(request, 'teacher_dashboard/upload_questionnaire.html', {'form': form})


@login_required
def review_extracted_questions(request, pk):
    questionnaire = get_object_or_404(Questionnaire, pk=pk)

    if request.user.is_staff:
        can_view = True
    elif hasattr(request.user, 'teacher_profile'):
        can_view = questionnaire.uploader == request.user.teacher_profile
    else:
        can_view = False

    if not can_view:
        messages.error(request, 'You do not have permission to view this.')
        return redirect('questionnaires:browse_questionnaires')

    extracted_questions = questionnaire.extracted_questions.select_related('question_type').all()

    if request.method == 'POST':
        action = request.POST.get('action')

        if action == 'save_selected':
            selected_ids = request.POST.getlist('selected_questions')

            manual_uids         = request.POST.getlist('manual_selected_uid[]')
            manual_texts        = request.POST.getlist('manual_question_text[]')
            manual_types        = request.POST.getlist('manual_question_type[]')
            manual_difficulties = request.POST.getlist('manual_difficulty[]')
            manual_points_list  = request.POST.getlist('manual_points[]')
            manual_answers      = request.POST.getlist('manual_correct_answer[]')
            manual_explanations = request.POST.getlist('manual_explanation[]')

            manual_opts_a = request.POST.getlist('manual_option_A[]')
            manual_opts_b = request.POST.getlist('manual_option_B[]')
            manual_opts_c = request.POST.getlist('manual_option_C[]')
            manual_opts_d = request.POST.getlist('manual_option_D[]')

            type_name_map = {
                'fill_in_the_blank': 'fill_blank',
                'multiple_choice':   'multiple_choice',
                'true_false':        'true_false',
                'identification':    'identification',
                'essay':             'essay',
                'fill_blank':        'fill_blank',
                'matching':          'matching',
            }

            newly_created_ids = []

            for i, uid in enumerate(manual_uids):
                q_text = manual_texts[i].strip()        if i < len(manual_texts)        else ''
                q_type = manual_types[i].strip()        if i < len(manual_types)        else ''
                q_diff = manual_difficulties[i].strip() if i < len(manual_difficulties) else 'medium'
                q_pts  = manual_points_list[i]          if i < len(manual_points_list)  else '1'
                q_ans  = manual_answers[i].strip()      if i < len(manual_answers)      else ''
                q_expl = manual_explanations[i].strip() if i < len(manual_explanations) else ''

                if not q_text or not q_type:
                    continue

                try:
                    q_pts = int(q_pts)
                except (ValueError, TypeError):
                    q_pts = 1

                resolved_type = type_name_map.get(q_type, q_type)

                try:
                    question_type_obj = QuestionType.objects.get(name=resolved_type)
                except QuestionType.DoesNotExist:
                    question_type_obj = QuestionType.objects.filter(is_active=True).first()
                    if not question_type_obj:
                        continue

                opt_a = manual_opts_a[i] if i < len(manual_opts_a) else None
                opt_b = manual_opts_b[i] if i < len(manual_opts_b) else None
                opt_c = manual_opts_c[i] if i < len(manual_opts_c) else None
                opt_d = manual_opts_d[i] if i < len(manual_opts_d) else None

                new_q = ExtractedQuestion.objects.create(
                    questionnaire  = questionnaire,
                    question_type  = question_type_obj,
                    question_text  = q_text,
                    correct_answer = q_ans,
                    explanation    = q_expl or None,
                    points         = q_pts,
                    difficulty     = q_diff,
                    is_approved    = True,
                    option_a       = opt_a or None,
                    option_b       = opt_b or None,
                    option_c       = opt_c or None,
                    option_d       = opt_d or None,
                )
                newly_created_ids.append(new_q.id)

            all_approved_ids = list(selected_ids) + [str(i) for i in newly_created_ids]

            if not all_approved_ids:
                messages.error(request, 'Please select at least one question.')
                return redirect('questionnaires:review_extracted', pk=pk)

            extracted_questions.filter(id__in=selected_ids).update(is_approved=True)
            extracted_questions.exclude(id__in=all_approved_ids).update(is_approved=False)

            final_title = request.POST.get('final_title', '').strip()
            if final_title:
                questionnaire.title = final_title
                questionnaire.save()

            total_saved = len(all_approved_ids)
            ActivityLog.objects.create(
                activity_type='questions_approved',
                user=request.user,
                description=(
                    f'Saved {total_saved} question(s) '
                    f'({len(newly_created_ids)} manual) for "{questionnaire.title}"'
                )
            )

            download_format = request.POST.get('download_format', 'none')
            if download_format != 'none':
                from django.urls import reverse
                download_url = reverse('questionnaires:download_questionnaire', args=[questionnaire.pk])
                return redirect(f"{download_url}?type=generated&format={download_format}")

            messages.success(request, f'Saved {total_saved} question(s) successfully!')
            return redirect('questionnaires:my_uploads')

        elif action == 'delete_question':
            question_id = request.POST.get('question_id')
            ExtractedQuestion.objects.filter(id=question_id, questionnaire=questionnaire).delete()
            messages.info(request, 'Question deleted.')
            return redirect('questionnaires:review_extracted', pk=pk)

        elif action == 'approve_all':
            extracted_questions.update(is_approved=True)
            ActivityLog.objects.create(
                activity_type='questions_approved',
                user=request.user,
                description=f'Approved all {extracted_questions.count()} questions for "{questionnaire.title}"'
            )
            messages.success(request, 'All questions approved!')
            return redirect('questionnaires:my_uploads')

        elif action == 'retry_extraction':
            return redirect('questionnaires:retry_extraction', pk=pk)

    question_types = QuestionType.objects.filter(
        id__in=extracted_questions.values_list('question_type', flat=True).distinct()
    )

    context = {
        'questionnaire':  questionnaire,
        'questions':      extracted_questions,
        'question_types': question_types,
        'total_points':   sum(q.points for q in extracted_questions),
    }

    return render(request, 'teacher_dashboard/review_extracted.html', context)


@login_required
def retry_extraction(request, pk):
    questionnaire = get_object_or_404(Questionnaire, pk=pk)

    if request.user.is_staff:
        can_retry = True
    elif hasattr(request.user, 'teacher_profile'):
        can_retry = questionnaire.uploader == request.user.teacher_profile
    else:
        can_retry = False

    if not can_retry:
        messages.error(request, 'You do not have permission to retry extraction.')
        return redirect('questionnaires:browse_questionnaires')

    if request.method == 'POST':
        question_type_ids = request.POST.getlist('question_types')

        if not question_type_ids:
            messages.error(request, 'Please select at least one question type.')
            return redirect('questionnaires:retry_extraction', pk=pk)

        try:
            questionnaire.extracted_questions.all().delete()
            questionnaire.extraction_status = 'processing'
            questionnaire.save()

            question_types = QuestionType.objects.filter(id__in=question_type_ids)
            type_names = [qt.name for qt in question_types]

            extractor = get_extractor()
            created_questions = extractor.process_questionnaire(questionnaire, type_names)

            questionnaire.extraction_status = 'completed'
            questionnaire.is_extracted = True
            questionnaire.extraction_error = None
            questionnaire.save()

            ActivityLog.objects.create(
                activity_type='questions_extracted',
                user=request.user,
                description=f'Re-extracted {len(created_questions)} questions from "{questionnaire.title}"'
            )

            messages.success(request, f'Successfully extracted {len(created_questions)} questions!')
            return redirect('questionnaires:review_extracted', pk=questionnaire.pk)

        except Exception as e:
            questionnaire.extraction_status = 'failed'
            questionnaire.extraction_error = str(e)
            questionnaire.save()

            messages.error(request, f'Extraction failed: {str(e)}')
            return redirect('questionnaires:retry_extraction', pk=pk)

    question_types = QuestionType.objects.filter(is_active=True)

    return render(request, 'teacher_dashboard/retry_extraction.html', {
        'questionnaire': questionnaire,
        'question_types': question_types,
    })


@login_required
def my_uploads(request):
    if request.user.is_staff:
        return redirect('accounts:admin_dashboard')

    teacher = get_object_or_404(TeacherProfile, user=request.user)
    questionnaires = Questionnaire.objects.filter(uploader=teacher).select_related('department', 'subject')

    search_query = request.GET.get('search', '')
    if search_query:
        questionnaires = questionnaires.filter(
            Q(title__icontains=search_query) |
            Q(description__icontains=search_query) |
            Q(subject__name__icontains=search_query)
        )

    paginator = Paginator(questionnaires, 10)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    context = {
        'page_obj': page_obj,
        'search_query': search_query,
    }
    return render(request, 'teacher_dashboard/my_uploads.html', context)


@login_required
def edit_questionnaire(request, pk):
    questionnaire = get_object_or_404(Questionnaire, pk=pk)

    if request.user.is_staff:
        can_edit = True
    elif hasattr(request.user, 'teacher_profile'):
        can_edit = questionnaire.uploader == request.user.teacher_profile
    else:
        can_edit = False

    if not can_edit:
        messages.error(request, 'You do not have permission to edit this questionnaire')
        return redirect('questionnaires:browse_questionnaires')

    if request.method == 'POST':
        form = QuestionnaireEditForm(request.POST, instance=questionnaire)
        if form.is_valid():
            form.save()

            ActivityLog.objects.create(
                activity_type='questionnaire_updated',
                user=request.user,
                description=f'Updated questionnaire "{questionnaire.title}"'
            )

            messages.success(request, 'Questionnaire updated successfully')
            if request.user.is_staff:
                return redirect('questionnaires:all_questionnaires')
            return redirect('questionnaires:my_uploads')
    else:
        form = QuestionnaireEditForm(instance=questionnaire)

    return render(request, 'teacher_dashboard/edit_questionnaire.html', {
        'form': form,
        'questionnaire': questionnaire
    })


@login_required
def delete_questionnaire(request, pk):
    questionnaire = get_object_or_404(Questionnaire, pk=pk)

    if request.user.is_staff:
        can_delete = True
    elif hasattr(request.user, 'teacher_profile'):
        can_delete = questionnaire.uploader == request.user.teacher_profile
    else:
        can_delete = False

    if not can_delete:
        messages.error(request, 'You do not have permission to delete this questionnaire')
        return redirect('questionnaires:browse_questionnaires')

    if request.method == 'POST':
        questionnaire_title = questionnaire.title

        ActivityLog.objects.create(
            activity_type='questionnaire_deleted',
            user=request.user,
            description=f'Deleted questionnaire "{questionnaire_title}"'
        )

        questionnaire.file.delete()
        questionnaire.delete()
        messages.success(request, 'Questionnaire deleted successfully')
        if request.user.is_staff:
            return redirect('questionnaires:all_questionnaires')
        return redirect('questionnaires:my_uploads')

    return render(request, 'teacher_dashboard/delete_questionnaire.html', {
        'questionnaire': questionnaire
    })


@login_required
def browse_questionnaires(request):
    if request.user.is_staff:
        return redirect('questionnaires:all_questionnaires')

    teacher = get_object_or_404(TeacherProfile, user=request.user)

    questionnaires = Questionnaire.objects.select_related(
        'department', 'subject', 'uploader__user'
    ).filter(subject__departments=teacher.department)

    # ── filters ──────────────────────────────────────────────────────────────
    subject_id   = request.GET.get('subject', '')
    exam_type    = request.GET.get('exam_type', '')          # ← new
    search_query = request.GET.get('search', '')

    if subject_id:
        questionnaires = questionnaires.filter(subject_id=subject_id)

    if exam_type:                                             # ← new
        questionnaires = questionnaires.filter(exam_type=exam_type)

    if search_query:
        questionnaires = questionnaires.filter(
            Q(title__icontains=search_query)       |
            Q(description__icontains=search_query) |
            Q(subject__name__icontains=search_query) |
            Q(subject__code__icontains=search_query)
        )

    subjects = Subject.objects.filter(departments=teacher.department)

    paginator   = Paginator(questionnaires, 12)
    page_number = request.GET.get('page')
    page_obj    = paginator.get_page(page_number)

    context = {
        'page_obj':         page_obj,
        'subjects':         subjects,
        'selected_subject': subject_id,
        'search_query':     search_query,
        'exam_type':        exam_type,                        # ← new
        'exam_type_choices': Questionnaire.EXAM_TYPE_CHOICES, # ← new
    }
    return render(request, 'teacher_dashboard/browse_questionnaires.html', context)



# ============================================================================
# FILE: questionnaires/views.py  — updated all_questionnaires() view only
#
# Replace your existing all_questionnaires() with this one.
# Everything else in your views.py stays the same.
# ============================================================================

@login_required
def all_questionnaires(request):
    if not request.user.is_staff:
        return redirect('questionnaires:browse_questionnaires')

    questionnaires = Questionnaire.objects.select_related(
        'department', 'subject', 'uploader__user'
    ).all()

    # ── filters ──────────────────────────────────────────────────────────────
    selected_department = request.GET.get('department', '')
    selected_subject    = request.GET.get('subject', '')
    exam_type           = request.GET.get('exam_type', '')   # ← new
    search_query        = request.GET.get('search', '')

    if selected_department:
        questionnaires = questionnaires.filter(department_id=selected_department)

    if selected_subject:
        questionnaires = questionnaires.filter(subject_id=selected_subject)

    if exam_type:                                            # ← new
        questionnaires = questionnaires.filter(exam_type=exam_type)

    if search_query:
        questionnaires = questionnaires.filter(
            Q(title__icontains=search_query)         |
            Q(description__icontains=search_query)   |
            Q(subject__name__icontains=search_query) |
            Q(subject__code__icontains=search_query)
        )

    departments = Department.objects.all()
    subjects    = Subject.objects.all()

    paginator   = Paginator(questionnaires, 12)
    page_number = request.GET.get('page')
    page_obj    = paginator.get_page(page_number)

    context = {
        'page_obj':            page_obj,
        'departments':         departments,
        'subjects':            subjects,
        'selected_department': selected_department,
        'selected_subject':    selected_subject,
        'search_query':        search_query,
        'exam_type':           exam_type,                    # ← new
        'exam_type_choices':   Questionnaire.EXAM_TYPE_CHOICES,  # ← new
    }
    return render(request, 'admin_dashboard/all_questionnaires.html', context)


@login_required
def download_questionnaire(request, pk):
    from .models import Download
    from .generators import generate_bisu_questionnaire
    import os

    questionnaire = get_object_or_404(Questionnaire, pk=pk)

    Download.objects.create(
        questionnaire=questionnaire,
        user=request.user if request.user.is_authenticated else None,
        ip_address=get_client_ip(request)
    )

    if hasattr(request.user, 'teacher_profile'):
        if questionnaire.uploader != request.user.teacher_profile:
            ActivityLog.objects.create(
                activity_type='questionnaire_downloaded',
                user=questionnaire.uploader.user,
                description=f'{request.user.get_full_name()} downloaded your "{questionnaire.title}"'
            )

    download_type = request.GET.get('type', 'original')

    if download_type == 'original':
        try:
            return FileResponse(
                questionnaire.file.open('rb'),
                as_attachment=True,
                filename=questionnaire.file.name.split('/')[-1]
            )
        except FileNotFoundError:
            raise Http404("File not found")

    elif download_type == 'generated':
        question_ids_param = request.GET.get('questions', '')

        if question_ids_param:
            try:
                question_ids = [int(i) for i in question_ids_param.split(',') if i.strip().isdigit()]
                selected_questions = questionnaire.extracted_questions.filter(
                    id__in=question_ids
                ).select_related('question_type').order_by('question_type__name', 'created_at')
            except (ValueError, TypeError):
                selected_questions = questionnaire.extracted_questions.filter(
                    is_approved=True
                ).select_related('question_type').order_by('question_type__name', 'created_at')
        else:
            selected_questions = questionnaire.extracted_questions.filter(
                is_approved=True
            ).select_related('question_type').order_by('question_type__name', 'created_at')

        if not selected_questions.exists():
            messages.warning(request, 'No questions available to generate the document.')
            return redirect('questionnaires:review_extracted', pk=pk)

        try:
            file_format = request.GET.get('format', 'docx').lower()
            docx_path, pdf_path = generate_bisu_questionnaire(questionnaire, selected_questions)

            if file_format == 'pdf' and pdf_path and os.path.exists(pdf_path):
                filepath     = pdf_path
                content_type = 'application/pdf'
                filename     = os.path.basename(pdf_path)
            else:
                filepath     = docx_path
                content_type = 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
                filename     = os.path.basename(docx_path)

            file_handle = open(filepath, 'rb')
            response    = FileResponse(file_handle, content_type=content_type)
            response['Content-Disposition'] = f'attachment; filename="{filename}"'
            return response

        except Exception as e:
            messages.error(request, f'Failed to generate questionnaire: {str(e)}')
            return redirect('questionnaires:review_extracted', pk=pk)

    else:
        raise Http404("Invalid download type")


@login_required
def get_subjects_ajax(request):
    department_id = request.GET.get('department')
    if department_id:
        subjects = Subject.objects.filter(departments__id=department_id).values('id', 'code', 'name')
        return JsonResponse({'subjects': list(subjects)})
    return JsonResponse({'subjects': []})


@login_required
def get_questions_json(request, pk):
    questionnaire = get_object_or_404(Questionnaire, pk=pk)

    questions_data = []
    for q in questionnaire.extracted_questions.select_related('question_type').order_by('created_at'):
        question_dict = {
            'id':             q.id,
            'question_text':  q.question_text,
            'type':           q.question_type.name,
            'type_display':   q.question_type.get_name_display(),
            'difficulty':     q.difficulty,
            'points':         q.points,
            'correct_answer': q.correct_answer,
            'explanation':    q.explanation or '',
        }
        if q.question_type.name == 'multiple_choice':
            question_dict['options'] = [
                q.option_a or '',
                q.option_b or '',
                q.option_c or '',
                q.option_d or '',
            ]
        questions_data.append(question_dict)

    return JsonResponse({
        'questionnaire_id':    questionnaire.pk,
        'questionnaire_title': questionnaire.title,
        'total':               len(questions_data),
        'questions':           questions_data,
    })


# ============================================================================
# WORKSPACE VIEWS  (now database-backed)
# ============================================================================

@login_required
def workspace(request):
    """Render the workspace page. All folder/question data is loaded from the DB."""
    if request.user.is_staff:
        messages.info(request, 'The workspace feature is for teachers only.')
        return redirect('accounts:admin_dashboard')

    teacher = get_object_or_404(TeacherProfile, user=request.user)

    # Load all folders with their questions in one efficient query
    folders = (
        WorkspaceFolder.objects
        .filter(teacher=teacher)
        .prefetch_related(
            'folder_questions__question__question_type',
            'folder_questions__question__questionnaire__subject',
        )
        .order_by('-created_at')
    )

    # Serialize folders → JSON-safe structure for the template
    folders_data = []
    for folder in folders:
        questions_data = []
        for fq in folder.folder_questions.all():
            q = fq.question
            qd = {
                'id':             q.pk,
                'question_text':  q.question_text,
                'type':           q.question_type.name,
                'type_display':   q.question_type.get_name_display(),
                'difficulty':     q.difficulty,
                'points':         q.points,
                'correct_answer': q.correct_answer,
                'explanation':    q.explanation or '',
                'subject_code':   q.questionnaire.subject.code,
                'subject_name':   q.questionnaire.subject.name,
            }
            if q.question_type.name == 'multiple_choice':
                qd['options'] = [
                    q.option_a or '',
                    q.option_b or '',
                    q.option_c or '',
                    q.option_d or '',
                ]
            questions_data.append(qd)

        folders_data.append({
            'id':         folder.pk,
            'name':       folder.name,
            'created_at': folder.created_at.isoformat(),
            'questions':  questions_data,
        })

    import json
    context = {
        'folders_json': json.dumps(folders_data),
    }
    return render(request, 'teacher_dashboard/workspace.html', context)


# ── Workspace API endpoints ───────────────────────────────────────────────────
# All return JSON.  The workspace template calls these via fetch().

@login_required
@require_POST
def workspace_create_folder(request):
    """POST { name } → create a new folder, return { id, name }"""
    if request.user.is_staff:
        return JsonResponse({'error': 'Not allowed'}, status=403)

    teacher = get_object_or_404(TeacherProfile, user=request.user)

    import json as _json
    try:
        body = _json.loads(request.body)
    except ValueError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)

    name = (body.get('name') or '').strip()[:80]
    if not name:
        return JsonResponse({'error': 'Folder name is required.'}, status=400)

    folder = WorkspaceFolder.objects.create(teacher=teacher, name=name)
    return JsonResponse({'id': folder.pk, 'name': folder.name})


@login_required
@require_POST
def workspace_rename_folder(request, folder_id):
    """POST { name } → rename folder"""
    teacher = get_object_or_404(TeacherProfile, user=request.user)
    folder  = get_object_or_404(WorkspaceFolder, pk=folder_id, teacher=teacher)

    import json as _json
    try:
        body = _json.loads(request.body)
    except ValueError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)

    name = (body.get('name') or '').strip()[:80]
    if not name:
        return JsonResponse({'error': 'Folder name is required.'}, status=400)

    folder.name = name
    folder.save()
    return JsonResponse({'id': folder.pk, 'name': folder.name})


@login_required
@require_POST
def workspace_delete_folder(request, folder_id):
    """POST → delete folder and all its question links"""
    teacher = get_object_or_404(TeacherProfile, user=request.user)
    folder  = get_object_or_404(WorkspaceFolder, pk=folder_id, teacher=teacher)
    name    = folder.name
    folder.delete()    # cascades to WorkspaceFolderQuestion rows
    return JsonResponse({'deleted': True, 'name': name})


@login_required
@require_POST
def workspace_add_questions(request, folder_id):
    """
    POST { question_ids: [int, ...] } → add questions to folder.
    Returns { added: N, already_existed: M }
    """
    if request.user.is_staff:
        return JsonResponse({'error': 'Not allowed'}, status=403)

    teacher = get_object_or_404(TeacherProfile, user=request.user)
    folder  = get_object_or_404(WorkspaceFolder, pk=folder_id, teacher=teacher)

    import json as _json
    try:
        body = _json.loads(request.body)
    except ValueError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)

    question_ids = body.get('question_ids', [])
    if not isinstance(question_ids, list):
        return JsonResponse({'error': 'question_ids must be a list'}, status=400)

    # Access control: only questions from questionnaires in the teacher's department
    allowed_questions = ExtractedQuestion.objects.filter(
        pk__in=question_ids,
        questionnaire__subject__departments=teacher.department,
    )

    added = 0
    already = 0
    for q in allowed_questions:
        _, created = WorkspaceFolderQuestion.objects.get_or_create(folder=folder, question=q)
        if created:
            added += 1
        else:
            already += 1

    return JsonResponse({'added': added, 'already_existed': already})


@login_required
@require_POST
def workspace_remove_question(request, folder_id, question_id):
    """POST → remove a single question from a folder"""
    teacher = get_object_or_404(TeacherProfile, user=request.user)
    folder  = get_object_or_404(WorkspaceFolder, pk=folder_id, teacher=teacher)
    WorkspaceFolderQuestion.objects.filter(folder=folder, question_id=question_id).delete()
    return JsonResponse({'removed': True})


@login_required
def download_workspace(request):
    """
    Download a combined BISU-format document from a workspace folder selection.

    Query-string parameters
    -----------------------
    format    : 'docx' (default) | 'pdf'
    questions : comma-separated ExtractedQuestion PKs
    """
    import os
    from .generators import generate_bisu_questionnaire

    if request.user.is_staff:
        messages.error(request, 'Admins cannot use the workspace download.')
        return redirect('accounts:admin_dashboard')

    question_ids_param = request.GET.get('questions', '').strip()

    if not question_ids_param:
        messages.error(request, 'No questions specified for download.')
        return redirect('questionnaires:workspace')

    try:
        question_ids = [
            int(i) for i in question_ids_param.split(',')
            if i.strip().isdigit()
        ]
    except (ValueError, TypeError):
        messages.error(request, 'Invalid question selection.')
        return redirect('questionnaires:workspace')

    if not question_ids:
        messages.error(request, 'No valid question IDs provided.')
        return redirect('questionnaires:workspace')

    teacher = get_object_or_404(TeacherProfile, user=request.user)

    selected_questions = ExtractedQuestion.objects.filter(
        pk__in=question_ids,
        questionnaire__subject__departments=teacher.department,
    ).select_related(
        'question_type',
        'questionnaire',
        'questionnaire__subject',
        'questionnaire__department',
    ).order_by(
        'questionnaire__subject__code',
        'question_type__name',
        'created_at',
    )

    if not selected_questions.exists():
        messages.error(request, 'None of the selected questions could be found.')
        return redirect('questionnaires:workspace')

    first_quest = selected_questions.first().questionnaire

    class WorkspaceQuestionnaireProxy:
        def __init__(self, base_questionnaire, questions):
            self.pk          = None
            self.title       = 'Workspace Selection'
            self.description = (
                f'Combined questionnaire — {questions.count()} question(s) '
                f'from {questions.values("questionnaire__subject__code").distinct().count()} subject(s)'
            )
            self.department  = base_questionnaire.department
            self.subject     = base_questionnaire.subject
            self.uploader    = base_questionnaire.uploader

    proxy = WorkspaceQuestionnaireProxy(first_quest, selected_questions)

    try:
        file_format = request.GET.get('format', 'docx').lower()
        docx_path, pdf_path = generate_bisu_questionnaire(proxy, selected_questions)

        if file_format == 'pdf' and pdf_path and os.path.exists(pdf_path):
            filepath     = pdf_path
            content_type = 'application/pdf'
            filename     = 'BISU_Workspace_Questionnaire.pdf'
        else:
            filepath     = docx_path
            content_type = (
                'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
            )
            filename = 'BISU_Workspace_Questionnaire.docx'

        ActivityLog.objects.create(
            activity_type='questionnaire_downloaded',
            user=request.user,
            description=(
                f'Downloaded workspace selection: '
                f'{selected_questions.count()} question(s) from '
                f'{selected_questions.values("questionnaire__subject__code").distinct().count()} subject(s)'
            )
        )

        file_handle = open(filepath, 'rb')
        response    = FileResponse(file_handle, content_type=content_type)
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        return response

    except Exception as e:
        messages.error(request, f'Failed to generate workspace document: {str(e)}')
        return redirect('questionnaires:workspace')
    
@login_required
def workspace_list_folders(request):
    """GET → return all folders + all question IDs in workspace (for browse page)"""
    if request.user.is_staff:
        return JsonResponse({'folders': [], 'question_ids_in_workspace': []})

    teacher = get_object_or_404(TeacherProfile, user=request.user)
    folders = WorkspaceFolder.objects.filter(teacher=teacher).prefetch_related('folder_questions').order_by('-created_at')

    folders_data = []
    all_question_ids = []
    for folder in folders:
        qids = list(folder.folder_questions.values_list('question_id', flat=True))
        all_question_ids.extend(qids)
        folders_data.append({
            'id':             folder.pk,
            'name':           folder.name,
            'question_count': len(qids),
        })

    return JsonResponse({
        'folders':                  folders_data,
        'question_ids_in_workspace': list(set(all_question_ids)),
    })