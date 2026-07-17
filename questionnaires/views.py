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
from django.utils import timezone
import json as _json

# Flat list of (value, label) tuples — evaluated once at import time so
# it's always a plain Python list when passed to template contexts.
QUESTION_TYPE_CHOICES = [
    ('multiple_choice', 'Multiple Choice'),
    ('true_false',      'True/False'),
    ('identification',  'Identification'),
    ('essay',           'Essay'),
    ('fill_blank',      'Fill in the Blanks'),
    ('matching',        'Matching Type'),
    ('enumeration',     'Enumeration'),
]


def get_client_ip(request):
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        return x_forwarded_for.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR')


def get_extractor():
    from .extractors import AIQuestionExtractor
    return AIQuestionExtractor()


def is_admin(user):
    return user.is_authenticated and user.is_staff


def is_teacher(user):
    return user.is_authenticated and not user.is_staff and hasattr(user, 'teacher_profile')


# ============================================================================
# HELPERS
# ============================================================================

def _clear_pending_session(request):
    request.session.pop('pending_questionnaire', None)
    request.session.pop('pending_questions', None)
    request.session.pop('pending_questionnaire_pk', None)
    request.session.pop('pending_source', None)
    request.session.modified = True


def _get_teacher_school_year_context(teacher):
    """
    Returns school-year context and assigned-subject data for a teacher,
    sourced from the SchoolYear model rather than calculated from the clock.

    Keys returned:
        current_year          – SchoolYear instance or None
        assigned_subjects     – list of Subject instances for the current year
        assigned_subject_ids  – list of subject PKs for the current year
        current_school_year   – string name for legacy template references
    """
    from accounts.models import SchoolYear, TeacherSubjectAssignment

    current_year         = SchoolYear.get_current()
    assigned_subject_ids = []
    assigned_subjects    = []

    if current_year:
        assignments = (
            TeacherSubjectAssignment.objects
            .filter(teacher=teacher, school_year=current_year)
            .select_related('subject')
            .order_by('subject__code')
        )
        assigned_subject_ids = [a.subject_id for a in assignments]
        assigned_subjects    = [a.subject    for a in assignments]

    return {
        'current_year':         current_year,
        'assigned_subjects':    assigned_subjects,
        'assigned_subject_ids': assigned_subject_ids,
        # Keep for any legacy template references
        'current_school_year':  current_year.name if current_year else '',
    }


def _restrict_subject_queryset(form, assigned_subject_ids):
    """
    Limit the 'subject' dropdown on a QuestionnaireUploadForm to only
    the subjects the teacher is assigned to for the current school year.
    """
    if 'subject' in form.fields:
        form.fields['subject'].queryset = Subject.objects.filter(
            pk__in=assigned_subject_ids,
            is_archived=False,
        ).order_by('code')


def _save_manual_questions(request, questionnaire):
    """
    Reads manual_* POST arrays and creates ExtractedQuestion rows.
    Returns list of created question PKs.
    """
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

    created_ids = []
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
        created_ids.append(new_q.id)

    return created_ids


# ============================================================================
# UPLOAD VIEW
# ============================================================================

@login_required
def upload_questionnaire(request):
    if request.user.is_staff:
        messages.error(request, 'Admins cannot upload questionnaires')
        return redirect('accounts:admin_dashboard')

    teacher = get_object_or_404(TeacherProfile, user=request.user)

    from accounts.models import TeacherSubjectAssignment
    from accounts.school_year_utils import resolve_view_semester
    current_semester, view_semester = resolve_view_semester(request)

    current_year = current_semester.school_year if current_semester else None
    view_year    = view_semester.school_year if view_semester else None

    # Viewing a past semester → read-only, block uploads (template shows the notice)
    is_read_only = bool(view_semester and current_semester and view_semester.pk != current_semester.pk)

    assigned_subject_ids = []
    assigned_subjects    = []
    if current_semester:
        assignments = (
            TeacherSubjectAssignment.objects
            .filter(teacher=teacher, semester=current_semester)
            .select_related('subject')
            .order_by('subject__code')
        )
        assigned_subject_ids = [a.subject_id for a in assignments]
        assigned_subjects    = [a.subject    for a in assignments]

    def _base_context(form):
        return {
            'form':                form,
            'current_year':        current_year,
            'view_year':           view_year,
            'is_read_only':        is_read_only,
            'assigned_subjects':   assigned_subjects,
            'current_school_year': current_year.name if current_year else '',
        }

    if request.method == 'POST':
        if is_read_only:
            messages.error(
                request,
                f"You're viewing a past semester"
                f"{f' ({view_year.name})' if view_year else ''}. "
                f"Switch back to the current semester to upload questionnaires."
            )
            form = QuestionnaireUploadForm(user=request.user)
            _restrict_subject_queryset(form, assigned_subject_ids)
            return render(request, 'teacher_dashboard/upload_questionnaire.html', _base_context(form))

        form = QuestionnaireUploadForm(request.POST, request.FILES, user=request.user)
        _restrict_subject_queryset(form, assigned_subject_ids)

        if form.is_valid():
            questionnaire = form.save(commit=False)
            questionnaire.uploader           = teacher
            questionnaire.department         = teacher.department
            questionnaire.extraction_status  = 'processing'
            # Stamp with the CURRENT year server-side — never trust the client.
            if current_year:
                questionnaire.school_year = current_year.name

            curriculum_id = request.POST.get('curriculum_id', '').strip()
            if curriculum_id:
                from accounts.models import Curriculum
                questionnaire.curriculum = Curriculum.objects.filter(pk=curriculum_id).first()

            questionnaire.save()

            try:
                question_types_qs = form.cleaned_data.get('question_types')
                if question_types_qs:
                    type_names = [qt.name for qt in question_types_qs]
                else:
                    type_names = list(
                        QuestionType.objects.filter(is_active=True)
                                            .values_list('name', flat=True)
                    )

                extractor = get_extractor()
                created_questions = extractor.process_questionnaire(
                    questionnaire,
                    type_names,
                    mode='extract',
                )

                if not created_questions:
                    questionnaire.file.delete(save=False)
                    questionnaire.delete()
                    messages.error(
                        request,
                        'The AI could not extract any questions from this file. '
                        'Please make sure it includes an answer key and try again.',
                    )
                    _restrict_subject_queryset(form, assigned_subject_ids)
                    return render(request, 'teacher_dashboard/upload_questionnaire.html', _base_context(form))

                questionnaire.extraction_status = 'pending_review'
                questionnaire.save()

                request.session['pending_questionnaire_pk'] = questionnaire.pk
                request.session['pending_source']           = 'extract'
                request.session.modified = True

                messages.success(
                    request,
                    f'Extracted {len(created_questions)} question(s)! '
                    f'Review and select the ones you want to keep.',
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
                    description='AI question extraction failed — file was not saved.',
                )

                err = str(e)
                if 'credit balance is too low' in err or ('credit' in err.lower() and 'low' in err.lower()):
                    up_msg = (
                        'The AI service account has run out of credits. '
                        'Please contact the administrator to top up the API credits.'
                    )
                elif any(code in err for code in ('503', '429', 'UNAVAILABLE',
                                                'RESOURCE_EXHAUSTED',
                                                'rate limit', 'overloaded')):
                    up_msg = (
                        'The AI service is temporarily unavailable due to high demand. '
                        'Your file was not saved. Please wait a moment and try again.'
                    )
                else:
                    up_msg = (
                        f'Extraction failed: {err}. '
                        f'Your file was not saved. Please try again.'
                    )
                messages.error(request, up_msg)
                _restrict_subject_queryset(form, assigned_subject_ids)
                return render(request, 'teacher_dashboard/upload_questionnaire.html', _base_context(form))
        else:
            messages.error(request, 'Please correct the errors below.')
    else:
        form = QuestionnaireUploadForm(user=request.user)

    _restrict_subject_queryset(form, assigned_subject_ids)
    return render(request, 'teacher_dashboard/upload_questionnaire.html', _base_context(form))

