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
                    text += page.extract_text() + "\n"
        except Exception as e:
            raise Exception(f"Error extracting PDF: {str(e)}")
        return text

    def _extract_from_docx(self, file_path: str) -> str:
        try:
            document = docx.Document(file_path)
            return "\n".join([paragraph.text for paragraph in document.paragraphs])
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
    # AI PROCESSING  — main entry point
    # =========================================================================

    def extract_questions_with_ai(
        self,
        content: str,
        question_types: List[str],
        mode: str = 'extract',
        num_questions: int = 10,
    ) -> Dict:
        """
        Use Gemini AI to process questions from content.

        mode='extract'  → scans the file and copies questions already written there
        mode='generate' → creates new questions based on the file content
        num_questions   → how many questions to generate per type (generate mode only)
        """

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

            # Clean up markdown code fences if present
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
        """
        Prompt for SCANNING the file and copying questions already written there.
        Used by upload_questionnaire view.
        """
        return f"""You are a question scanner. Your ONLY job is to find and copy questions that are ALREADY WRITTEN in the text below.

STRICT RULES:
- DO NOT create, generate, invent, or add any new questions
- DO NOT rephrase or rewrite — copy the question text EXACTLY word for word as it appears
- ONLY include questions that are literally present in the provided text
- If no questions are found, return {{"questions": []}}

QUESTION TYPES TO LOOK FOR:
{', '.join(question_types)}

TEXT TO SCAN:
{content[:8000]}

FOR EACH QUESTION YOU FIND, return a JSON object with:
- "type": classify as one of {question_types}
- "question": exact question text copied from the file
- "options": {{"a": "...", "b": "...", "c": "...", "d": "..."}} (multiple choice only)
- "correct_answer": the answer if shown in the file, otherwise ""
- "explanation": any explanation shown in the file, otherwise ""
- "difficulty": estimate "easy", "medium", or "hard"
- "points": point value if shown, otherwise 1

CRITICAL: Return ONLY a valid JSON object. No markdown, no code blocks, just pure JSON.

JSON Structure:
{{
    "questions": [
        {{
            "type": "multiple_choice",
            "question": "exact question text from file",
            "options": {{
                "a": "exact option A from file",
                "b": "exact option B from file",
                "c": "exact option C from file",
                "d": "exact option D from file"
            }},
            "correct_answer": "a",
            "explanation": "",
            "difficulty": "medium",
            "points": 1
        }},
        {{
            "type": "identification",
            "question": "exact question text from file",
            "correct_answer": "answer if shown",
            "explanation": "",
            "difficulty": "medium",
            "points": 1
        }}
    ]
}}

If no questions are found in the text, return: {{"questions": []}}

JSON:"""

    def _build_generation_prompt(
        self,
        content: str,
        question_types: List[str],
        num_questions: int = 10,
    ) -> str:
        """
        Prompt for GENERATING new questions based on the file content.
        Used by generate_questionnaire view.
        """
        types_str   = ', '.join(question_types)
        total       = num_questions * len(question_types)

        return f"""You are an expert teacher creating exam questions.

EDUCATIONAL CONTENT:
{content[:8000]}

TASK:
Generate exactly {num_questions} questions for EACH of the following question types: {types_str}
Total questions = {num_questions} × {len(question_types)} type(s) = {total} questions.

IMPORTANT RULES:
- Base every question strictly on the content provided above. Do NOT invent facts outside it.
- Vary difficulty across each type: roughly 30% easy, 50% medium, 20% hard.
- Each question must be clear, unambiguous, and answerable from the content.
- For multiple_choice : provide exactly 4 options (a–d) with exactly one correct answer.
- For true_false      : correct_answer must be lowercase "true" or "false".
- For identification  : correct_answer is a specific term or short phrase from the content.
- For essay           : provide key points or a model answer in correct_answer.
- For fill_blank      : write the sentence with "___" for the blank; correct_answer fills it.
- For matching        : list items as "1. X | 2. Y | 3. Z" and answers as matching pairs.

CRITICAL: Return ONLY a valid JSON object. No markdown, no explanation, no code blocks.

Required JSON structure:
{{
    "questions": [
        {{
            "type": "multiple_choice",
            "question": "Question text here?",
            "options": {{
                "a": "First option",
                "b": "Second option",
                "c": "Third option",
                "d": "Fourth option"
            }},
            "correct_answer": "a",
            "explanation": "Why this is the correct answer.",
            "difficulty": "medium",
            "points": 1
        }},
        {{
            "type": "true_false",
            "question": "Statement that is true or false.",
            "correct_answer": "true",
            "explanation": "Brief explanation.",
            "difficulty": "easy",
            "points": 1
        }},
        {{
            "type": "identification",
            "question": "What term refers to ...?",
            "correct_answer": "Term",
            "explanation": "Explanation.",
            "difficulty": "medium",
            "points": 1
        }},
        {{
            "type": "fill_blank",
            "question": "The ___ is responsible for ...",
            "correct_answer": "missing word",
            "explanation": "Explanation.",
            "difficulty": "easy",
            "points": 1
        }},
        {{
            "type": "essay",
            "question": "Discuss the significance of ...",
            "correct_answer": "Key points: 1) ... 2) ... 3) ...",
            "explanation": "",
            "difficulty": "hard",
            "points": 5
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
        """
        Main method called by views.

        Reads the file attached to `questionnaire`, sends the text to Gemini,
        then persists each returned question as an ExtractedQuestion row.

        Parameters
        ----------
        questionnaire : Questionnaire instance
        question_types : list of QuestionType.name strings
        mode           : 'extract' (copy existing) | 'generate' (create new)
        num_questions  : questions per type when mode='generate'
        """
        from questionnaires.models import ExtractedQuestion, QuestionType

        # ── Build a lookup: type name → QuestionType DB object ───────────────
        type_map = {}
        for qt in QuestionType.objects.filter(is_active=True):
            type_map[qt.name.lower()] = qt
            type_map[qt.name]         = qt

        # Common aliases the AI might return
        aliases = {
            'multiple_choice':    'multiple_choice',
            'multiplechoice':     'multiple_choice',
            'mcq':                'multiple_choice',
            'true_false':         'true_false',
            'truefalse':          'true_false',
            'true/false':         'true_false',
            'fill_in_the_blank':  'fill_blank',
            'fill_blank':         'fill_blank',
            'fill in the blank':  'fill_blank',
            'identification':     'identification',
            'essay':              'essay',
            'matching':           'matching',
            'enumeration':        'enumeration',
            'short_answer':       'identification',
        }

        # ── Extract text from the uploaded file ──────────────────────────────
        file_path = questionnaire.file.path
        content   = self.extract_text_from_file(file_path)

        if not content.strip():
            raise Exception("No text content could be extracted from the file")

        # ── Call Gemini ───────────────────────────────────────────────────────
        extracted_data = self.extract_questions_with_ai(
            content,
            question_types,
            mode=mode,
            num_questions=num_questions,
        )

        # ── Persist questions ─────────────────────────────────────────────────
        created_questions = []
        for q_data in extracted_data.get('questions', []):
            try:
                raw_type      = q_data.get('type', '').strip().lower()
                resolved_name = aliases.get(raw_type, raw_type)
                question_type = type_map.get(resolved_name) or type_map.get(raw_type)

                if not question_type:
                    print(
                        f"Warning: Question type '{raw_type}' not found in database. "
                        f"Available: {list(type_map.keys())}"
                    )
                    # Fallback to first active type rather than silently dropping
                    question_type = QuestionType.objects.filter(is_active=True).first()
                    if not question_type:
                        continue

                question = ExtractedQuestion.objects.create(
                    questionnaire  = questionnaire,
                    question_type  = question_type,
                    question_text  = q_data['question'],
                    option_a       = q_data.get('options', {}).get('a'),
                    option_b       = q_data.get('options', {}).get('b'),
                    option_c       = q_data.get('options', {}).get('c'),
                    option_d       = q_data.get('options', {}).get('d'),
                    correct_answer = q_data.get('correct_answer', ''),
                    explanation    = q_data.get('explanation', ''),
                    difficulty     = q_data.get('difficulty', 'medium'),
                    points         = q_data.get('points', 1),
                )
                created_questions.append(question)

            except Exception as e:
                print(f"Error creating question: {str(e)}")
                continue

        if not created_questions:
            raise Exception("No questions were found or created from the file")

        return created_questions