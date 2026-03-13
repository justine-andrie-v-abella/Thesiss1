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

def get_client_ip(request):
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        return x_forwarded_for.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR')

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
# HELPER: build a list of plain dicts from ExtractedQuestion objects
# so we can store them in the session (no DB objects in session).
# ============================================================================

def _questions_to_session(questions):
    """
    Convert a list/queryset of ExtractedQuestion objects into a list of
    plain dicts safe for Django session storage.
    """
    result = []
    for q in questions:
        result.append({
            'question_text':  q.question_text,
            'question_type':  q.question_type.name,
            'difficulty':     q.difficulty,
            'points':         q.points,
            'correct_answer': q.correct_answer,
            'explanation':    q.explanation or '',
            'option_a':       q.option_a or '',
            'option_b':       q.option_b or '',
            'option_c':       q.option_c or '',
            'option_d':       q.option_d or '',
        })
    return result


def _clear_pending_session(request):
    """Remove all pending questionnaire data from session."""
    request.session.pop('pending_questionnaire', None)
    request.session.pop('pending_questions', None)
    request.session.modified = True


# ============================================================================
# UPLOAD VIEW  —  now stores in session, does NOT save to DB
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
            # ── Build a temporary (unsaved) Questionnaire so the extractor
            #    can read the file field. We'll only persist it on Save. ──────
            questionnaire = form.save(commit=False)
            questionnaire.uploader   = teacher
            questionnaire.department = teacher.department
            questionnaire.exam_type  = form.cleaned_data['exam_type']

            # Save ONLY to get a file on disk (needed by the extractor).
            # We mark extraction_status='processing' temporarily.
            questionnaire.extraction_status = 'processing'
            questionnaire.save()

            try:
                type_names = list(
                    QuestionType.objects.filter(is_active=True).values_list('name', flat=True)
                )

                extractor = get_extractor()
                # process_questionnaire saves ExtractedQuestion rows to DB.
                # We'll grab them, serialise to dicts, then delete everything.
                created_questions = extractor.process_questionnaire(
                    questionnaire, type_names, mode='extract'
                )

                if not created_questions:
                    # Nothing extracted — clean up and bail
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

                # ── Serialise questions to plain dicts ────────────────────────
                session_questions = _questions_to_session(
                    questionnaire.extracted_questions.select_related('question_type').all()
                )

                # ── Store form data + questions in session ────────────────────
                request.session['pending_questionnaire'] = {
                    'title':       questionnaire.title,
                    'description': questionnaire.description,
                    'subject_id':  questionnaire.subject_id,
                    'exam_type':   questionnaire.exam_type,
                    'source':      'extract',
                }
                request.session['pending_questions'] = session_questions
                request.session.modified = True

                # ── Delete the temporary DB records — nothing persists yet ────
                questionnaire.extracted_questions.all().delete()
                questionnaire.file.delete(save=False)
                questionnaire.delete()

                messages.success(
                    request,
                    f'Extracted {len(session_questions)} questions! '
                    f'Now select the ones you want to keep.',
                )
                return redirect('questionnaires:review_extracted')

            except Exception as e:
                # Clean up on failure
                try:
                    questionnaire.file.delete(save=False)
                    questionnaire.delete()
                except Exception:
                    pass

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


# ============================================================================
# GENERATE VIEW  —  now stores in session, does NOT save to DB
# ============================================================================