# ============================================================================
# GENERATE VIEW
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
            questionnaire.uploader           = teacher
            questionnaire.department         = teacher.department
            questionnaire.exam_type          = form.cleaned_data['exam_type']
            questionnaire.extraction_status  = 'processing'
            questionnaire.save()

            try:
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

                questionnaire.extraction_status = 'pending_review'
                questionnaire.save()

                request.session['pending_questionnaire_pk'] = questionnaire.pk
                request.session['pending_source']           = 'generate'
                request.session.modified = True

                messages.success(
                    request,
                    f'AI generated {len(created_questions)} question(s)! '
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

                err = str(e)
                if 'credit balance is too low' in err or 'credit' in err.lower() and 'low' in err.lower():
                    gen_msg = (
                        'The AI service account has run out of credits. '
                        'Please contact the administrator to top up the API credits.'
                    )
                elif any(code in err for code in ('503', '429', 'UNAVAILABLE',
                                                   'RESOURCE_EXHAUSTED',
                                                   'rate limit', 'overloaded')):
                    gen_msg = (
                        'The AI service is temporarily unavailable due to high demand. '
                        'Your file was not saved. Please wait a moment and try again.'
                    )
                else:
                    gen_msg = (
                        f'AI generation failed: {err}. '
                        f'Your file was not saved. Please try again.'
                    )
                messages.error(request, gen_msg)
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
# CANCEL PENDING
# ============================================================================

@login_required
def cancel_pending(request):
    pending_pk = request.session.get('pending_questionnaire_pk')
    if pending_pk:
        try:
            q = Questionnaire.objects.get(
                pk=pending_pk,
                uploader__user=request.user,
                extraction_status='pending_review',
            )
            q.extracted_questions.all().delete()
            q.file.delete(save=False)
            q.delete()
        except Questionnaire.DoesNotExist:
            pass

    _clear_pending_session(request)
    messages.info(request, 'Upload cancelled. No questions were saved.')
    return redirect('questionnaires:upload_questionnaire')


# ============================================================================
# REVIEW VIEW — handles both PK-based (new) and session-dict (legacy) flows
# ============================================================================

@login_required
def review_extracted_questions(request):
    if request.user.is_staff:
        messages.error(request, 'Admins cannot review extracted questions.')
        return redirect('accounts:admin_dashboard')

    pending_pk = request.session.get('pending_questionnaire_pk')

    # ── NEW FLOW: questionnaire already exists in DB ──────────────────────────
    if pending_pk:
        questionnaire = get_object_or_404(
            Questionnaire, pk=pending_pk, uploader__user=request.user
        )
        source              = request.session.get('pending_source', 'extract')
        extracted_questions = questionnaire.extracted_questions\
            .select_related('question_type').all()

        if request.method == 'POST':
            action = request.POST.get('action')

            if action == 'delete_question':
                qid = request.POST.get('question_id')
                try:
                    questionnaire.extracted_questions.filter(pk=qid).delete()
                    return JsonResponse({'ok': True})
                except Exception:
                    return JsonResponse({'error': 'Failed to delete'}, status=400)

            if action == 'save_selected':
                selected_ids = request.POST.getlist('selected_questions')
                manual_uids  = request.POST.getlist('manual_selected_uid[]')

                if not selected_ids and not manual_uids:
                    if source == 'generate':
                        return JsonResponse({
                            'success': False,
                            'error': 'Please select at least one question.',
                        })
                    messages.error(request, 'Please select at least one question.')
                    question_types = QuestionType.objects.filter(
                        id__in=extracted_questions.values_list(
                            'question_type', flat=True
                        ).distinct()
                    ).exclude(name='section_header')
                    return render(request, 'teacher_dashboard/review_extracted.html', {
                        'questionnaire':  questionnaire,
                        'questions':      extracted_questions,
                        'question_types': question_types,
                        'source':         source,
                        'from_my_uploads': False,
                    })

                final_title = request.POST.get('final_title', '').strip()
                if final_title and final_title != questionnaire.title:
                    questionnaire.title = final_title

                extracted_questions.filter(id__in=selected_ids).update(is_approved=True)
                extracted_questions.exclude(id__in=selected_ids).update(is_approved=False)

                manual_created_ids = _save_manual_questions(request, questionnaire)

                questionnaire.extraction_status = 'completed'
                questionnaire.is_extracted      = True
                questionnaire.save()

                _clear_pending_session(request)

                total_saved   = len(selected_ids) + len(manual_created_ids)
                all_saved_ids = list(selected_ids) + [str(i) for i in manual_created_ids]

                ActivityLog.objects.create(
                    activity_type='questionnaire_uploaded',
                    user=request.user,
                    description=(
                        f'You uploaded "{questionnaire.title}" '
                        f'for {questionnaire.subject.code}'
                    ),
                )

                if source == 'generate':
                    folder_id = request.POST.get('workspace_folder_id', '').strip()
                    if not folder_id:
                        return JsonResponse({
                            'success': False,
                            'error': 'No workspace folder selected.',
                        })
                    teacher = get_object_or_404(TeacherProfile, user=request.user)
                    try:
                        folder = WorkspaceFolder.objects.get(pk=folder_id, teacher=teacher)
                    except WorkspaceFolder.DoesNotExist:
                        return JsonResponse({
                            'success': False,
                            'error': 'Workspace folder not found.',
                        })

                    added = already = 0
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

                    return JsonResponse({
                        'success':     True,
                        'added':       added,
                        'folder_name': folder.name,
                        'total_saved': total_saved,
                    })

                download_format = request.POST.get('download_format', 'none')
                if download_format != 'none':
                    from django.urls import reverse
                    download_url = reverse(
                        'questionnaires:download_questionnaire',
                        args=[questionnaire.pk],
                    )
                    return redirect(f"{download_url}?type=generated&format={download_format}")

                messages.success(request, f'Saved {total_saved} question(s) successfully!')
                return redirect('questionnaires:my_uploads')

        # GET
        question_types = QuestionType.objects.filter(
            id__in=extracted_questions.values_list('question_type', flat=True).distinct()
        ).exclude(name='section_header')
        return render(request, 'teacher_dashboard/review_extracted.html', {
            'questionnaire':  questionnaire,
            'questions':      extracted_questions,
            'question_types': question_types,
            'source':         source,
            'from_my_uploads': False,
        })

    # ── LEGACY FLOW: session dict (pending_questionnaire key) ─────────────────
    pending_meta = request.session.get('pending_questionnaire')
    pending_qs   = request.session.get('pending_questions', [])

    if not pending_meta:
        messages.error(request, 'No pending questionnaire found. Please upload again.')
        return redirect('questionnaires:upload_questionnaire')

    source = pending_meta.get('source', 'extract')

    class _FakeQuestionType:
        def __init__(self, name):
            self.name     = name
            self._display = name.replace('_', ' ').title()
        def get_name_display(self):
            return self._display

    class _FakeQuestion:
        def __init__(self, index, data):
            self.id             = index
            self.question_text  = data['question_text']
            self.difficulty     = data['difficulty']
            self.points         = data['points']
            self.correct_answer = data['correct_answer']
            self.explanation    = data.get('explanation', '')
            self.is_approved    = True
            self.question_type  = _FakeQuestionType(data['question_type'])
            self._data          = data
            self.options_list   = [
                ('a', data.get('option_a', '')),
                ('b', data.get('option_b', '')),
                ('c', data.get('option_c', '')),
                ('d', data.get('option_d', '')),
            ]

        def get_matching_data(self):
            if self.question_type.name != 'matching':
                return None
            opt_a = self._data.get('option_a', '')
            opt_b = self._data.get('option_b', '')
            opt_c = self._data.get('option_c', '')
            if not opt_a or not opt_b:
                return None
            try:
                column_a = _json.loads(opt_a)
                column_b = _json.loads(opt_b)
                pairs    = _json.loads(opt_c) if opt_c else []
                if not column_a or not column_b:
                    return None
                return {
                    'column_a':      column_a,
                    'column_b':      column_b,
                    'pairs':         pairs,
                    'pairs_by_item': {
                        p['item']: p['match']
                        for p in pairs
                        if isinstance(p, dict) and 'item' in p and 'match' in p
                    },
                }
            except (ValueError, TypeError, KeyError):
                return None

    class _FakeQuestionnaire:
        def __init__(self, meta):
            self.title       = meta['title']
            self.description = meta.get('description', '')

    if request.method == 'POST':
        action = request.POST.get('action')

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

        if action == 'save_selected':
            selected_indices = request.POST.getlist('selected_questions')
            manual_uids      = request.POST.getlist('manual_selected_uid[]')

            if not selected_indices and not manual_uids:
                if source == 'generate':
                    return JsonResponse({
                        'success': False,
                        'error': 'Please select at least one question.',
                    })
                messages.error(request, 'Please select at least one question.')
                fake_questions = [_FakeQuestion(i, q) for i, q in enumerate(pending_qs)]
                used_types     = {q['question_type'] for q in pending_qs}
                fake_types     = [_FakeQuestionType(t) for t in used_types]
                return render(request, 'teacher_dashboard/review_extracted.html', {
                    'questionnaire':  _FakeQuestionnaire(pending_meta),
                    'questions':      fake_questions,
                    'question_types': fake_types,
                    'source':         source,
                    'from_my_uploads': False,
                })

            teacher     = get_object_or_404(TeacherProfile, user=request.user)
            subject     = get_object_or_404(Subject, pk=pending_meta['subject_id'])
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
                file_size         = 0,
                file_type         = 'txt',
            )
            questionnaire.file = None
            questionnaire.save()

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

            manual_created_ids = _save_manual_questions(request, questionnaire)
            all_saved_ids      = newly_created_ids + manual_created_ids
            total_saved        = len(all_saved_ids)

            ActivityLog.objects.create(
                activity_type='questionnaire_uploaded',
                user=request.user,
                description=(
                    f'You uploaded "{questionnaire.title}" '
                    f'for {questionnaire.subject.code}'
                ),
            )

            _clear_pending_session(request)

            if source == 'generate':
                folder_id = request.POST.get('workspace_folder_id', '').strip()
                if not folder_id:
                    return JsonResponse({
                        'success': False,
                        'error': 'No workspace folder selected.',
                    })
                try:
                    folder = WorkspaceFolder.objects.get(pk=folder_id, teacher=teacher)
                except WorkspaceFolder.DoesNotExist:
                    return JsonResponse({
                        'success': False,
                        'error': 'Workspace folder not found.',
                    })
                added = already = 0
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
                return JsonResponse({
                    'success':     True,
                    'added':       added,
                    'folder_name': folder.name,
                    'total_saved': total_saved,
                })

            download_format = request.POST.get('download_format', 'none')
            if download_format != 'none':
                from django.urls import reverse
                download_url = reverse(
                    'questionnaires:download_questionnaire',
                    args=[questionnaire.pk],
                )
                return redirect(f"{download_url}?type=generated&format={download_format}")

            messages.success(request, f'Saved {total_saved} question(s) successfully!')
            return redirect('questionnaires:my_uploads')

    fake_questions = [_FakeQuestion(i, q) for i, q in enumerate(pending_qs)]
    used_types     = {q['question_type'] for q in pending_qs}
    fake_types     = [_FakeQuestionType(t) for t in used_types]

    return render(request, 'teacher_dashboard/review_extracted.html', {
        'questionnaire':  _FakeQuestionnaire(pending_meta),
        'questions':      fake_questions,
        'question_types': fake_types,
        'total_points':   sum(q['points'] for q in pending_qs),
        'source':         source,
    })


