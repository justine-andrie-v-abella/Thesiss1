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


class BISUQuestionnaireGenerator:
    """
    Generates questionnaires in BISU official format.
    """

    def __init__(self):
        self.doc = Document()
        self._setup_page_margins()

    def _setup_page_margins(self):
        """Set page margins to match BISU format"""
        section = self.doc.sections[0]
        section.page_width = Inches(8.5)
        section.page_height = Inches(11)
        section.top_margin = Inches(0.5)
        section.bottom_margin = Inches(1.0)
        section.left_margin = Inches(1.0)
        section.right_margin = Inches(1.0)

    def generate_questionnaire(self, questionnaire_data):
        """Generate a complete questionnaire document."""
        self._add_header(
            questionnaire_data.get('department', 'College Of Computing and Information Sciences'),
            questionnaire_data.get('semester', '1st Semester, A.Y.2025-2026')
        )
        self._add_title_section(
            questionnaire_data['title'],
            questionnaire_data['course_code'],
            questionnaire_data['course_name'],
            questionnaire_data['program'],
            questionnaire_data['instructor']
        )
        self._add_student_info_fields()
        self._add_general_directions(
            questionnaire_data.get('general_directions', self._get_default_directions())
        )
        self._add_questions_by_type(questionnaire_data['questions'])
        return self.doc

    def _add_header(self, department, semester):
        """Add BISU header"""
        # University name (bold, centered)
        p = self.doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run = p.add_run("BOHOL ISLAND STATE UNIVERSITY")
        run.bold = True
        run.font.size = Pt(12)
        run.font.name = 'Calibri'

        # Department
        p = self.doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run = p.add_run(department)
        run.font.size = Pt(10)
        run.font.name = 'Calibri'

        # Semester
        p = self.doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run = p.add_run(semester)
        run.font.size = Pt(10)
        run.font.name = 'Calibri'
        run.italic = True

        self.doc.add_paragraph()

    def _add_title_section(self, title, course_code, course_name, program, instructor):
        """Add exam title and course info in a 2-column layout using a table"""
        table = self.doc.add_table(rows=2, cols=2)
        table.style = 'Table Grid'

        # Hide borders
        from docx.oxml.ns import qn
        from docx.oxml import OxmlElement

        def set_no_border(cell):
            tc = cell._tc
            tcPr = tc.get_or_add_tcPr()
            tcBorders = OxmlElement('w:tcBorders')
            for side in ['top', 'left', 'bottom', 'right', 'insideH', 'insideV']:
                border = OxmlElement(f'w:{side}')
                border.set(qn('w:val'), 'none')
                tcBorders.append(border)
            tcPr.append(tcBorders)

        # Row 0: Title | Program
        cell_left = table.rows[0].cells[0]
        cell_right = table.rows[0].cells[1]
        set_no_border(cell_left)
        set_no_border(cell_right)

        p = cell_left.paragraphs[0]
        r = p.add_run(title)
        r.bold = True
        r.font.size = Pt(11)
        r.font.name = 'Calibri'

        p = cell_right.paragraphs[0]
        p.alignment = WD_ALIGN_PARAGRAPH.RIGHT
        r = p.add_run(program)
        r.font.size = Pt(10)
        r.font.name = 'Calibri'

        # Row 1: Course | Instructor
        cell_left = table.rows[1].cells[0]
        cell_right = table.rows[1].cells[1]
        set_no_border(cell_left)
        set_no_border(cell_right)

        p = cell_left.paragraphs[0]
        r = p.add_run(f"{course_code} – {course_name}")
        r.font.size = Pt(10)
        r.font.name = 'Calibri'

        p = cell_right.paragraphs[0]
        p.alignment = WD_ALIGN_PARAGRAPH.RIGHT
        r = p.add_run(instructor)
        r.font.size = Pt(10)
        r.font.name = 'Calibri'

        self.doc.add_paragraph()

    def _add_student_info_fields(self):
        """Add Name and Section fields using a table"""
        table = self.doc.add_table(rows=1, cols=2)

        # Left: Name
        cell = table.rows[0].cells[0]
        p = cell.paragraphs[0]
        r = p.add_run("Name: ________________________________________________")
        r.font.size = Pt(10)
        r.font.name = 'Calibri'

        # Right: Section
        cell = table.rows[0].cells[1]
        p = cell.paragraphs[0]
        p.alignment = WD_ALIGN_PARAGRAPH.RIGHT
        r = p.add_run("Section: _____________________")
        r.font.size = Pt(10)
        r.font.name = 'Calibri'

        self.doc.add_paragraph()

    def _add_general_directions(self, directions):
        """Add general directions section"""
        p = self.doc.add_paragraph()
        r = p.add_run("GENERAL DIRECTION: ")
        r.bold = True
        r.font.size = Pt(10)
        r.font.name = 'Calibri'

        r2 = p.add_run(directions)
        r2.font.size = Pt(10)
        r2.font.name = 'Calibri'

        self.doc.add_paragraph()

    def _get_default_directions(self):
        return (
            "Write all your answers and solutions directly on the test questionnaire. "
            "Make sure your responses are well-organized and written clearly and legibly. "
            "After three (3) warnings, students caught discussing during the exam will be "
            "asked to IMMEDIATELY SURRENDER their test questionnaires. If you have any "
            "questions during the exam, feel free to ask the instructor for assistance. "
            "Wishing you all the best of luck on your exam!"
        )

    def _add_questions_by_type(self, questions_by_type):
        """Add questions grouped by type"""
        question_number = 1

        for section_key, section_data in questions_by_type.items():
            if not section_data.get('questions'):
                continue

            # Section header (bold)
            p = self.doc.add_paragraph()
            r = p.add_run(f"{section_data['title']}.")
            r.bold = True
            r.font.size = Pt(10)
            r.font.name = 'Calibri'

            r2 = p.add_run(f" {section_data['instruction']}")
            r2.font.size = Pt(10)
            r2.font.name = 'Calibri'

            self.doc.add_paragraph()

            for question in section_data['questions']:
                self._add_question(question, question_number)
                question_number += 1

            self.doc.add_paragraph()

    def _add_question(self, question, number):
        """Add a single question"""
        # Question text
        p = self.doc.add_paragraph()
        r = p.add_run(f"{number}. {question.question_text}")
        r.font.size = Pt(10)
        r.font.name = 'Calibri'

        # Multiple choice options in a table for alignment
        if question.question_type.name == 'multiple_choice':
            opts = [
                ('a', question.option_a),
                ('b', question.option_b),
                ('c', question.option_c),
                ('d', question.option_d),
            ]
            # 2 options per row in a 2-column table
            table = self.doc.add_table(rows=2, cols=2)
            for i, (letter, text) in enumerate(opts):
                row = i // 2
                col = i % 2
                cell = table.rows[row].cells[col]
                p = cell.paragraphs[0]
                r = p.add_run(f"{letter}. {text or ''}")
                r.font.size = Pt(9)
                r.font.name = 'Calibri'
                # Highlight correct answer
                if question.correct_answer.lower() == letter:
                    r.font.color.rgb = RGBColor(0, 128, 0)

            self.doc.add_paragraph()

        elif question.question_type.name == 'true_false':
            p = self.doc.add_paragraph()
            r = p.add_run("   A. True          B. False")
            r.font.size = Pt(9)
            r.font.name = 'Calibri'

    def save_to_buffer(self):
        """Save document to an in-memory buffer (no file needed)"""
        buffer = io.BytesIO()
        self.doc.save(buffer)
        buffer.seek(0)
        return buffer

    def save_docx(self, filepath):
        """Save as DOCX file"""
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        self.doc.save(filepath)
        return filepath

    def save_pdf(self, filepath):
        """Save as PDF (requires docx2pdf or LibreOffice)"""
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


