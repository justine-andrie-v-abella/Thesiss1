# ============================================================================
# FILE: questionnaires/services/gemini_extraction_service.py
# ============================================================================

import json
import PyPDF2
import docx
import openpyxl
from typing import List, Dict
from django.conf import settings


class GeminiQuestionnaireExtractor:
    """Extract or generate questions from uploaded files using Google Gemini API"""

    def __init__(self, api_key=None):
        self.api_key = api_key or getattr(settings, 'GEMINI_API_KEY', None)
        if not self.api_key:
            raise ValueError("GEMINI_API_KEY not found in settings")

        try:
            from google import genai
            self.client = genai.Client(api_key=self.api_key)
            self.model = 'gemini-2.5-flash'
        except ImportError:
            raise ImportError("Please install google-genai: pip install google-genai")

    # =========================================================================
    # FILE EXTRACTION
    # =========================================================================

    def extract_text_from_file(self, file_path: str) -> str:
        """Extract text content from various file formats"""
        extension = file_path.lower().split('.')[-1]

        if extension == 'pdf':
            return self._extract_from_pdf(file_path)
        elif extension in ['docx', 'doc']:
            return self._extract_from_docx(file_path)
        elif extension in ['xlsx', 'xls']:
            return self._extract_from_excel(file_path)
        elif extension == 'txt':
            with open(file_path, 'r', encoding='utf-8') as f:
                return f.read()
        else:
            raise ValueError(f"Unsupported file format: {extension}")

    def _extract_from_pdf(self, file_path: str) -> str:
        text = ""
        try:
            with open(file_path, 'rb') as file:
                pdf_reader = PyPDF2.PdfReader(file)
                for page in pdf_reader.pages:
                    extracted = page.extract_text()
                    if extracted:
                        text += extracted + "\n"
        except Exception as e:
            raise Exception(f"Error extracting PDF: {str(e)}")
        return text

    def _extract_from_docx(self, file_path: str) -> str:
        """
        Extract text from DOCX preserving structure.

        Tables are rendered in a way that makes two-column matching type
        sections clearly recognizable to Gemini:

            [TABLE]
            Column A  |  Column B
            1. CREATE  |  A. Permanently deletes a database object.
            2. DROP    |  B. Creates new database objects.
            [/TABLE]

        This format is unambiguous — Gemini will always classify it as
        'matching' rather than 'identification'.
        """
        try:
            document = docx.Document(file_path)
            parts = []

            # Build a set of paragraphs that are inside tables so we can
            # skip them when iterating document.paragraphs (python-docx
            # exposes table cell paragraphs in both places).
            table_para_ids = set()
            for table in document.tables:
                for row in table.rows:
                    for cell in row.cells:
                        for para in cell.paragraphs:
                            table_para_ids.add(id(para))

            # Iterate the document in reading order (paragraphs + tables)
            for block in document.element.body:
                tag = block.tag.split('}')[-1]  # strip namespace

                if tag == 'p':
                    # Regular paragraph
                    para_text = block.text_content().strip() if hasattr(block, 'text_content') else ''
                    # Use python-docx paragraph objects for clean text
                    for para in document.paragraphs:
                        if para._element is block:
                            para_text = para.text.strip()
                            break
                    if para_text:
                        parts.append(para_text)

                elif tag == 'tbl':
                    # Find the matching python-docx Table object
                    table_obj = None
                    for t in document.tables:
                        if t._element is block:
                            table_obj = t
                            break

                    if table_obj is None:
                        continue

                    rows = table_obj.rows
                    if not rows:
                        continue

                    # Collect all cell values
                    grid = []
                    for row in rows:
                        cells = [cell.text.strip() for cell in row.cells]
                        # De-duplicate merged cells (python-docx repeats them)
                        deduped = []
                        for i, c in enumerate(cells):
                            if i == 0 or c != cells[i - 1]:
                                deduped.append(c)
                        grid.append(deduped)

                    # Detect two-column matching table:
                    # - Has exactly 2 columns after dedup
                    # - First column items look like "1. X", "2. X" (numbered)
                    # - Second column items look like "A. X", "B. X" (lettered)
                    col_count = max(len(r) for r in grid) if grid else 0
                    is_matching_table = False

                    if col_count == 2 and len(grid) >= 2:
                        # Check if first data row (skip header if present)
                        # has numbered left and lettered right
                        data_rows = [r for r in grid if len(r) == 2 and r[0] and r[1]]
                        if data_rows:
                            first = data_rows[0]
                            left_numbered  = first[0][:2].strip().rstrip('.').isdigit()
                            right_lettered = first[1][:1].strip().upper().isalpha()
                            is_matching_table = left_numbered or right_lettered

                    if is_matching_table:
                        # Format as an explicit matching block so Gemini
                        # can't mistake it for anything else
                        parts.append("[TABLE]")
                        parts.append("Column A  |  Column B")
                        for row in grid:
                            if len(row) == 2:
                                parts.append(f"{row[0]}  |  {row[1]}")
                            elif len(row) == 1 and row[0]:
                                parts.append(row[0])
                        parts.append("[/TABLE]")
                    else:
                        # Generic table: just join cells with pipes
                        for row in grid:
                            line = '  |  '.join(c for c in row if c)
                            if line:
                                parts.append(line)

            return "\n".join(parts)

        except Exception as e:
            raise Exception(f"Error extracting DOCX: {str(e)}")

    def _extract_from_excel(self, file_path: str) -> str:
        try:
            workbook = openpyxl.load_workbook(file_path)
            text = ""
            for sheet in workbook.worksheets:
                for row in sheet.iter_rows(values_only=True):
                    text += " ".join([str(cell) for cell in row if cell]) + "\n"
            return text
        except Exception as e:
            raise Exception(f"Error extracting Excel: {str(e)}")

    # =========================================================================
    # AI PROCESSING
    # =========================================================================

    def extract_questions_with_ai(
        self,
        content: str,
        question_types: List[str],
        mode: str = 'extract',
        num_questions: int = 10,
    ) -> Dict:
        if mode == 'generate':
            prompt = self._build_generation_prompt(content, question_types, num_questions)
        else:
            prompt = self._build_extraction_prompt(content, question_types)

        try:
            response = self.client.models.generate_content(
                model=self.model,
                contents=prompt,
            )

            response_text = response.text

            if '```json' in response_text:
                response_text = response_text.split('```json')[1].split('```')[0]
            elif '```' in response_text:
                response_text = response_text.split('```')[1].split('```')[0]

            response_text = response_text.strip()
            data = json.loads(response_text)

            if 'questions' not in data or not data['questions']:
                raise Exception("AI response did not contain any questions")

            return data

        except json.JSONDecodeError as e:
            raise Exception(
                f"Failed to parse AI response as JSON: {str(e)}\n"
                f"Response preview: {response_text[:200]}"
            )
        except Exception as e:
            raise Exception(f"AI extraction failed: {str(e)}")

    # =========================================================================
    # PROMPTS
    # =========================================================================

    def _build_extraction_prompt(self, content: str, question_types: List[str]) -> str:
        return f"""You are a question scanner. Your ONLY job is to find and copy questions ALREADY WRITTEN in the text below.

STRICT RULES:
- DO NOT create, generate, invent, or add any new questions.
- DO NOT rephrase or rewrite — copy the question text EXACTLY word for word.
- ONLY include questions that are literally present in the provided text.
- If no questions are found, return {{"questions": []}}.

═══════════════════════════════════════════════════════
SECTION RECOGNITION
═══════════════════════════════════════════════════════
Recognize ALL of these as question sections:
- Roman numerals: I., II., III., IV., V., etc.
- Labels like: Multiple Choice, True or False, Identification, Matching Type,
  Fill in the Blank, Essay, Scenario-Based, Situation-Based, Spot the Error,
  Enumeration, Bonus, Short Answer, Problem Solving, etc.
- Numbered sub-questions inside any section are individual questions.

═══════════════════════════════════════════════════════
QUESTION TYPES
═══════════════════════════════════════════════════════
Use ONLY these types: {', '.join(question_types)}

- "multiple_choice"  → has lettered options A B C D
- "true_false"       → asks true or false
- "identification"   → short answer; also Scenario-Based and Spot-the-Error
- "essay"            → long open-ended answer
- "fill_blank"       → sentence with ___ to complete
- "matching"         → two-column table with Column A and Column B

═══════════════════════════════════════════════════════
MATCHING TYPE — CRITICAL INSTRUCTIONS
═══════════════════════════════════════════════════════
You will see matching tables formatted like this in the text:

    [TABLE]
    Column A  |  Column B
    1. CREATE  |  A. Permanently deletes a database object.
    2. TINYINT  |  B. Creates new database objects.
    3. DROP  |  C. Modifies the structure of an existing table.
    [/TABLE]

OR like this (column A and column B listed separately):

    Column A          Column B
    1. CREATE         A. Permanently deletes a database object.
    2. TINYINT        B. Creates new database objects.

OR like a plain numbered/lettered list:

    1. CREATE     2. TINYINT     3. DROP
    A. Deletes    B. Creates     C. Modifies

For ALL of these formats:
- Treat the ENTIRE section as ONE question with type "matching"
- Set "question" to the section heading or instruction text (e.g. "Matching Type" or "Match Column A to Column B")
- Set "column_a" to ALL Column A items as a JSON array: ["1. CREATE", "2. TINYINT", ...]
- Set "column_b" to ALL Column B items as a JSON array: ["A. Permanently deletes...", "B. Creates...", ...]
- Set "matching_pairs" to the correct answer pairs IF an answer key is present, otherwise []
- NEVER split a matching section into multiple identification questions

═══════════════════════════════════════════════════════
SCENARIO-BASED / SPOT THE ERROR / BONUS
═══════════════════════════════════════════════════════
Each numbered item = its own question.
type: "identification" or "essay"
Copy text exactly, including any code blocks.
correct_answer: "" unless explicitly shown.

═══════════════════════════════════════════════════════
TEXT TO SCAN:
═══════════════════════════════════════════════════════
{content}

═══════════════════════════════════════════════════════
RETURN — valid JSON only, no markdown, no extra text
═══════════════════════════════════════════════════════
{{
    "questions": [
        {{
            "type": "multiple_choice",
            "question": "exact question text",
            "options": {{"a": "...", "b": "...", "c": "...", "d": "..."}},
            "correct_answer": "a",
            "explanation": "",
            "difficulty": "medium",
            "points": 1
        }},
        {{
            "type": "matching",
            "question": "Matching Type",
            "column_a": ["1. CREATE", "2. TINYINT", "3. DROP", "4. DECIMAL(10,2)", "5. ALTER", "6. TRUNCATE", "7. CHAR(2)", "8. RENAME"],
            "column_b": [
                "A. Permanently deletes a database object.",
                "B. Creates new database objects.",
                "C. Modifies the structure of an existing table.",
                "D. Removes all rows but keeps table structure.",
                "E. Changes the name of a table.",
                "F. Storing exact currency values without rounding errors.",
                "G. Storing small whole numbers like age or status flags.",
                "H. Storing fixed-length codes such as country abbreviations (PH, US, UK)"
            ],
            "matching_pairs": [],
            "correct_answer": "",
            "explanation": "",
            "difficulty": "medium",
            "points": 1
        }},
        {{
            "type": "identification",
            "question": "exact question text",
            "correct_answer": "",
            "explanation": "",
            "difficulty": "medium",
            "points": 1
        }},
        {{
            "type": "true_false",
            "question": "exact statement",
            "correct_answer": "true",
            "explanation": "",
            "difficulty": "easy",
            "points": 1
        }},
        {{
            "type": "fill_blank",
            "question": "The ___ command removes all rows but keeps table structure.",
            "correct_answer": "TRUNCATE",
            "explanation": "",
            "difficulty": "easy",
            "points": 1
        }},
        {{
            "type": "essay",
            "question": "exact essay question",
            "correct_answer": "",
            "explanation": "",
            "difficulty": "hard",
            "points": 5
        }}
    ]
}}

JSON:"""

    def _build_generation_prompt(
        self,
        content: str,
        question_types: List[str],
        num_questions: int = 10,
    ) -> str:
        types_str = ', '.join(question_types)
        total     = num_questions * len(question_types)

        return f"""You are an expert teacher creating exam questions.

EDUCATIONAL CONTENT:
{content[:8000]}

TASK:
Generate exactly {num_questions} questions for EACH of these types: {types_str}
Total = {num_questions} × {len(question_types)} = {total} questions.

RULES:
- Base every question on the content above only.
- Vary difficulty: ~30% easy, ~50% medium, ~20% hard.
- multiple_choice : 4 options (a–d), one correct answer.
- true_false      : correct_answer = "true" or "false" (lowercase).
- identification  : correct_answer = specific term or phrase.
- essay           : correct_answer = key points / model answer.
- fill_blank      : use "___" in the question; correct_answer fills it.
- matching        : populate column_a, column_b, and matching_pairs.

Return ONLY valid JSON, no markdown.

{{
    "questions": [
        {{
            "type": "multiple_choice",
            "question": "...",
            "options": {{"a": "...", "b": "...", "c": "...", "d": "..."}},
            "correct_answer": "a",
            "explanation": "...",
            "difficulty": "medium",
            "points": 1
        }},
        {{
            "type": "matching",
            "question": "Match each item in Column A with the correct description in Column B.",
            "column_a": ["1. Term one", "2. Term two", "3. Term three"],
            "column_b": ["A. Description one", "B. Description two", "C. Description three"],
            "matching_pairs": [
                {{"item": "1. Term one",   "match": "A"}},
                {{"item": "2. Term two",   "match": "C"}},
                {{"item": "3. Term three", "match": "B"}}
            ],
            "correct_answer": "1-A, 2-C, 3-B",
            "explanation": "",
            "difficulty": "medium",
            "points": 1
        }}
    ]
}}

JSON:"""

    # =========================================================================
    # ORCHESTRATOR
    # =========================================================================

    def process_questionnaire(
        self,
        questionnaire,
        question_types: List[str],
        mode: str = 'extract',
        num_questions: int = 10,
    ):
        from questionnaires.models import ExtractedQuestion, QuestionType

        type_map = {}
        for qt in QuestionType.objects.filter(is_active=True):
            type_map[qt.name.lower()] = qt
            type_map[qt.name]         = qt

        aliases = {
            'multiple_choice':   'multiple_choice',
            'multiplechoice':    'multiple_choice',
            'mcq':               'multiple_choice',
            'true_false':        'true_false',
            'truefalse':         'true_false',
            'true/false':        'true_false',
            'fill_in_the_blank': 'fill_blank',
            'fill_blank':        'fill_blank',
            'fill in the blank': 'fill_blank',
            'identification':    'identification',
            'essay':             'essay',
            'matching':          'matching',
            'enumeration':       'enumeration',
            'short_answer':      'identification',
            'scenario':          'identification',
            'scenario-based':    'identification',
            'scenario_based':    'identification',
            'situation-based':   'identification',
            'spot the error':    'identification',
            'spot_the_error':    'identification',
            'bonus':             'identification',
            'problem solving':   'essay',
            'problem_solving':   'essay',
        }

        file_path = questionnaire.file.path
        content   = self.extract_text_from_file(file_path)

        if not content.strip():
            raise Exception("No text content could be extracted from the file")

        extracted_data = self.extract_questions_with_ai(
            content,
            question_types,
            mode=mode,
            num_questions=num_questions,
        )

        created_questions = []

        for q_data in extracted_data.get('questions', []):
            try:
                raw_type      = q_data.get('type', '').strip().lower()
                resolved_name = aliases.get(raw_type, raw_type)
                question_type = type_map.get(resolved_name) or type_map.get(raw_type)

                if not question_type:
                    print(f"Warning: type '{raw_type}' not in DB, skipping.")
                    continue

                option_a = option_b = option_c = option_d = None
                correct_answer = q_data.get('correct_answer', '')

                if resolved_name == 'matching':
                    col_a = q_data.get('column_a', [])
                    col_b = q_data.get('column_b', [])
                    pairs = q_data.get('matching_pairs', [])

                    option_a = json.dumps(col_a, ensure_ascii=False)
                    option_b = json.dumps(col_b, ensure_ascii=False)
                    option_c = json.dumps(pairs, ensure_ascii=False)
                    option_d = None

                    if not correct_answer and pairs:
                        correct_answer = ', '.join(
                            f"{p['item'].split('.')[0].strip()}-{p['match']}"
                            for p in pairs
                            if isinstance(p, dict) and 'item' in p and 'match' in p
                        )

                elif q_data.get('options'):
                    opts     = q_data['options']
                    option_a = opts.get('a')
                    option_b = opts.get('b')
                    option_c = opts.get('c')
                    option_d = opts.get('d')

                question = ExtractedQuestion.objects.create(
                    questionnaire  = questionnaire,
                    question_type  = question_type,
                    question_text  = q_data['question'],
                    option_a       = option_a,
                    option_b       = option_b,
                    option_c       = option_c,
                    option_d       = option_d,
                    correct_answer = correct_answer,
                    explanation    = q_data.get('explanation', ''),
                    difficulty     = q_data.get('difficulty', 'medium'),
                    points         = q_data.get('points', 1),
                )
                created_questions.append(question)

            except Exception as e:
                print(f"Error creating question: {e}")
                continue

        if not created_questions:
            raise Exception("No questions were found or created from the file")

        return created_questions