# ============================================================================
# RETRY EXTRACTION
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
            type_names     = [qt.name for qt in question_types]

            extractor         = get_extractor()
            created_questions = extractor.process_questionnaire(questionnaire, type_names)

            questionnaire.extraction_status = 'completed'
            questionnaire.is_extracted      = True
            questionnaire.extraction_error  = None
            questionnaire.save()

            ActivityLog.objects.create(
                activity_type='questions_extracted',
                user=request.user,
                description=(
                    f'Re-extracted {len(created_questions)} questions '
                    f'from "{questionnaire.title}"'
                ),
            )

            messages.success(request, f'Successfully extracted {len(created_questions)} questions!')
            return redirect('questionnaires:review_extracted_pk', pk=questionnaire.pk)

        except Exception as e:
            questionnaire.extraction_status = 'failed'
            questionnaire.extraction_error  = str(e)
            questionnaire.save()

            messages.error(request, f'Extraction failed: {str(e)}')
            return redirect('questionnaires:retry_extraction', pk=pk)

    question_types = QuestionType.objects.filter(is_active=True)
    return render(request, 'teacher_dashboard/retry_extraction.html', {
        'questionnaire': questionnaire,
        'question_types': question_types,
    })


# ============================================================================
# REVIEW BY PK  —  DB-backed (retry extraction only)
# ============================================================================