@login_required
def generate_questionnaire(request):
    if request.user.is_staff:
        messages.error(request, 'Admins cannot generate questionnaires.')
        return redirect('accounts:admin_dashboard')

    teacher = get_object_or_404(TeacherProfile, user=request.user)

    if request.method == 'POST':
        form = QuestionnaireUploadForm(request.POST, request.FILES, user=request.user)

        if form.is_valid():
            questionnaire                    = form.save(commit=False)
            questionnaire.uploader          = teacher
            questionnaire.department        = teacher.department
            questionnaire.exam_type         = form.cleaned_data['exam_type']
            questionnaire.extraction_status = 'processing'
            questionnaire.save()

            try:
                # ── Determine which question types the teacher wants ──────────
                question_types_qs = form.cleaned_data.get('question_types')
                if question_types_qs:
                    type_names = [qt.name for qt in question_types_qs]
                else:
                    type_names = list(
                        QuestionType.objects.filter(is_active=True)
                                            .values_list('name', flat=True)
                    )

                try:
                    num_questions = int(request.POST.get('num_questions', 10))
                    num_questions = max(1, min(num_questions, 30))
                except (ValueError, TypeError):
                    num_questions = 10

                extractor = get_extractor()
                created_questions = extractor.process_questionnaire(
                    questionnaire,
                    type_names,
                    mode='generate',
                    num_questions=num_questions,
                )

                if not created_questions:
                    questionnaire.file.delete(save=False)
                    questionnaire.delete()
                    messages.error(
                        request,
                        'The AI could not generate any questions from this file. '
                        'Please upload a more content-rich document and try again.',
                    )
                    return render(
                        request,
                        'teacher_dashboard/generate_questionnaire.html',
                        {'form': form},
                    )

                # ── Serialise generated questions to plain dicts ──────────────
                session_questions = _questions_to_session(
                    questionnaire.extracted_questions.select_related('question_type').all()
                )

                # ── Store in session ──────────────────────────────────────────
                request.session['pending_questionnaire'] = {
                    'title':       questionnaire.title,
                    'description': questionnaire.description,
                    'subject_id':  questionnaire.subject_id,
                    'exam_type':   questionnaire.exam_type,
                    'source':      'generate',
                }
                request.session['pending_questions'] = session_questions
                request.session.modified = True

                # ── Delete temporary DB records ───────────────────────────────
                questionnaire.extracted_questions.all().delete()
                questionnaire.file.delete(save=False)
                questionnaire.delete()

                messages.success(
                    request,
                    f'AI generated {len(session_questions)} question(s)! '
                    f'Review and save the ones you want to your workspace.',
                )
                return redirect('questionnaires:review_extracted')

            except Exception as e:
                try:
                    questionnaire.file.delete(save=False)
                    questionnaire.delete()
                except Exception:
                    pass

                ActivityLog.objects.create(
                    activity_type='extraction_failed',
                    user=request.user,
                    description='AI question generation failed — file was not saved.',
                )

                messages.error(
                    request,
                    f'AI generation failed: {str(e)}. '
                    f'Your file was not saved. Please try again.',
                )
                return render(
                    request,
                    'teacher_dashboard/generate_questionnaire.html',
                    {'form': form},
                )
        else:
            messages.error(request, 'Please correct the errors below.')

    else:
        form = QuestionnaireUploadForm(user=request.user)

    return render(
        request,
        'teacher_dashboard/generate_questionnaire.html',
        {'form': form},
    )


# ============================================================================
# CANCEL PENDING  —  clears session and redirects back to upload
# ============================================================================

@login_required
def cancel_pending(request):
    """
    Called when the teacher clicks 'Cancel & Discard' on the extract-mode
    review page.  Clears session data so nothing is left behind, then
    sends the teacher back to the upload page.

    NOTE: generate mode does NOT use this — its workspace button stays
    pointing to the workspace page as before.
    """
    _clear_pending_session(request)
    messages.info(request, 'Upload cancelled. No questions were saved.')
    return redirect('questionnaires:upload_questionnaire')


# ============================================================================
# REVIEW VIEW  —  session-based (no pk), writes to DB only on Save
# ============================================================================

