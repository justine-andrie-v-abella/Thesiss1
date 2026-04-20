# ============================================================================
# FILE: questionnaires/generators.py
# BISU Questionnaire Generator - Creates formatted DOCX and PDF files
# ============================================================================

from docx import Document
from docx.shared import Pt, Inches, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK
from docx.oxml.ns import qn
from docx.oxml import OxmlElement
import io
import os
from django.conf import settings

TEMPLATE_PATH = r"C:\DJANGO PROJECTS\THESISattempt4\bisu_template.docx"


class BISUQuestionnaireGenerator:

    def __init__(self, template_path=None):
        path = template_path or TEMPLATE_PATH
        if os.path.exists(path):
            self.doc = Document(path)
            print(f"✅ Loaded template: {path}")
        else:
            print(f"⚠️  Template not found at: {path}")
            self.doc = Document()
            self._setup_page_margins()

    def _setup_page_margins(self):
        section = self.doc.sections[0]
        section.page_width    = Inches(8.5)
        section.page_height   = Inches(11)
        section.top_margin    = Inches(0.5)
        section.bottom_margin = Inches(1.0)
        section.left_margin   = Inches(1.0)
        section.right_margin  = Inches(1.0)

    def generate_questionnaire(self, questionnaire_data):
        self._fill_placeholders(questionnaire_data)
        answer_key_data = self._add_questions_by_type(questionnaire_data['questions'])
        if answer_key_data:
            self._add_answer_key_page(answer_key_data)
        return self.doc

    # =========================================================================
    # PLACEHOLDER REPLACEMENT
    # =========================================================================

    def _fill_placeholders(self, data):
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

        for paragraph in self.doc.paragraphs:
            self._replace_all(paragraph, replacements)

        for table in self.doc.tables:
            for row in table.rows:
                for cell in row.cells:
                    for paragraph in cell.paragraphs:
                        self._replace_all(paragraph, replacements)

        for section in self.doc.sections:
            for header_footer in [
                section.header, section.footer,
                section.even_page_header, section.even_page_footer,
                section.first_page_header, section.first_page_footer,
            ]:
                if header_footer is None:
                    continue
                for paragraph in header_footer.paragraphs:
                    self._replace_all(paragraph, replacements)
                for table in header_footer.tables:
                    for row in table.rows:
                        for cell in row.cells:
                            for paragraph in cell.paragraphs:
                                self._replace_all(paragraph, replacements)

    def _replace_all(self, paragraph, replacements):
        for placeholder, value in replacements.items():
            if placeholder in paragraph.text:
                self._replace_in_paragraph(paragraph, placeholder, value)

    PLACEHOLDER_STYLES = {
        '{{TITLE}}': {
            'font_name': 'Arial narrow',
            'font_size': Pt(14),
            'bold':      True,
            'italic':    False,
            'underline': False,
        },
        '{{DEPARTMENT}}': {
            'font_name': 'Arial',
            'font_size': Pt(10),
            'bold':      False,
            'italic':    False,
            'underline': False,
        },
    }

    def _replace_in_paragraph(self, paragraph, placeholder, value):
        full_text = ''.join(run.text for run in paragraph.runs)
        if placeholder not in full_text:
            return
        new_text = full_text.replace(placeholder, value)
        if paragraph.runs:
            first_run = paragraph.runs[0]
            first_run.text = new_text
            for run in paragraph.runs[1:]:
                run.text = ''
            style = self.PLACEHOLDER_STYLES.get(placeholder)
            if style:
                if 'font_name'  in style: first_run.font.name     = style['font_name']
                if 'font_size'  in style: first_run.font.size      = style['font_size']
                if 'bold'       in style: first_run.bold           = style['bold']
                if 'italic'     in style: first_run.italic         = style['italic']
                if 'underline'  in style: first_run.underline      = style['underline']
                if 'color'      in style: first_run.font.color.rgb = style['color']

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
    # =========================================================================

    def _add_questions_by_type(self, questions_by_type):
        """Adds all question sections and returns answer-key data grouped by type."""
        question_number = 1
        answer_key = {}

        for section_key, section_data in questions_by_type.items():
            if not section_data.get('questions'):
                continue

            # Section header (bold part title + instruction)
            p  = self.doc.add_paragraph()
            r  = p.add_run(f"{section_data['title']}.")
            r.bold = True
            r.font.size = Pt(12)
            r.font.name = 'Arial'
            r2 = p.add_run(f" {section_data['instruction']}")
            r2.font.size = Pt(12)
            r2.font.name = 'Arial'

            self.doc.add_paragraph()

            section_answers = []
            for question in section_data['questions']:
                self._add_question(question, question_number)
                qtype = question.question_type.name
                if qtype != 'essay':
                    if qtype == 'matching':
                        md = question.get_matching_data()
                        pairs = md.get('pairs', []) if md else []
                        section_answers.append((question_number, 'matching', pairs))
                    else:
                        section_answers.append(
                            (question_number, qtype, question.correct_answer or '')
                        )
                question_number += 1

            if section_answers:
                answer_key[section_key] = {
                    'title':   section_data['title'],
                    'answers': section_answers,
                }

            self.doc.add_paragraph()

        return answer_key

    def _add_question(self, question, number):
        """Dispatch to the correct renderer based on question type."""
        qtype = question.question_type.name

        if qtype == 'matching':
            # Matching: render the table WITHOUT printing a numbered stem.
            # The section header already tells students what to do.
            # The overall question_number is still consumed (counts as 1).
            self._add_matching_question(question, number)
            return

        # All other types: print the numbered question stem first.
        # True/False gets a blank prepended before the number (like identification).
        if qtype == 'true_false':
            p = self.doc.add_paragraph()
            r = p.add_run(f"________ {number}. {question.question_text}")
            r.font.size = Pt(12)
            r.font.name = 'Arial'
        else:
            p = self.doc.add_paragraph()
            r = p.add_run(f"{number}. {question.question_text}")
            r.font.size = Pt(12)
            r.font.name = 'Arial'

        if qtype == 'multiple_choice':
            self._add_multiple_choice(question)

        elif qtype in ('identification', 'fill_blank', 'fill_in_the_blank'):
            p = self.doc.add_paragraph()
            r = p.add_run("Answer: ________________________")
            r.font.size = Pt(12)
            r.font.name = 'Arial'

        elif qtype == 'essay':
            for _ in range(4):
                p = self.doc.add_paragraph()
                r = p.add_run("_" * 80)
                r.font.size = Pt(10)
                r.font.name = 'Arial'

    # =========================================================================
    # MULTIPLE CHOICE
    # =========================================================================

    def _add_multiple_choice(self, question):
        opts = [
            ('a', question.option_a),
            ('b', question.option_b),
            ('c', question.option_c),
            ('d', question.option_d),
        ]
        table = self.doc.add_table(rows=2, cols=2)
        for i, (letter, text) in enumerate(opts):
            cell = table.rows[i // 2].cells[i % 2]
            p = cell.paragraphs[0]
            r = p.add_run(f"{letter}. {text or ''}")
            r.font.size = Pt(12)
            r.font.name = 'Arial'
        self.doc.add_paragraph()

    # =========================================================================
    # MATCHING TYPE
    # =========================================================================

    def _add_matching_question(self, question, start_number):
        """
        Render a matching question as a full-width, invisible-border table.

        Layout per row:
            _____ | 1. Term | Description text

        Columns:
            Col 0  "Blank"   — answer line  (narrow)
            Col 1  "Col A"   — numbered term
            Col 2  "Col B"   — lettered description (widest)

        The entire table is centred and spans the full text width.
        All borders are invisible (white / no border).
        A bold column-header row labels each column.
        """
        md = question.get_matching_data()

        if not md:
            p = self.doc.add_paragraph()
            r = p.add_run(
                f"   [Could not render matching table. "
                f"Raw answer key: {question.correct_answer or '(none)'}]"
            )
            r.italic = True
            r.font.size = Pt(11)
            r.font.name = 'Arial'
            self.doc.add_paragraph()
            return

        column_a = md['column_a']   # ["1. CREATE", "2. DROP", ...]
        column_b = md['column_b']   # ["A. Deletes object", ...]
        pairs    = md['pairs']      # [{"item": "1. CREATE", "match": "B"}, ...]

        n_rows = max(len(column_a), len(column_b))
        if n_rows == 0:
            return

        # ── Page / content width ──────────────────────────────────────────
        # Derive from the first section so it works with any template margins.
        section      = self.doc.sections[0]
        page_w       = section.page_width
        left_margin  = section.left_margin
        right_margin = section.right_margin
        content_w    = page_w - left_margin - right_margin   # in EMUs

        # Convert to DXA (1 DXA = 914400/1440 EMU = 635 EMU)
        content_w_dxa = int(content_w / 635)

        # Column proportions:  blank 10% | ColA 30% | ColB 60%
        col_blank = int(content_w_dxa * 0.10)
        col_a     = int(content_w_dxa * 0.30)
        col_b     = content_w_dxa - col_blank - col_a   # remainder

        # ── Build table: 1 header row + n data rows ───────────────────────
        table = self.doc.add_table(rows=1 + n_rows, cols=3)

        # Full-width + centred
        tbl    = table._tbl
        tblPr  = tbl.find(qn('w:tblPr'))
        if tblPr is None:
            tblPr = OxmlElement('w:tblPr')
            tbl.insert(0, tblPr)

        # Table width
        tblW = OxmlElement('w:tblW')
        tblW.set(qn('w:w'),    str(content_w_dxa))
        tblW.set(qn('w:type'), 'dxa')
        existing = tblPr.find(qn('w:tblW'))
        if existing is not None:
            tblPr.remove(existing)
        tblPr.append(tblW)

        # Horizontal alignment = center
        jc = OxmlElement('w:jc')
        jc.set(qn('w:val'), 'center')
        existing = tblPr.find(qn('w:jc'))
        if existing is not None:
            tblPr.remove(existing)
        tblPr.append(jc)

        # Remove default table borders (make all borders invisible)
        self._set_table_borders_invisible(tblPr)

        # Set column widths
        self._set_col_widths(table, [col_blank, col_a, col_b])

        # ── Header row ────────────────────────────────────────────────────
        header_labels = ['Ans.', 'Column A', 'Column B']
        for ci, label in enumerate(header_labels):
            cell = table.rows[0].cells[ci]
            p    = cell.paragraphs[0]
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER if ci == 0 else WD_ALIGN_PARAGRAPH.LEFT
            r    = p.add_run(label)
            r.bold      = True
            r.underline = True
            r.font.size = Pt(11)
            r.font.name = 'Arial'

        # ── Data rows ─────────────────────────────────────────────────────
        for i in range(n_rows):
            row = table.rows[i + 1]

            # Col 0 — answer blank, centred
            cell_blank = row.cells[0]
            p = cell_blank.paragraphs[0]
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            r = p.add_run("_______")
            r.font.size = Pt(11)
            r.font.name = 'Arial'

            # Col 1 — Column A item (e.g. "1. CREATE")
            a_text  = column_a[i] if i < len(column_a) else ''
            cell_a  = row.cells[1]
            p = cell_a.paragraphs[0]
            r = p.add_run(a_text)
            r.font.size = Pt(11)
            r.font.name = 'Arial'

            # Col 2 — Column B item (e.g. "A. Deletes object")
            b_text  = column_b[i] if i < len(column_b) else ''
            cell_b  = row.cells[2]
            p = cell_b.paragraphs[0]
            r = p.add_run(b_text)
            r.font.size = Pt(11)
            r.font.name = 'Arial'

        self.doc.add_paragraph()

    # =========================================================================
    # TABLE HELPERS
    # =========================================================================

    @staticmethod
    def _set_col_widths(table, widths_dxa):
        """Set individual column widths (DXA) on every cell in each column."""
        for ci, width in enumerate(widths_dxa):
            for cell in table.columns[ci].cells:
                tc   = cell._tc
                tcPr = tc.get_or_add_tcPr()
                tcW  = OxmlElement('w:tcW')
                tcW.set(qn('w:w'),    str(width))
                tcW.set(qn('w:type'), 'dxa')
                existing = tcPr.find(qn('w:tcW'))
                if existing is not None:
                    tcPr.remove(existing)
                tcPr.append(tcW)

    @staticmethod
    def _set_table_borders_invisible(tblPr):
        """
        Add a <w:tblBorders> element that sets all six border positions to
        'none' so the table grid lines are completely invisible.
        """
        # Remove any existing tblBorders first
        existing = tblPr.find(qn('w:tblBorders'))
        if existing is not None:
            tblPr.remove(existing)

        tblBorders = OxmlElement('w:tblBorders')
        for border_name in ('top', 'left', 'bottom', 'right', 'insideH', 'insideV'):
            border = OxmlElement(f'w:{border_name}')
            border.set(qn('w:val'),   'none')
            border.set(qn('w:sz'),    '0')
            border.set(qn('w:space'), '0')
            border.set(qn('w:color'), 'auto')
            tblBorders.append(border)

        tblPr.append(tblBorders)

    @staticmethod
    def _shade_cell(cell, fill_hex):
        """Apply a background fill colour to a table cell."""
        tc   = cell._tc
        tcPr = tc.get_or_add_tcPr()
        shd  = OxmlElement('w:shd')
        shd.set(qn('w:val'),   'clear')
        shd.set(qn('w:color'), 'auto')
        shd.set(qn('w:fill'),  fill_hex)
        existing = tcPr.find(qn('w:shd'))
        if existing is not None:
            tcPr.remove(existing)
        tcPr.append(shd)

    # =========================================================================
    # ANSWER KEY PAGE
    # =========================================================================

    def _add_answer_key_page(self, answer_key_data):
        """
        Appends a dedicated Answer Key page at the very end of the document.
        A hard page-break separates it from the question body so it can be
        detached before handing out the test.
        """
        # ── Hard page break ───────────────────────────────────────────────
        p   = self.doc.add_paragraph()
        run = p.add_run()
        run.add_break(WD_BREAK.PAGE)

        # ── Page heading ──────────────────────────────────────────────────
        p = self.doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        r = p.add_run('ANSWER KEY')
        r.bold           = True
        r.font.size      = Pt(16)
        r.font.name      = 'Arial'

        p = self.doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        r = p.add_run('(For Instructor Use Only — Detach Before Distributing)')
        r.italic         = True
        r.font.size      = Pt(10)
        r.font.name      = 'Arial'
        r.font.color.rgb = RGBColor(100, 100, 100)

        self._add_horizontal_rule()
        self.doc.add_paragraph()

        # ── Answers grouped by section ────────────────────────────────────
        for section_key, section_data in answer_key_data.items():
            answers = section_data.get('answers', [])
            if not answers:
                continue

            # Section label
            p = self.doc.add_paragraph()
            r = p.add_run(section_data['title'] + ':')
            r.bold      = True
            r.font.size = Pt(12)
            r.font.name = 'Arial'

            if section_key == 'matching':
                # Show Column-A-item → Column-B-letter pairs
                for num, _qtype, pairs in answers:
                    if not pairs:
                        continue
                    parts = []
                    for pair in pairs:
                        item  = pair.get('item', '')
                        match = pair.get('match', '?')
                        n     = item.split('.')[0].strip() if '.' in str(item) else str(item)
                        parts.append(f"{n}\u2192{match}")
                    p = self.doc.add_paragraph()
                    r = p.add_run('   '.join(parts))
                    r.font.size = Pt(11)
                    r.font.name = 'Arial'

            else:
                # Layout as a compact grid (5 answers per row)
                cols = 5
                rows_needed = (len(answers) + cols - 1) // cols
                table = self.doc.add_table(rows=rows_needed, cols=cols)

                # Invisible borders
                tbl   = table._tbl
                tblPr = tbl.find(qn('w:tblPr'))
                if tblPr is None:
                    tblPr = OxmlElement('w:tblPr')
                    tbl.insert(0, tblPr)
                self._set_table_borders_invisible(tblPr)

                for idx, (num, _qtype, answer) in enumerate(answers):
                    row_i = idx // cols
                    col_i = idx % cols
                    cell  = table.rows[row_i].cells[col_i]
                    p     = cell.paragraphs[0]
                    r     = p.add_run(f"{num}. {answer}")
                    r.font.size = Pt(11)
                    r.font.name = 'Arial'

            self.doc.add_paragraph()

    def _add_horizontal_rule(self):
        """Add a simple decorative rule paragraph."""
        p = self.doc.add_paragraph()
        r = p.add_run('\u2500' * 55)
        r.font.size      = Pt(9)
        r.font.name      = 'Arial'
        r.font.color.rgb = RGBColor(150, 150, 150)

    # =========================================================================
    # SAVE METHODS
    # =========================================================================

    def save_to_buffer(self):
        buffer = io.BytesIO()
        self.doc.save(buffer)
        buffer.seek(0)
        return buffer

    def save_docx(self, filepath):
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        self.doc.save(filepath)
        return filepath

    def save_pdf(self, filepath):
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
    Returns: tuple (docx_path, pdf_path)  — pdf_path may be None.
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
        'fill_in_the_blank': {
            'title_label': 'Fill in the Blanks',
            'instruction': 'Complete the following statements.',
        },
        'matching': {
            'title_label': 'Matching Type',
            'instruction': (
                'Match the items in Column A with their correct description in Column B. '
                'Write the letter of your answer in the blank provided.'
            ),
        },
    }

    sections = {}
    part_number = 1
    for qtype, config in section_config.items():
        if questions_by_type.get(qtype):
            sections[qtype] = {
                'title':       f'PART {part_number}. {config["title_label"]}',
                'instruction': config['instruction'],
                'questions':   questions_by_type[qtype],
            }
            part_number += 1

    try:
        instructor_name = (questionnaire_obj.uploader.user.get_full_name()
                           or questionnaire_obj.uploader.user.username)
    except Exception:
        instructor_name = "Instructor"

    questionnaire_data = {
        'title':       questionnaire_obj.title or 'Examination',
        'course_code': questionnaire_obj.subject.code,
        'course_name': questionnaire_obj.subject.name,
        'program':     questionnaire_obj.department.code,
        'instructor':  instructor_name,
        'department':  questionnaire_obj.department.name,
        'semester':    '1st Semester, A.Y.2025-2026',
        'questions':   sections,
    }

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