@login_required
def review_extracted_questions_pk(request, pk):
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

    from accounts.models import Semester
    current_semester = Semester.get_current()
    quest_sem_label = questionnaire.semester  # '1st' / '2nd'
    is_read_only = bool(
        current_semester and quest_sem_label and
        quest_sem_label != ('1st' if current_semester.number == 1 else '2nd')
        or (current_semester and questionnaire.school_year != current_semester.school_year.name)
    )

    extracted_questions = questionnaire.extracted_questions.select_related('question_type').all()
    source = request.GET.get('source', request.POST.get('source', 'extract'))

    if request.method == 'POST':
        if is_read_only:
            messages.error(request, 'This questionnaire belongs to a past semester and cannot be edited.')
            return redirect('questionnaires:my_uploads')

        action = request.POST.get('action')
        source = request.POST.get('source', 'extract')
        # ... rest unchanged ...

    question_types = QuestionType.objects.filter(
        id__in=extracted_questions.values_list('question_type', flat=True).distinct()
    ).exclude(name='section_header')
    return render(request, 'teacher_dashboard/review_extracted.html', {
        'questionnaire':  questionnaire,
        'questions':      extracted_questions,
        'question_types': question_types,
        'total_points':   sum(q.points for q in extracted_questions),
        'source':         source,
        'from_my_uploads': True,
        'is_read_only':   is_read_only,
    })

# ============================================================================
# MY UPLOADS
# ============================================================================

@login_required
def my_uploads(request):
    if request.user.is_staff:
        return redirect('accounts:admin_dashboard')

    teacher = get_object_or_404(TeacherProfile, user=request.user)

    from accounts.school_year_utils import resolve_view_semester
    from accounts.models import Semester
    current_semester, view_semester = resolve_view_semester(request)

    current_year_obj = current_semester.school_year if current_semester else None
    view_year_obj     = view_semester.school_year if view_semester else None
    is_read_only      = bool(view_semester and current_semester and view_semester.pk != current_semester.pk)

    questionnaires = (
        Questionnaire.objects
        .filter(uploader=teacher, is_archived=False)
        .select_related('department', 'subject')
    )

    search_query = request.GET.get('search', '')

    if view_semester:
        sem_label = '1st' if view_semester.number == 1 else '2nd'
        questionnaires = questionnaires.filter(
            school_year=view_semester.school_year.name,
            semester=sem_label,
        )
    if search_query:
        questionnaires = questionnaires.filter(
            Q(title__icontains=search_query) |
            Q(description__icontains=search_query) |
            Q(subject__name__icontains=search_query)
        )

    archived_questionnaires = (
        Questionnaire.objects
        .filter(uploader=teacher, is_archived=True)
        .select_related('department', 'subject')
        .order_by('-uploaded_at')
    )

    paginator   = Paginator(questionnaires, 10)
    page_number = request.GET.get('page')
    page_obj    = paginator.get_page(page_number)

    all_semesters = Semester.objects.select_related('school_year').order_by('-school_year__name', '-number')

    return render(request, 'teacher_dashboard/my_uploads.html', {
        'page_obj':                page_obj,
        'search_query':            search_query,
        'archived_questionnaires': archived_questionnaires,
        'current_semester':        current_semester,
        'view_semester':           view_semester,
        'all_semesters':           all_semesters,
        'is_read_only':            is_read_only,
        'current_year_name':       current_year_obj.name if current_year_obj else '',
        'selected_school_year':    view_year_obj.name if view_year_obj else '',
    })

# ============================================================================
# EDIT / DELETE
# ============================================================================

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
                description=f'Updated questionnaire "{questionnaire.title}"',
            )
            messages.success(request, 'Questionnaire updated successfully')
            if request.user.is_staff:
                return redirect('questionnaires:all_questionnaires')
            return redirect('questionnaires:my_uploads')
        else:
            messages.error(request, 'Please correct the errors below.')
    return redirect('questionnaires:my_uploads')


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
            description=f'Deleted questionnaire "{questionnaire_title}"',
        )
        questionnaire.file.delete()
        questionnaire.delete()
        messages.success(request, 'Questionnaire deleted successfully')
        if request.user.is_staff:
            return redirect('questionnaires:all_questionnaires')
        return redirect('questionnaires:my_uploads')

    return redirect('questionnaires:my_uploads')


@login_required
def archive_questionnaire(request, pk):
    questionnaire = get_object_or_404(Questionnaire, pk=pk, is_archived=False)

    if request.user.is_staff:
        can_act = True
    elif hasattr(request.user, 'subadmin_profile') and request.user.subadmin_profile.is_active:
        can_act = questionnaire.department_id == request.user.subadmin_profile.department_id
    elif hasattr(request.user, 'teacher_profile'):
        can_act = questionnaire.uploader == request.user.teacher_profile
    else:
        can_act = False

    if not can_act:
        return JsonResponse({'error': 'Permission denied'}, status=403)

    if request.method == 'POST':
        questionnaire.is_archived = True
        questionnaire.save()
        ActivityLog.objects.create(
            activity_type='questionnaire_archived',
            user=request.user,
            description=f'Archived questionnaire "{questionnaire.title}"',
        )
        return JsonResponse({'success': True, 'message': f'"{questionnaire.title}" archived successfully.'})

    return JsonResponse({'error': 'Invalid request'}, status=400)


@login_required
def unarchive_questionnaire(request, pk):
    questionnaire = get_object_or_404(Questionnaire, pk=pk, is_archived=True)

    if request.user.is_staff:
        can_act = True
    elif hasattr(request.user, 'subadmin_profile') and request.user.subadmin_profile.is_active:
        can_act = questionnaire.department_id == request.user.subadmin_profile.department_id
    elif hasattr(request.user, 'teacher_profile'):
        can_act = questionnaire.uploader == request.user.teacher_profile
    else:
        can_act = False

    if not can_act:
        return JsonResponse({'error': 'Permission denied'}, status=403)

    if request.method == 'POST':
        questionnaire.is_archived = False
        questionnaire.save()
        ActivityLog.objects.create(
            activity_type='questionnaire_restored',
            user=request.user,
            description=f'Restored questionnaire "{questionnaire.title}"',
        )
        return JsonResponse({'success': True, 'message': f'"{questionnaire.title}" restored successfully.'})

    return JsonResponse({'error': 'Invalid request'}, status=400)


@login_required
def permanent_delete_questionnaire(request, pk):
    questionnaire = get_object_or_404(Questionnaire, pk=pk, is_archived=True)
    if request.user.is_staff:
        can_act = True
    elif hasattr(request.user, 'teacher_profile'):
        can_act = questionnaire.uploader == request.user.teacher_profile
    else:
        can_act = False
    if not can_act:
        return JsonResponse({'error': 'Permission denied'}, status=403)
    if request.method == 'POST':
        title = questionnaire.title
        from accounts.models import ActivityLog
        ActivityLog.objects.create(
            activity_type='questionnaire_deleted',
            user=request.user,
            description=f'Permanently deleted questionnaire "{title}"',
        )
        questionnaire.file.delete()
        questionnaire.delete()
        return JsonResponse({'success': True, 'message': f'"{title}" permanently deleted.'})
    return JsonResponse({'error': 'Invalid request'}, status=400)