@login_required
def review_extracted_questions(request):
    """
    GET  : render review page from session data (nothing in DB yet).
    POST : on 'save_selected' — persist Questionnaire + chosen questions to DB,
           clear session.
           on 'delete_question' — remove a question from the session list.
    """
    if request.user.is_staff:
        messages.error(request, 'Admins cannot review extracted questions.')
        return redirect('accounts:admin_dashboard')

    # ── Redirect if no session data (e.g. user navigated here directly) ──────
    pending_meta = request.session.get('pending_questionnaire')
    pending_qs   = request.session.get('pending_questions', [])

    if not pending_meta:
        messages.error(request, 'No pending questionnaire found. Please upload again.')
        return redirect('questionnaires:upload_questionnaire')

    source = pending_meta.get('source', 'extract')

    # ── Helper: build a fake object the template can iterate ─────────────────
    class _FakeQuestionType:
        def __init__(self, name):
            self.name = name
            self._display = name.replace('_', ' ').title()
        def get_name_display(self):
            return self._display

    class _FakeQuestion:
        def __init__(self, index, data):
            self.id            = index          # used as checkbox value
            self.question_text = data['question_text']
            self.difficulty    = data['difficulty']
            self.points        = data['points']
            self.correct_answer = data['correct_answer']
            self.explanation   = data.get('explanation', '')
            self.is_approved   = True
            self.question_type = _FakeQuestionType(data['question_type'])
            # options_list matches the template: [('a', text), ...]
            self.options_list  = [
                ('a', data.get('option_a', '')),
                ('b', data.get('option_b', '')),
                ('c', data.get('option_c', '')),
                ('d', data.get('option_d', '')),
            ]

    class _FakeQuestionnaire:
        def __init__(self, meta):
            self.title       = meta['title']
            self.description = meta.get('description', '')

    # ── POST ──────────────────────────────────────────────────────────────────
    if request.method == 'POST':
        action = request.POST.get('action')

        # ── Delete a single question from the session list ────────────────────
        if action == 'delete_question':
            idx_str = request.POST.get('question_id')
            try:
                idx = int(idx_str)
                pending_qs.pop(idx)
                request.session['pending_questions'] = pending_qs
                request.session.modified = True
                return JsonResponse({'ok': True})
            except (ValueError, IndexError):
                return JsonResponse({'error': 'Invalid index'}, status=400)

        # ── Save selected questions to DB ─────────────────────────────────────
        if action == 'save_selected':
            selected_indices = request.POST.getlist('selected_questions')

            # ── Collect manually-added questions from the form ────────────────
            manual_uids         = request.POST.getlist('manual_selected_uid[]')
            manual_texts        = request.POST.getlist('manual_question_text[]')
            manual_types        = request.POST.getlist('manual_question_type[]')
            manual_difficulties = request.POST.getlist('manual_difficulty[]')
            manual_points_list  = request.POST.getlist('manual_points[]')
            manual_answers      = request.POST.getlist('manual_correct_answer[]')
            manual_explanations = request.POST.getlist('manual_explanation[]')
            manual_opts_a       = request.POST.getlist('manual_option_A[]')
            manual_opts_b       = request.POST.getlist('manual_option_B[]')
            manual_opts_c       = request.POST.getlist('manual_option_C[]')
            manual_opts_d       = request.POST.getlist('manual_option_D[]')

            type_name_map = {
                'fill_in_the_blank': 'fill_blank',
                'multiple_choice':   'multiple_choice',
                'true_false':        'true_false',
                'identification':    'identification',
                'essay':             'essay',
                'fill_blank':        'fill_blank',
                'matching':          'matching',
            }

            has_ai      = len(selected_indices) > 0
            has_manual  = len(manual_uids) > 0

            if not has_ai and not has_manual:
                if source == 'generate':
                    return JsonResponse({'success': False, 'error': 'Please select at least one question.'})
                messages.error(request, 'Please select at least one question.')
                # Re-render review page (session still intact)
                fake_questions = [_FakeQuestion(i, q) for i, q in enumerate(pending_qs)]
                used_types = {q['question_type'] for q in pending_qs}
                fake_types = [_FakeQuestionType(t) for t in used_types]
                return render(request, 'teacher_dashboard/review_extracted.html', {
                    'questionnaire':  _FakeQuestionnaire(pending_meta),
                    'questions':      fake_questions,
                    'question_types': fake_types,
                    'source':         source,
                })

            # ── NOW create the Questionnaire in the DB ────────────────────────
            teacher  = get_object_or_404(TeacherProfile, user=request.user)
            subject  = get_object_or_404(Subject, pk=pending_meta['subject_id'])

            final_title = request.POST.get('final_title', '').strip() or pending_meta['title']

            questionnaire = Questionnaire(
                title             = final_title,
                description       = pending_meta.get('description', ''),
                subject           = subject,
                department        = teacher.department,
                exam_type         = pending_meta['exam_type'],
                uploader          = teacher,
                extraction_status = 'completed',
                is_extracted      = True,
                # file is blank — generate mode never stores a file,
                # and extract mode cleaned up the temp file already.
                file_size         = 0,
                file_type         = 'txt',
            )
            # file field is required by the model's save() — bypass size/type calc
            questionnaire.file = ''
            # Use update_fields to skip the save() override that reads file.size
            questionnaire.save()

            # ── Save AI-extracted questions that were selected ─────────────────
            newly_created_ids = []

            for idx_str in selected_indices:
                try:
                    idx = int(idx_str)
                    q   = pending_qs[idx]
                except (ValueError, IndexError):
                    continue

                resolved_type = type_name_map.get(q['question_type'], q['question_type'])
                try:
                    q_type_obj = QuestionType.objects.get(name=resolved_type)
                except QuestionType.DoesNotExist:
                    q_type_obj = QuestionType.objects.filter(is_active=True).first()
                    if not q_type_obj:
                        continue

                new_q = ExtractedQuestion.objects.create(
                    questionnaire  = questionnaire,
                    question_type  = q_type_obj,
                    question_text  = q['question_text'],
                    correct_answer = q['correct_answer'],
                    explanation    = q.get('explanation') or None,
                    points         = q['points'],
                    difficulty     = q['difficulty'],
                    is_approved    = True,
                    option_a       = q.get('option_a') or None,
                    option_b       = q.get('option_b') or None,
                    option_c       = q.get('option_c') or None,
                    option_d       = q.get('option_d') or None,
                )
                newly_created_ids.append(new_q.id)

            # ── Save manually-added questions ─────────────────────────────────
            manual_created_ids = []

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
                    q_type_obj = QuestionType.objects.get(name=resolved_type)
                except QuestionType.DoesNotExist:
                    q_type_obj = QuestionType.objects.filter(is_active=True).first()
                    if not q_type_obj:
                        continue

                new_q = ExtractedQuestion.objects.create(
                    questionnaire  = questionnaire,
                    question_type  = q_type_obj,
                    question_text  = q_text,
                    correct_answer = q_ans,
                    explanation    = q_expl or None,
                    points         = q_pts,
                    difficulty     = q_diff,
                    is_approved    = True,
                    option_a       = manual_opts_a[i] if i < len(manual_opts_a) else None,
                    option_b       = manual_opts_b[i] if i < len(manual_opts_b) else None,
                    option_c       = manual_opts_c[i] if i < len(manual_opts_c) else None,
                    option_d       = manual_opts_d[i] if i < len(manual_opts_d) else None,
                )
                manual_created_ids.append(new_q.id)

            all_saved_ids = newly_created_ids + manual_created_ids
            total_saved   = len(all_saved_ids)

            # ── Activity logs ─────────────────────────────────────────────────
            ActivityLog.objects.create(
                activity_type='questionnaire_uploaded',
                user=request.user,
                description=(
                    f'You uploaded "{questionnaire.title}" '
                    f'for {questionnaire.subject.code}'
                ),
            )
            ActivityLog.objects.create(
                activity_type='questions_approved',
                user=request.user,
                description=(
                    f'Saved {total_saved} question(s) '
                    f'({len(manual_created_ids)} manual) for "{questionnaire.title}"'
                ),
            )

            # ── Clear session — work is done ──────────────────────────────────
            _clear_pending_session(request)

            # ── GENERATE MODE: also save to workspace folder ──────────────────
            if source == 'generate':
                folder_id = request.POST.get('workspace_folder_id', '').strip()

                if not folder_id:
                    # Still saved to DB — just no folder attached yet
                    return JsonResponse({'success': False, 'error': 'No workspace folder selected.'})

                try:
                    folder = WorkspaceFolder.objects.get(pk=folder_id, teacher=teacher)
                except WorkspaceFolder.DoesNotExist:
                    return JsonResponse({'success': False, 'error': 'Workspace folder not found.'})

                added   = 0
                already = 0
                for qid in all_saved_ids:
                    try:
                        q = ExtractedQuestion.objects.get(pk=qid)
                    except ExtractedQuestion.DoesNotExist:
                        continue
                    _, created = WorkspaceFolderQuestion.objects.get_or_create(
                        folder=folder, question=q
                    )
                    if created:
                        added += 1
                    else:
                        already += 1

                ActivityLog.objects.create(
                    activity_type='questions_approved',
                    user=request.user,
                    description=(
                        f'Saved {added} generated question(s) to workspace folder '
                        f'"{folder.name}" from "{questionnaire.title}"'
                    ),
                )

                return JsonResponse({
                    'success':     True,
                    'added':       added,
                    'already':     already,
                    'folder_name': folder.name,
                    'total_saved': total_saved,
                })

            # ── EXTRACT MODE: download or redirect ────────────────────────────
            download_format = request.POST.get('download_format', 'none')
            if download_format != 'none':
                from django.urls import reverse
                download_url = reverse('questionnaires:download_questionnaire', args=[questionnaire.pk])
                return redirect(f"{download_url}?type=generated&format={download_format}")

            messages.success(request, f'Saved {total_saved} question(s) successfully!')
            return redirect('questionnaires:my_uploads')

    # ── GET  ──────────────────────────────────────────────────────────────────
    fake_questions = [_FakeQuestion(i, q) for i, q in enumerate(pending_qs)]
    used_types     = {q['question_type'] for q in pending_qs}

    class _FakeQuestionTypeWithCount(_FakeQuestionType):
        pass

    fake_types = [_FakeQuestionTypeWithCount(t) for t in used_types]

    context = {
        'questionnaire':  _FakeQuestionnaire(pending_meta),
        'questions':      fake_questions,
        'question_types': fake_types,
        'total_points':   sum(q['points'] for q in pending_qs),
        'source':         source,
    }
    return render(request, 'teacher_dashboard/review_extracted.html', context)


