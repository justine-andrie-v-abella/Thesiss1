# ============================================================================
# FILE: questionnaires/generators.py
# BISU Questionnaire Generator - Creates formatted DOCX and PDF files
# ============================================================================

from docx import Document
from docx.shared import Pt, Inches, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
import io
import os
from django.conf import settings

# ============================================================================
# Path to your custom Word template
# Edit this path if you move the template file
# ============================================================================
TEMPLATE_PATH = r"C:\DJANGO PROJECTS\THESISattempt4\bisu_template.docx"


class BISUQuestionnaireGenerator:
    """
    Generates questionnaires using the BISU official Word template.
    The template (bisu_template.docx) handles all static design:
      - School logo, header branding, borders, fonts, layout
    This code only fills in the dynamic content:
      - Exam title, course info, student fields, questions
    """

    def __init__(self, template_path=None):
        """
        Load the BISU Word template as the base document.
        Falls back to a blank document if the template is not found.
        """
        path = template_path or TEMPLATE_PATH

        if os.path.exists(path):
            self.doc = Document(path)
            print(f"✅ Loaded template: {path}")
        else:
            print(f"⚠️  Template not found at: {path}")
            print("    Falling back to blank document. Please check the TEMPLATE_PATH.")
            self.doc = Document()
            self._setup_page_margins()

    def _setup_page_margins(self):
        """
        Fallback margins — only used when template is NOT found.
        When the template IS loaded, its margins are used automatically.
        """
        section = self.doc.sections[0]
        section.page_width = Inches(8.5)
        section.page_height = Inches(11)
        section.top_margin = Inches(0.5)
        section.bottom_margin = Inches(1.0)
        section.left_margin = Inches(1.0)
        section.right_margin = Inches(1.0)

    def generate_questionnaire(self, questionnaire_data):
        """
        Generate a complete questionnaire document.

        The template already contains the static header (logo, school name,
        department, decorative lines, etc.). This method appends the
        dynamic content after the template's existing content.

        If your template has placeholder text like {{TITLE}}, {{COURSE}},
        etc., use the find-and-replace approach below instead.
        """

        # --- Option A: Append content after template's existing content ---
        # Use this if your template has a pre-designed header but is otherwise blank.

        self._fill_placeholders(questionnaire_data)
        self._add_questions_by_type(questionnaire_data['questions'])

        return self.doc

    # =========================================================================
    # PLACEHOLDER REPLACEMENT
    # In your Word template, type these exact placeholder texts where you want
    # dynamic values to appear:
    #
    #   {{TITLE}}        → Exam title  (e.g. "MIDTERM EXAMINATION")
    #   {{COURSE_CODE}}  → Subject code (e.g. "CC 101")
    #   {{COURSE_NAME}}  → Subject name (e.g. "Introduction to Computing")
    #   {{PROGRAM}}      → Department/program code (e.g. "BSCS")
    #   {{INSTRUCTOR}}   → Instructor name
    #   {{DEPARTMENT}}   → Full department name
    #   {{SEMESTER}}     → Semester string
    #   {{DIRECTIONS}}   → General directions paragraph
    #
    # Save your template, then this code will replace them automatically.
    # =========================================================================

    def _fill_placeholders(self, data):
        """Replace {{PLACEHOLDER}} text in the template with actual values."""
        replacements = {
            '{{TITLE}}':       data.get('title', 'Examination'),
            '{{COURSE_CODE}}': data.get('course_code', ''),
            '{{COURSE_NAME}}': data.get('course_name', ''),
            '{{PROGRAM}}':     data.get('program', ''),
            '{{INSTRUCTOR}}':  data.get('instructor', ''),
            '{{DEPARTMENT}}':  data.get('department', ''),
            '{{SEMESTER}}':    data.get('semester', ''),
            '{{DIRECTIONS}}':  data.get('general_directions', self._get_default_directions()),
        }

        # 1. Replace in main body paragraphs
        for paragraph in self.doc.paragraphs:
            self._replace_all(paragraph, replacements)

        # 2. Replace inside tables in the main body
        for table in self.doc.tables:
            for row in table.rows:
                for cell in row.cells:
                    for paragraph in cell.paragraphs:
                        self._replace_all(paragraph, replacements)

        # 3. Replace in headers AND footers (Word stores these separately per section)
        for section in self.doc.sections:
            for header_footer in [
                section.header,
                section.footer,
                section.even_page_header,
                section.even_page_footer,
                section.first_page_header,
                section.first_page_footer,
            ]:
                if header_footer is None:
                    continue

                # Paragraphs directly in the header/footer
                for paragraph in header_footer.paragraphs:
                    self._replace_all(paragraph, replacements)

                # Tables inside the header/footer
                for table in header_footer.tables:
                    for row in table.rows:
                        for cell in row.cells:
                            for paragraph in cell.paragraphs:
                                self._replace_all(paragraph, replacements)

    def _replace_all(self, paragraph, replacements):
        """Apply all replacements to a single paragraph."""
        for placeholder, value in replacements.items():
            if placeholder in paragraph.text:
                self._replace_in_paragraph(paragraph, placeholder, value)

    # =========================================================================
    # PLACEHOLDER FONT STYLES
    # Customize the font of each placeholder here.
    # Any placeholder not listed below will keep the template's original font.
    #
    # Available style keys:
    #   'font_name'  → e.g. 'Arial', 'Calibri', 'Times New Roman'
    #   'font_size'  → in points, e.g. Pt(14)
    #   'bold'       → True or False
    #   'italic'     → True or False
    #   'underline'  → True or False
    #   'color'      → RGBColor(r, g, b) — remove key to keep template color
    # =========================================================================
    PLACEHOLDER_STYLES = {
        '{{TITLE}}': {
            'font_name': 'Arial narrow',
            'font_size': Pt(14),
            'bold':      True,
            'italic':    False,
            'underline': False,
            # 'color': RGBColor(0, 0, 128),  # uncomment for custom color
        },
        '{{DEPARTMENT}}': {
            'font_name': 'Arial',
            'font_size': Pt(10),
            'bold':      False,
            'italic':    False,
            'underline': False,
        },
        # Add more placeholders below if needed, e.g.:
        # '{{INSTRUCTOR}}': {
        #     'font_name': 'Calibri',
        #     'font_size': Pt(10),
        #     'bold': False,
        #     'italic': True,
        # },
    }

    def _replace_in_paragraph(self, paragraph, placeholder, value):
        """
        Replace placeholder text inside a paragraph while preserving formatting.
        Word sometimes splits a placeholder across multiple runs, so we
        consolidate the full text, replace it, then rewrite the first run.
        If a style is defined in PLACEHOLDER_STYLES, it is applied to the run.
        """
        full_text = ''.join(run.text for run in paragraph.runs)
        if placeholder not in full_text:
            return

        new_text = full_text.replace(placeholder, value)

        # Write the new text into the first run, clear the rest
        if paragraph.runs:
            first_run = paragraph.runs[0]
            first_run.text = new_text
            for run in paragraph.runs[1:]:
                run.text = ''

            # Apply custom font style if defined for this placeholder
            style = self.PLACEHOLDER_STYLES.get(placeholder)
            if style:
                if 'font_name' in style:
                    first_run.font.name = style['font_name']
                if 'font_size' in style:
                    first_run.font.size = style['font_size']
                if 'bold' in style:
                    first_run.bold = style['bold']
                if 'italic' in style:
                    first_run.italic = style['italic']
                if 'underline' in style:
                    first_run.underline = style['underline']
                if 'color' in style:
                    first_run.font.color.rgb = style['color']

    def _get_default_directions(self):
        return (
            "Write all your answers and solutions directly on the test questionnaire. "
            "Make sure your responses are well-organized and written clearly and legibly. "
            "After three (3) warnings, students caught discussing during the exam will be "
            "asked to IMMEDIATELY SURRENDER their test questionnaires. If you have any "
            "questions during the exam, feel free to ask the instructor for assistance. "
            "Wishing you all the best of luck on your exam!"
        )

    # =========================================================================
    # QUESTION SECTIONS
    # These are appended after the template content / placeholders.
    # =========================================================================

    def _add_questions_by_type(self, questions_by_type):
        """Add questions grouped by type/part."""
        question_number = 1

        for section_key, section_data in questions_by_type.items():
            if not section_data.get('questions'):
                continue

            # Section header
            p = self.doc.add_paragraph()
            r = p.add_run(f"{section_data['title']}.")
            r.bold = True
            r.font.size = Pt(12)
            r.font.name = 'Arial'

            r2 = p.add_run(f" {section_data['instruction']}")
            r2.font.size = Pt(12)
            r2.font.name = 'Arial'

            self.doc.add_paragraph()

            for question in section_data['questions']:
                self._add_question(question, question_number)
                question_number += 1

            self.doc.add_paragraph()

    def _add_question(self, question, number):
        """Add a single question with its options."""
        p = self.doc.add_paragraph()
        r = p.add_run(f"{number}. {question.question_text}")
        r.font.size = Pt(12)
        r.font.name = 'Arial'

        if question.question_type.name == 'multiple_choice':
            opts = [
                ('a', question.option_a),
                ('b', question.option_b),
                ('c', question.option_c),
                ('d', question.option_d),
            ]
            table = self.doc.add_table(rows=2, cols=2)
            for i, (letter, text) in enumerate(opts):
                row = i // 2
                col = i % 2
                cell = table.rows[row].cells[col]
                p = cell.paragraphs[0]
                r = p.add_run(f"{letter}. {text or ''}")
                r.font.size = Pt(12)
                r.font.name = 'Arial'
                if question.correct_answer.lower() == letter:
                    r.font.color.rgb = RGBColor(0, 128, 0)

            self.doc.add_paragraph()

        elif question.question_type.name == 'true_false':
            p = self.doc.add_paragraph()
            r = p.add_run("   A. True          B. False")
            r.font.size = Pt(12)
            r.font.name = 'Arial'

    # =========================================================================
    # SAVE METHODS
    # =========================================================================

    def save_to_buffer(self):
        """Save document to an in-memory buffer (for HTTP responses)."""
        buffer = io.BytesIO()
        self.doc.save(buffer)
        buffer.seek(0)
        return buffer

    def save_docx(self, filepath):
        """Save as DOCX file."""
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        self.doc.save(filepath)
        return filepath

    def save_pdf(self, filepath):
        """Save as PDF (requires docx2pdf or LibreOffice)."""
        docx_path = filepath.replace('.pdf', '_temp.docx')
        self.save_docx(docx_path)
        try:
            from docx2pdf import convert
            convert(docx_path, filepath)
            os.remove(docx_path)
            return filepath
        except ImportError:
            print("Warning: docx2pdf not installed. Returning DOCX instead.")
            return docx_path
        except Exception as e:
            print(f"PDF conversion failed: {e}")
            return docx_path