# ============================================================================
# BROWSE  (teachers see each other's questionnaires)
# ============================================================================

@login_required
def browse_questionnaires(request):
    if request.user.is_staff:
        return redirect('questionnaires:all_questionnaires')

    teacher = get_object_or_404(TeacherProfile, user=request.user)

    assigned_subjects = teacher.subjects.all()
    if assigned_subjects.exists():
        questionnaires = Questionnaire.objects.select_related(
            'department', 'subject', 'uploader__user', 'curriculum'
        ).filter(
            subject__in=assigned_subjects,
            is_extracted=True,
            extraction_status='completed',
            is_archived=False,
        )
    else:
        questionnaires = Questionnaire.objects.select_related(
            'department', 'subject', 'uploader__user', 'curriculum'
        ).filter(
            subject__departments=teacher.department,
            is_extracted=True,
            extraction_status='completed',
            is_archived=False,
        )

    from accounts.school_year_utils import resolve_view_semester
    current_semester, view_semester = resolve_view_semester(request)
    current_year = current_semester.school_year if current_semester else None
    view_year    = view_semester.school_year if view_semester else None

    subject_id              = request.GET.get('subject', '')
    exam_type                = request.GET.get('exam_type', '')
    search_query             = request.GET.get('search', '')
    selected_semester        = request.GET.get('semester', '')
    selected_question_type   = request.GET.get('question_type', '')
    selected_year_level      = request.GET.get('year_level', '')
    selected_curriculum_id   = request.GET.get('curriculum', '')

    if selected_year_level:
        questionnaires = questionnaires.filter(year_level=selected_year_level)
    if subject_id:
        questionnaires = questionnaires.filter(subject_id=subject_id)
    if exam_type:
        questionnaires = questionnaires.filter(exam_type=exam_type)
    if selected_semester:
        questionnaires = questionnaires.filter(semester=selected_semester)
    if view_semester:
        questionnaires = questionnaires.filter(
            school_year=view_semester.school_year.name,
            semester='1st' if view_semester.number == 1 else '2nd',
        )
    if selected_question_type:
        questionnaires = questionnaires.filter(
            extracted_questions__question_type__name=selected_question_type
        ).distinct()
    if selected_curriculum_id:
        questionnaires = questionnaires.filter(curriculum_id=selected_curriculum_id)
    if search_query:
        questionnaires = questionnaires.filter(
            Q(title__icontains=search_query)         |
            Q(description__icontains=search_query)   |
            Q(subject__name__icontains=search_query)  |
            Q(subject__code__icontains=search_query)
        )

    from accounts.models import Curriculum, ProgramCurriculum
    if assigned_subjects.exists():
        program_ids = ProgramCurriculum.objects.filter(
            subject__in=assigned_subjects
        ).values_list('program_id', flat=True).distinct()
    else:
        program_ids = ProgramCurriculum.objects.filter(
            subject__departments=teacher.department
        ).values_list('program_id', flat=True).distinct()

    curriculum_options = (
        Curriculum.objects
        .filter(program_id__in=program_ids)
        .order_by('-created_at')
        .values('id', 'code', 'school_year', 'is_active', 'is_draft')
    )

    subjects = assigned_subjects.order_by('code') if assigned_subjects.exists() \
        else Subject.objects.filter(departments=teacher.department)

    paginator   = Paginator(questionnaires, 12)
    page_number = request.GET.get('page')
    page_obj    = paginator.get_page(page_number)

    ctx = {
        'page_obj':               page_obj,
        'subjects':               subjects,
        'selected_subject':       subject_id,
        'search_query':           search_query,
        'exam_type':              exam_type,
        'exam_type_choices':      Questionnaire.EXAM_TYPE_CHOICES,
        'semester_choices':       Questionnaire.SEMESTER_CHOICES,
        'selected_semester':      selected_semester,
        'question_type_choices':  QUESTION_TYPE_CHOICES,
        'selected_question_type': selected_question_type,
        'selected_year_level':    selected_year_level,
        'curriculum_options':     list(curriculum_options),
        'selected_curriculum_id': selected_curriculum_id,
        'current_semester':       current_semester,
        'view_semester':          view_semester,
        'current_year':           current_year,
        'view_year':              view_year,
        'current_year_name':      current_year.name if current_year else '',
        'selected_school_year':   view_year.name if view_year else '',
    }
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return render(request, 'teacher_dashboard/browse_questionnaires_partial.html', ctx)
    return render(request, 'teacher_dashboard/browse_questionnaires.html', ctx)


# ============================================================================
# ALL QUESTIONNAIRES (admin)
# ============================================================================

@login_required
def all_questionnaires(request):
    if not request.user.is_staff:
        return redirect('questionnaires:browse_questionnaires')

    questionnaires = Questionnaire.objects.select_related(
        'department', 'subject', 'uploader__user'
    ).filter(is_extracted=True, extraction_status='completed', is_archived=False)

    archived_questionnaires = Questionnaire.objects.select_related(
        'department', 'subject', 'uploader__user'
    ).filter(is_archived=True)

    selected_department    = request.GET.get('department', '')
    selected_subject       = request.GET.get('subject', '')
    exam_type              = request.GET.get('exam_type', '')
    search_query           = request.GET.get('search', '')
    selected_semester      = request.GET.get('semester', '')
    selected_school_year   = request.GET.get('school_year', '')
    selected_question_type = request.GET.get('question_type', '')

    if selected_department:
        questionnaires = questionnaires.filter(department_id=selected_department)
    if selected_subject:
        questionnaires = questionnaires.filter(subject_id=selected_subject)
    if exam_type:
        questionnaires = questionnaires.filter(exam_type=exam_type)
    if selected_semester:
        questionnaires = questionnaires.filter(semester=selected_semester)
    if selected_school_year:
        questionnaires = questionnaires.filter(school_year=selected_school_year)
    if selected_question_type:
        questionnaires = questionnaires.filter(
            extracted_questions__question_type__name=selected_question_type
        ).distinct()
    if search_query:
        questionnaires = questionnaires.filter(
            Q(title__icontains=search_query)         |
            Q(description__icontains=search_query)   |
            Q(subject__name__icontains=search_query) |
            Q(subject__code__icontains=search_query)
        )

    departments = Department.objects.all()
    subjects    = Subject.objects.all()
    school_year_options = list(
        Questionnaire.objects.filter(
            is_extracted=True, extraction_status='completed',
            is_archived=False, school_year__gt=''
        ).values_list('school_year', flat=True).distinct().order_by('-school_year')
    )
    paginator   = Paginator(questionnaires, 12)
    page_number = request.GET.get('page')
    page_obj    = paginator.get_page(page_number)

    ctx = {
        'page_obj':               page_obj,
        'departments':            departments,
        'subjects':               subjects,
        'selected_department':    selected_department,
        'selected_subject':       selected_subject,
        'search_query':           search_query,
        'exam_type':              exam_type,
        'exam_type_choices':      Questionnaire.EXAM_TYPE_CHOICES,
        'semester_choices':       Questionnaire.SEMESTER_CHOICES,
        'selected_semester':      selected_semester,
        'selected_school_year':   selected_school_year,
        'school_year_options':    school_year_options,
        'archived_questionnaires': archived_questionnaires,
        'question_type_choices':  QUESTION_TYPE_CHOICES,
        'selected_question_type': selected_question_type,
    }
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return render(request, 'admin_dashboard/all_questionnaires_partial.html', ctx)
    return render(request, 'admin_dashboard/all_questionnaires.html', ctx)