# ============================================================================
# RETRY EXTRACTION  (unchanged — only relevant after a questionnaire is saved)
# ============================================================================

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
            return redirect('questionnaires:review_extracted_pk', pk=questionnaire.pk)

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


# ============================================================================
# REVIEW BY PK  —  kept for retry_extraction and any direct DB-backed review
# ============================================================================

@login_required
def review_extracted_questions_pk(request, pk):
    """
    Legacy review view used only by retry_extraction (already saved to DB).
    The main upload/generate flow now uses review_extracted_questions (session-based).
    """
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
    source = request.GET.get('source', request.POST.get('source', 'extract'))

    if request.method == 'POST':
        action = request.POST.get('action')
        source = request.POST.get('source', 'extract')

        if action == 'save_selected':
            selected_ids        = request.POST.getlist('selected_questions')
            manual_uids         = request.POST.getlist('manual_selected_uid[]')
            manual_texts        = request.POST.getlist('manual_question_text[]')
            manual_types        = request.POST.getlist('manual_question_type[]')
            manual_difficulties = request.POST.getlist('manual_difficulty[]')
            manual_points_list  = request.POST.getlist('manual_points[]')
            manual_answers      = request.POST.getlist('manual_correct_answer[]')
            manual_explanations = request.POST.getlist('manual_explanation[]')
            manual_opts_a       = request.POST.getlist('manual_option_A[]')
            manual_opts_b       = request.POST.getlist('manual_option_B[]')
            manual_opts_c       = request.POST.getlist('manual_option_C[]')
            manual_opts_d       = request.POST.getlist('manual_option_D[]')

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
                    q_type_obj = QuestionType.objects.get(name=resolved_type)
                except QuestionType.DoesNotExist:
                    q_type_obj = QuestionType.objects.filter(is_active=True).first()
                    if not q_type_obj:
                        continue
                new_q = ExtractedQuestion.objects.create(
                    questionnaire=questionnaire, question_type=q_type_obj,
                    question_text=q_text, correct_answer=q_ans,
                    explanation=q_expl or None, points=q_pts, difficulty=q_diff,
                    is_approved=True,
                    option_a=manual_opts_a[i] if i < len(manual_opts_a) else None,
                    option_b=manual_opts_b[i] if i < len(manual_opts_b) else None,
                    option_c=manual_opts_c[i] if i < len(manual_opts_c) else None,
                    option_d=manual_opts_d[i] if i < len(manual_opts_d) else None,
                )
                newly_created_ids.append(new_q.id)

            all_approved_ids = list(selected_ids) + [str(i) for i in newly_created_ids]
            if not all_approved_ids:
                messages.error(request, 'Please select at least one question.')
                return redirect('questionnaires:review_extracted_pk', pk=pk)

            extracted_questions.filter(id__in=selected_ids).update(is_approved=True)
            extracted_questions.exclude(id__in=all_approved_ids).update(is_approved=False)

            final_title = request.POST.get('final_title', '').strip()
            if final_title:
                questionnaire.title = final_title
                questionnaire.save()

            total_saved = len(all_approved_ids)
            ActivityLog.objects.create(
                activity_type='questions_approved', user=request.user,
                description=f'Saved {total_saved} question(s) for "{questionnaire.title}"'
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
            return JsonResponse({'ok': True})

    question_types = QuestionType.objects.filter(
        id__in=extracted_questions.values_list('question_type', flat=True).distinct()
    )
    context = {
        'questionnaire':  questionnaire,
        'questions':      extracted_questions,
        'question_types': question_types,
        'total_points':   sum(q.points for q in extracted_questions),
        'source':         source,
    }
    return render(request, 'teacher_dashboard/review_extracted.html', context)


# ============================================================================
# REST OF VIEWS  (unchanged)
# ============================================================================

@login_required
def my_uploads(request):
    if request.user.is_staff:
        return redirect('accounts:admin_dashboard')

    teacher = get_object_or_404(TeacherProfile, user=request.user)

    questionnaires = (
        Questionnaire.objects
        .filter(uploader=teacher)
        .exclude(file='')
        .select_related('department', 'subject')
    )

    search_query = request.GET.get('search', '')
    if search_query:
        questionnaires = questionnaires.filter(
            Q(title__icontains=search_query) |
            Q(description__icontains=search_query) |
            Q(subject__name__icontains=search_query)
        )

    paginator   = Paginator(questionnaires, 10)
    page_number = request.GET.get('page')
    page_obj    = paginator.get_page(page_number)

    return render(request, 'teacher_dashboard/my_uploads.html', {
        'page_obj':     page_obj,
        'search_query': search_query,
    })


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
        'questionnaire': questionnaire,
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
        'questionnaire': questionnaire,
    })