def generate_bisu_questionnaire(questionnaire_obj, selected_questions):
    """
    Main function to generate BISU questionnaire from database objects.

    Returns:
        tuple: (docx_path, pdf_path) - pdf_path may be None if conversion fails
    """
    from collections import defaultdict

    # Group questions by type
    questions_by_type = defaultdict(list)
    for q in selected_questions:
        questions_by_type[q.question_type.name].append(q)

    # Section configuration
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

    # Build ordered sections (only types that have questions)
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

    # Get instructor full name safely
    try:
        instructor_name = questionnaire_obj.uploader.user.get_full_name() or \
                          questionnaire_obj.uploader.user.username
    except Exception:
        instructor_name = "Instructor"

    # Prepare data
    questionnaire_data = {
        'title': questionnaire_obj.title or 'Examination',
        'course_code': questionnaire_obj.subject.code,
        'course_name': questionnaire_obj.subject.name,
        'program': questionnaire_obj.department.code,
        'instructor': instructor_name,
        'department': questionnaire_obj.department.name,
        'semester': '1st Semester, A.Y.2025-2026',
        'questions': sections,
    }

    # Generate document
    generator = BISUQuestionnaireGenerator()
    generator.generate_questionnaire(questionnaire_data)

    # Save to files
    output_dir = os.path.join(settings.MEDIA_ROOT, 'generated_questionnaires')
    os.makedirs(output_dir, exist_ok=True)

    # Sanitize filename
    safe_name = f"{questionnaire_obj.subject.code}_{questionnaire_obj.title}".replace(' ', '_')
    safe_name = "".join(c for c in safe_name if c.isalnum() or c in ('_', '-'))

    docx_path = os.path.join(output_dir, f"{safe_name}.docx")
    pdf_path = os.path.join(output_dir, f"{safe_name}.pdf")

    generator.save_docx(docx_path)

    try:
        generator.save_pdf(pdf_path)
    except Exception as e:
        print(f"PDF generation failed: {e}")
        pdf_path = None

    return docx_path, pdf_path