# ============================================================================
# DOWNLOAD
# ============================================================================

@login_required
def download_questionnaire(request, pk):
    from .models import Download
    from .generators import generate_bisu_questionnaire
 
    questionnaire = get_object_or_404(Questionnaire, pk=pk)
 
    Download.objects.create(
        questionnaire=questionnaire,
        user=request.user if request.user.is_authenticated else None,
        ip_address=get_client_ip(request),
    )
 
    if hasattr(request.user, 'teacher_profile'):
        if questionnaire.uploader != request.user.teacher_profile:
            ActivityLog.objects.create(
                activity_type='questionnaire_downloaded',
                user=questionnaire.uploader.user,
                description=(
                    f'{request.user.get_full_name()} downloaded '
                    f'your "{questionnaire.title}"'
                ),
            )
 
    download_type = request.GET.get('type', 'original')
 
    if download_type == 'original':
        # questionnaire.file uses Django's storage API (FileField.open()),
        # so once DEFAULT_FILE_STORAGE points at S3/R2 this works correctly
        # without ever touching local disk.
        try:
            return FileResponse(
                questionnaire.file.open('rb'),
                as_attachment=True,
                filename=questionnaire.file.name.split('/')[-1],
            )
        except (FileNotFoundError, ValueError):
            raise Http404("Original file not found")
 
    elif download_type == 'generated':
        question_ids_param = request.GET.get('questions', '')
 
        if question_ids_param:
            try:
                question_ids = [
                    int(i) for i in question_ids_param.split(',')
                    if i.strip().isdigit()
                ]
                selected_questions = questionnaire.extracted_questions.filter(
                    id__in=question_ids
                ).select_related('question_type').order_by('created_at')
            except (ValueError, TypeError):
                selected_questions = questionnaire.extracted_questions.filter(
                    is_approved=True
                ).select_related('question_type').order_by('created_at')
        else:
            selected_questions = questionnaire.extracted_questions.filter(
                is_approved=True
            ).select_related('question_type').order_by('created_at')
 
        if not selected_questions.exists():
            messages.warning(request, 'No questions available to generate the document.')
            return redirect('questionnaires:my_uploads')
 
        try:
            # generate_bisu_questionnaire now returns an in-memory buffer —
            # nothing is written to local disk, so this works on Vercel.
            buffer, filename = generate_bisu_questionnaire(questionnaire, selected_questions)
 
            response = FileResponse(
                buffer,
                as_attachment=True,
                filename=filename,
                content_type=(
                    'application/vnd.openxmlformats-officedocument'
                    '.wordprocessingml.document'
                ),
            )
            return response
 
        except Exception as e:
            messages.error(request, f'Failed to generate questionnaire: {str(e)}')
            return redirect('questionnaires:my_uploads')
 
    else:
        raise Http404("Invalid download type")


# ============================================================================
# AJAX HELPERS
# ============================================================================

@login_required
def get_subjects_ajax(request):
    department_id = request.GET.get('department')
    if not department_id:
        return JsonResponse({'subjects': []})

    if not request.user.is_staff:
        try:
            from accounts.models import TeacherProfile, SubAdminProfile
            user_dept_id = None
            if hasattr(request.user, 'teacher'):
                user_dept_id = request.user.teacher.department_id
            elif hasattr(request.user, 'subadmin_profile'):
                user_dept_id = request.user.subadmin_profile.department_id
            if user_dept_id and str(user_dept_id) != str(department_id):
                return JsonResponse({'subjects': [], 'error': 'Not authorized'}, status=403)
        except Exception:
            pass

    subjects = Subject.objects.filter(
        departments__id=department_id
    ).values('id', 'code', 'name')
    return JsonResponse({'subjects': list(subjects)})


@login_required
def get_questions_json(request, pk):
    questionnaire = get_object_or_404(Questionnaire, pk=pk)

    is_owner = (
        hasattr(questionnaire, 'uploader') and
        questionnaire.uploader is not None and
        questionnaire.uploader.user_id == request.user.pk
    )
    can_access = False
    try:
        if hasattr(request.user, 'teacher_profile'):
            teacher = request.user.teacher_profile
            can_access = (
                teacher.department_id == questionnaire.department_id or
                teacher.subjects.filter(id=questionnaire.subject_id).exists() or
                questionnaire.subject.departments.filter(id=teacher.department_id).exists()
            )
        elif hasattr(request.user, 'subadmin_profile'):
            can_access = (request.user.subadmin_profile.department_id == questionnaire.department_id)
    except Exception:
        pass
    if not request.user.is_staff and not is_owner and not can_access:
        return JsonResponse({'error': 'You do not have permission to view these questions.'}, status=403)

    questions_data = []

    for q in questionnaire.extracted_questions.select_related('question_type').order_by('created_at'):
        q_type = q.question_type.name

        base = {
            'id':             q.id,
            'question_text':  q.question_text,
            'type':           q_type,
            'type_display':   q.question_type.get_name_display(),
            'difficulty':     q.difficulty,
            'points':         q.points,
            'correct_answer': q.correct_answer or '',
            'explanation':    q.explanation or '',
        }

        if q_type == 'matching':
            try:
                col_a = _json.loads(q.option_a) if q.option_a else []
                col_b = _json.loads(q.option_b) if q.option_b else []
                pairs = _json.loads(q.option_c) if q.option_c else []
            except (ValueError, TypeError):
                col_a, col_b, pairs = [], [], []
            base['column_a']       = col_a
            base['column_b']       = col_b
            base['matching_pairs'] = pairs
            base['options']        = None

        elif q_type == 'multiple_choice':
            base['options'] = [
                q.option_a or '', q.option_b or '',
                q.option_c or '', q.option_d or '',
            ]
            base['column_a']       = None
            base['column_b']       = None
            base['matching_pairs'] = None

        else:
            base['options']        = None
            base['column_a']       = None
            base['column_b']       = None
            base['matching_pairs'] = None

        questions_data.append(base)

    return JsonResponse({
        'questionnaire_id':      questionnaire.pk,
        'questionnaire_title':   questionnaire.title,
        'questionnaire_subject': f"{questionnaire.subject.code} \u2014 {questionnaire.subject.name}",
        'exam_type_display':     questionnaire.get_exam_type_display(),
        'department':            questionnaire.department.name,
        'total':                 len(questions_data),
        'questions':             questions_data,
    })


# ============================================================================
# WORKSPACE VIEWS
# ============================================================================