@login_required
def browse_questionnaires(request):
    if request.user.is_staff:
        return redirect('questionnaires:all_questionnaires')

    teacher = get_object_or_404(TeacherProfile, user=request.user)

    questionnaires = Questionnaire.objects.select_related(
        'department', 'subject', 'uploader__user'
    ).filter(
        subject__departments=teacher.department
    ).exclude(file='')

    subject_id   = request.GET.get('subject', '')
    exam_type    = request.GET.get('exam_type', '')
    search_query = request.GET.get('search', '')

    if subject_id:
        questionnaires = questionnaires.filter(subject_id=subject_id)
    if exam_type:
        questionnaires = questionnaires.filter(exam_type=exam_type)
    if search_query:
        questionnaires = questionnaires.filter(
            Q(title__icontains=search_query)       |
            Q(description__icontains=search_query) |
            Q(subject__name__icontains=search_query) |
            Q(subject__code__icontains=search_query)
        )

    subjects    = Subject.objects.filter(departments=teacher.department)
    paginator   = Paginator(questionnaires, 12)
    page_number = request.GET.get('page')
    page_obj    = paginator.get_page(page_number)

    return render(request, 'teacher_dashboard/browse_questionnaires.html', {
        'page_obj':          page_obj,
        'subjects':          subjects,
        'selected_subject':  subject_id,
        'search_query':      search_query,
        'exam_type':         exam_type,
        'exam_type_choices': Questionnaire.EXAM_TYPE_CHOICES,
    })