# =============================================================================
# MAIN ENTRY POINT
# =============================================================================

def generate_bisu_questionnaire(questionnaire_obj, selected_questions):
    """
    Generate BISU questionnaire from database objects using the Word template.

    Returns:
        tuple: (docx_path, pdf_path) — pdf_path may be None if conversion fails
    """
    from collections import defaultdict

    questions_by_type = defaultdict(list)
    for q in selected_questions:
        questions_by_type[q.question_type.name].append(q)

    section_config = {
        'identification': {
            'title_label': 'Identification',
            'instruction': 'Read carefully and identify what is being asked.',
        },
        'multiple_choice': {
            'title_label': 'Multiple Choice',
            'instruction': 'Write the CAPITAL LETTER of the best response.',
        },
        'true_false': {
            'title_label': 'True or False',
            'instruction': 'Write TRUE if the statement is correct, otherwise write FALSE.',
        },
        'essay': {
            'title_label': 'Essay',
            'instruction': 'Answer the following questions comprehensively.',
        },
        'fill_blank': {
            'title_label': 'Fill in the Blanks',
            'instruction': 'Complete the following statements.',
        },
        'matching': {
            'title_label': 'Matching Type',
            'instruction': 'Match the items in Column A with those in Column B.',
        },
    }

    sections = {}
    part_number = 1
    for qtype, config in section_config.items():
        if questions_by_type.get(qtype):
            sections[qtype] = {
                'title': f'PART {part_number}. {config["title_label"]}',
                'instruction': config['instruction'],
                'questions': questions_by_type[qtype],
            }
            part_number += 1

    try:
        instructor_name = questionnaire_obj.uploader.user.get_full_name() or \
                          questionnaire_obj.uploader.user.username
    except Exception:
        instructor_name = "Instructor"

    questionnaire_data = {
        'title':             questionnaire_obj.title or 'Examination',
        'course_code':       questionnaire_obj.subject.code,
        'course_name':       questionnaire_obj.subject.name,
        'program':           questionnaire_obj.department.code,
        'instructor':        instructor_name,
        'department':        questionnaire_obj.department.name,
        'semester':          '1st Semester, A.Y.2025-2026',
        'questions':         sections,
    }

    # Generate using the Word template
    generator = BISUQuestionnaireGenerator()
    generator.generate_questionnaire(questionnaire_data)

    output_dir = os.path.join(settings.MEDIA_ROOT, 'generated_questionnaires')
    os.makedirs(output_dir, exist_ok=True)

    safe_name = f"{questionnaire_obj.subject.code}_{questionnaire_obj.title}".replace(' ', '_')
    safe_name = "".join(c for c in safe_name if c.isalnum() or c in ('_', '-'))

    docx_path = os.path.join(output_dir, f"{safe_name}.docx")
    pdf_path  = os.path.join(output_dir, f"{safe_name}.pdf")

    generator.save_docx(docx_path)

    try:
        generator.save_pdf(pdf_path)
    except Exception as e:
        print(f"PDF generation failed: {e}")
        pdf_path = None

    return docx_path, pdf_path