def _build_folder_questions_data(folder):
    """Return the list of question dicts for a WorkspaceFolder."""
    questions_data = []
    for fq in folder.folder_questions.select_related(
        'question__question_type',
        'question__questionnaire__subject',
    ).all():
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
    return questions_data


@login_required
def workspace(request):
    if request.user.is_staff:
        messages.info(request, 'The workspace feature is for teachers only.')
        return redirect('accounts:admin_dashboard')

    teacher = get_object_or_404(TeacherProfile, user=request.user)

    active_folders = (
        WorkspaceFolder.objects
        .filter(teacher=teacher, is_archived=False)
        .select_related('subject')
        .order_by('-created_at')
    )
    folders_data = [
        {
            'id':           f.pk,
            'name':         f.name,
            'created_at':   f.created_at.isoformat(),
            'subject_id':   f.subject_id,
            'subject_code': f.subject.code if f.subject else None,
            'subject_name': f.subject.name if f.subject else None,
            'questions':    _build_folder_questions_data(f),
        }
        for f in active_folders
    ]

    archived_folders = (
        WorkspaceFolder.objects
        .filter(teacher=teacher, is_archived=True)
        .select_related('subject')
        .order_by('-created_at')
    )
    archived_folders_data = [
        {
            'id':           f.pk,
            'name':         f.name,
            'created_at':   f.created_at.isoformat(),
            'subject_id':   f.subject_id,
            'subject_code': f.subject.code if f.subject else None,
            'subject_name': f.subject.name if f.subject else None,
            'questions':    _build_folder_questions_data(f),
        }
        for f in archived_folders
    ]

    assigned_subjects = list(
        teacher.subjects.values('id', 'code', 'name').order_by('code')
    )
    if not assigned_subjects:
        from accounts.models import Subject as SubjectModel
        assigned_subjects = list(
            SubjectModel.objects.filter(departments=teacher.department)
            .values('id', 'code', 'name').order_by('code')
        )

    import json
    return render(request, 'teacher_dashboard/workspace.html', {
        'folders_json':          json.dumps(folders_data),
        'archived_folders_json': json.dumps(archived_folders_data),
        'subjects_json':         json.dumps(assigned_subjects),
    })


@login_required
@require_POST
def workspace_create_folder(request):
    if request.user.is_staff:
        return JsonResponse({'error': 'Not allowed'}, status=403)

    from django.core.cache import cache
    teacher = get_object_or_404(TeacherProfile, user=request.user)

    try:
        body = _json.loads(request.body)
    except ValueError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)

    name = (body.get('name') or '').strip()[:80]
    if not name:
        return JsonResponse({'error': 'Folder name is required.'}, status=400)

    subject_id = body.get('subject_id')
    subject    = None
    if subject_id:
        from accounts.models import Subject as SubjectModel
        try:
            subject = SubjectModel.objects.get(pk=subject_id)
        except SubjectModel.DoesNotExist:
            return JsonResponse({'error': 'Invalid subject selected.'}, status=400)

    folder = WorkspaceFolder.objects.create(teacher=teacher, name=name, subject=subject)
    cache.delete(f'workspace_folders_{teacher.id}')
    return JsonResponse({
        'id':           folder.pk,
        'name':         folder.name,
        'subject_id':   folder.subject_id,
        'subject_code': folder.subject.code if folder.subject else None,
        'subject_name': folder.subject.name if folder.subject else None,
    })


@login_required
@require_POST
def workspace_rename_folder(request, folder_id):
    from django.core.cache import cache
    teacher = get_object_or_404(TeacherProfile, user=request.user)
    folder  = get_object_or_404(WorkspaceFolder, pk=folder_id, teacher=teacher)

    try:
        body = _json.loads(request.body)
    except ValueError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)

    name = (body.get('name') or '').strip()[:80]
    if not name:
        return JsonResponse({'error': 'Folder name is required.'}, status=400)

    folder.name = name
    folder.save()
    cache.delete(f'workspace_folders_{teacher.id}')
    return JsonResponse({'id': folder.pk, 'name': folder.name})


@login_required
@require_POST
def workspace_delete_folder(request, folder_id):
    from django.core.cache import cache
    teacher = get_object_or_404(TeacherProfile, user=request.user)
    folder  = get_object_or_404(WorkspaceFolder, pk=folder_id, teacher=teacher)
    name    = folder.name
    folder.delete()
    cache.delete(f'workspace_folders_{teacher.id}')
    return JsonResponse({'deleted': True, 'name': name})


@login_required
@require_POST
def workspace_archive_folder(request, folder_id):
    from django.core.cache import cache
    teacher = get_object_or_404(TeacherProfile, user=request.user)
    folder  = get_object_or_404(WorkspaceFolder, pk=folder_id, teacher=teacher, is_archived=False)
    folder.is_archived = True
    folder.save()
    cache.delete(f'workspace_folders_{teacher.id}')
    return JsonResponse({'archived': True, 'name': folder.name})


@login_required
@require_POST
def workspace_unarchive_folder(request, folder_id):
    from django.core.cache import cache
    teacher = get_object_or_404(TeacherProfile, user=request.user)
    folder  = get_object_or_404(WorkspaceFolder, pk=folder_id, teacher=teacher, is_archived=True)
    folder.is_archived = False
    folder.save()
    cache.delete(f'workspace_folders_{teacher.id}')
    return JsonResponse({
        'unarchived':   True,
        'id':           folder.pk,
        'name':         folder.name,
        'created_at':   folder.created_at.isoformat(),
        'subject_id':   folder.subject_id,
        'subject_code': folder.subject.code if folder.subject else None,
        'subject_name': folder.subject.name if folder.subject else None,
        'questions':    _build_folder_questions_data(folder),
    })


@login_required
@require_POST
def workspace_permanent_delete_folder(request, folder_id):
    from django.core.cache import cache
    teacher = get_object_or_404(TeacherProfile, user=request.user)
    folder  = get_object_or_404(WorkspaceFolder, pk=folder_id, teacher=teacher, is_archived=True)
    name    = folder.name
    folder.delete()
    cache.delete(f'workspace_folders_{teacher.id}')
    return JsonResponse({'deleted': True, 'name': name})


@login_required
@require_POST
def workspace_add_questions(request, folder_id):
    if request.user.is_staff:
        return JsonResponse({'error': 'Not allowed'}, status=403)

    from django.core.cache import cache
    teacher = get_object_or_404(TeacherProfile, user=request.user)
    folder  = get_object_or_404(WorkspaceFolder, pk=folder_id, teacher=teacher)

    try:
        body = _json.loads(request.body)
    except ValueError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)

    question_ids = body.get('question_ids', [])
    if not isinstance(question_ids, list):
        return JsonResponse({'error': 'question_ids must be a list'}, status=400)

    allowed_questions = ExtractedQuestion.objects.filter(
        pk__in=question_ids
    ).select_related('questionnaire__subject')

    if folder.subject_id:
        wrong = [
            q for q in allowed_questions
            if q.questionnaire.subject_id != folder.subject_id
        ]
        if wrong:
            folder_subject = folder.subject.code if folder.subject else 'this subject'
            return JsonResponse({
                'error': (
                    f'This folder is locked to {folder_subject}. '
                    f'You can only add questions from {folder_subject} questionnaires.'
                ),
                'subject_mismatch':       True,
                'folder_subject_code':    folder.subject.code if folder.subject else '',
                'folder_subject_name':    folder.subject.name if folder.subject else '',
            }, status=400)

    added = already = 0
    for q in allowed_questions:
        _, created = WorkspaceFolderQuestion.objects.get_or_create(folder=folder, question=q)
        if created:
            added += 1
        else:
            already += 1

    cache.delete(f'workspace_folders_{teacher.id}')
    return JsonResponse({'added': added, 'already_existed': already})