@login_required
def all_questionnaires(request):
    if not request.user.is_staff:
        return redirect('questionnaires:browse_questionnaires')

    questionnaires = Questionnaire.objects.select_related(
        'department', 'subject', 'uploader__user'
    ).exclude(file='')

    selected_department = request.GET.get('department', '')
    selected_subject    = request.GET.get('subject', '')
    exam_type           = request.GET.get('exam_type', '')
    search_query        = request.GET.get('search', '')

    if selected_department:
        questionnaires = questionnaires.filter(department_id=selected_department)
    if selected_subject:
        questionnaires = questionnaires.filter(subject_id=selected_subject)
    if exam_type:
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

    return render(request, 'admin_dashboard/all_questionnaires.html', {
        'page_obj':            page_obj,
        'departments':         departments,
        'subjects':            subjects,
        'selected_department': selected_department,
        'selected_subject':    selected_subject,
        'search_query':        search_query,
        'exam_type':           exam_type,
        'exam_type_choices':   Questionnaire.EXAM_TYPE_CHOICES,
    })


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
            return redirect('questionnaires:my_uploads')

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
            return redirect('questionnaires:my_uploads')

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
                q.option_a or '', q.option_b or '',
                q.option_c or '', q.option_d or '',
            ]
        questions_data.append(question_dict)

    return JsonResponse({
        'questionnaire_id':    questionnaire.pk,
        'questionnaire_title': questionnaire.title,
        'total':               len(questions_data),
        'questions':           questions_data,
    })


# ============================================================================
# WORKSPACE VIEWS  (unchanged)
# ============================================================================

@login_required
def workspace(request):
    if request.user.is_staff:
        messages.info(request, 'The workspace feature is for teachers only.')
        return redirect('accounts:admin_dashboard')

    teacher = get_object_or_404(TeacherProfile, user=request.user)

    folders = (
        WorkspaceFolder.objects
        .filter(teacher=teacher)
        .prefetch_related(
            'folder_questions__question__question_type',
            'folder_questions__question__questionnaire__subject',
        )
        .order_by('-created_at')
    )

    folders_data = []
    for folder in folders:
        questions_data = []
        for fq in folder.folder_questions.all():
            q  = fq.question
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
                    q.option_a or '', q.option_b or '',
                    q.option_c or '', q.option_d or '',
                ]
            questions_data.append(qd)

        folders_data.append({
            'id':         folder.pk,
            'name':       folder.name,
            'created_at': folder.created_at.isoformat(),
            'questions':  questions_data,
        })

    import json
    return render(request, 'teacher_dashboard/workspace.html', {
        'folders_json': json.dumps(folders_data),
    })


@login_required
@require_POST
def workspace_create_folder(request):
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
    teacher = get_object_or_404(TeacherProfile, user=request.user)
    folder  = get_object_or_404(WorkspaceFolder, pk=folder_id, teacher=teacher)
    name    = folder.name
    folder.delete()
    return JsonResponse({'deleted': True, 'name': name})


@login_required
@require_POST
def workspace_add_questions(request, folder_id):
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
    teacher = get_object_or_404(TeacherProfile, user=request.user)
    folder  = get_object_or_404(WorkspaceFolder, pk=folder_id, teacher=teacher)
    WorkspaceFolderQuestion.objects.filter(folder=folder, question_id=question_id).delete()
    return JsonResponse({'removed': True})


@login_required
def download_workspace(request):
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
        'question_type', 'questionnaire',
        'questionnaire__subject', 'questionnaire__department',
    ).order_by(
        'questionnaire__subject__code', 'question_type__name', 'created_at',
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
            content_type = 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
            filename     = 'BISU_Workspace_Questionnaire.docx'

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
    if request.user.is_staff:
        return JsonResponse({'folders': [], 'question_ids_in_workspace': []})

    teacher = get_object_or_404(TeacherProfile, user=request.user)
    folders = (
        WorkspaceFolder.objects
        .filter(teacher=teacher)
        .prefetch_related('folder_questions')
        .order_by('-created_at')
    )

    folders_data     = []
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
        'folders':                   folders_data,
        'question_ids_in_workspace': list(set(all_question_ids)),
    })