@login_required
@require_POST
def workspace_remove_question(request, folder_id, question_id):
    from django.core.cache import cache
    teacher = get_object_or_404(TeacherProfile, user=request.user)
    folder  = get_object_or_404(WorkspaceFolder, pk=folder_id, teacher=teacher)
    WorkspaceFolderQuestion.objects.filter(
        folder=folder, question_id=question_id
    ).delete()
    cache.delete(f'workspace_folders_{teacher.id}')
    return JsonResponse({'removed': True})


@login_required
def download_workspace(request):
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
 
    owned_ids = set(
        WorkspaceFolderQuestion.objects.filter(
            folder__teacher=teacher,
            question_id__in=question_ids,
        ).values_list('question_id', flat=True)
    )
 
    if not owned_ids:
        messages.error(request, 'None of the selected questions belong to your workspace.')
        return redirect('questionnaires:workspace')
 
    selected_questions = ExtractedQuestion.objects.filter(
        pk__in=owned_ids,
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
            self.department = base_questionnaire.department
            self.subject    = base_questionnaire.subject
            self.uploader   = base_questionnaire.uploader
            # No extracted_questions relation on the proxy — generator
            # checks hasattr() before using it, so this is safe.
 
    proxy = WorkspaceQuestionnaireProxy(first_quest, selected_questions)
 
    try:
        buffer, _ = generate_bisu_questionnaire(proxy, selected_questions)
        filename = 'BISU_Workspace_Questionnaire.docx'
 
        ActivityLog.objects.create(
            activity_type='questionnaire_downloaded',
            user=request.user,
            description=(
                f'Downloaded workspace selection: '
                f'{selected_questions.count()} question(s) from '
                f'{selected_questions.values("questionnaire__subject__code").distinct().count()} subject(s)'
            ),
        )
 
        response = FileResponse(
            buffer,
            content_type=(
                'application/vnd.openxmlformats-officedocument'
                '.wordprocessingml.document'
            ),
        )
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        return response
 
    except Exception as e:
        messages.error(request, f'Failed to generate workspace document: {str(e)}')
        return redirect('questionnaires:workspace')


@login_required
def workspace_list_folders(request):
    if request.user.is_staff:
        return JsonResponse({'folders': [], 'question_ids_in_workspace': []})

    from django.core.cache import cache

    teacher   = get_object_or_404(TeacherProfile, user=request.user)
    cache_key = f'workspace_folders_{teacher.id}'
    cached    = cache.get(cache_key)

    if cached:
        return JsonResponse(cached)

    folders = (
        WorkspaceFolder.objects
        .filter(teacher=teacher)
        .select_related('subject')
        .prefetch_related(
            'folder_questions',
            'folder_questions__question',
            'folder_questions__question__question_type',
        )
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
            'subject_id':     folder.subject_id,
            'subject_code':   folder.subject.code if folder.subject else None,
            'subject_name':   folder.subject.name if folder.subject else None,
        })

    data = {
        'folders':                   folders_data,
        'question_ids_in_workspace': list(set(all_question_ids)),
    }

    cache.set(cache_key, data, timeout=60)
    return JsonResponse(data)


@login_required
def get_subject_curriculum_info(request):
    """
    Return semester, year_level, and ONLY the curriculum versions
    that actually contain this subject.
    """
    subject_id = request.GET.get('subject_id')
    if not subject_id:
        return JsonResponse({'found': False})

    from accounts.models import ProgramCurriculum, Curriculum

    entries = (
        ProgramCurriculum.objects
        .filter(subject_id=subject_id)
        .select_related('curriculum')
        .order_by('-curriculum__created_at')
    )

    if not entries.exists():
        return JsonResponse({'found': False})

    latest_entry = entries.first()

    curricula_list = []
    for entry in entries:
        cur = entry.curriculum
        if cur is None:
            continue
        label = cur.code + ' (' + cur.school_year + ')'
        if cur.is_active:
            label += ' — Latest'
        elif cur.is_draft:
            label += ' — Draft'
        else:
            label += ' — Archived'
        curricula_list.append({
            'id':        cur.id,
            'label':     label,
            'is_active': cur.is_active,
            'is_draft':  cur.is_draft,
        })

    seen = set()
    unique_curricula = []
    for cur in curricula_list:
        if cur['id'] not in seen:
            seen.add(cur['id'])
            unique_curricula.append(cur)

    sem_map = {1: '1st', 2: '2nd'}
    return JsonResponse({
        'found':      True,
        'semester':   sem_map.get(latest_entry.semester, ''),
        'year_level': latest_entry.year_level,
        'curricula':  unique_curricula,
        'active_id':  next(
            (c['id'] for c in unique_curricula if c['is_active']), None
        ),
    })


from django.http import JsonResponse
from django.shortcuts import get_object_or_404


def subadmin_restore_questionnaire(request, pk):
    """Restore an archived questionnaire"""
    if not request.user.is_authenticated:
        return JsonResponse({'error': 'Not authenticated'}, status=401)

    try:
        subadmin      = request.user.subadmin_profile
        questionnaire = get_object_or_404(
            Questionnaire, pk=pk, department=subadmin.department, is_archived=True
        )
        questionnaire.is_archived = False
        questionnaire.save()
        return JsonResponse({'success': True})
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=400)


def subadmin_permanent_delete_questionnaire(request, pk):
    """Permanently delete a questionnaire and its questions"""
    if not request.user.is_authenticated:
        return JsonResponse({'error': 'Not authenticated'}, status=401)

    if request.method != 'DELETE':
        return JsonResponse({'error': 'Method not allowed'}, status=405)

    try:
        subadmin      = request.user.subadmin_profile
        questionnaire = get_object_or_404(
            Questionnaire, pk=pk, department=subadmin.department, is_archived=True
        )
        questionnaire.extracted_questions.all().delete()
        questionnaire.delete()
        return JsonResponse({'success': True})
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=400)


def subadmin_archive_count(request):
    """Get count of archived questionnaires for the subadmin's department"""
    if not request.user.is_authenticated:
        return JsonResponse({'count': 0})

    try:
        subadmin = request.user.subadmin_profile
        count = Questionnaire.objects.filter(
            department=subadmin.department,
            is_archived=True
        ).count()
        return JsonResponse({'count': count})
    except Exception:
        return JsonResponse({'count': 0})