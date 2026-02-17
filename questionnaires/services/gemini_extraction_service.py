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

    def extract_questions_with_ai(self, content: str, question_types: List[str], mode: str = 'extract') -> Dict:
        """
        Use Gemini AI to process questions from content.

        mode='extract'  → scans the file and copies questions already written there
        mode='generate' → creates new questions based on the file content
        """

        if mode == 'generate':
            prompt = self._build_generation_prompt(content, question_types)
        else:
            prompt = self._build_extraction_prompt(content, question_types)

        try:
            response = self.client.models.generate_content(
                model=self.model,
                contents=prompt
            )

            response_text = response.text

            # Clean up response
            if "```json" in response_text:
                response_text = response_text.split("```json")[1].split("```")[0]
            elif "```" in response_text:
                response_text = response_text.split("```")[1].split("```")[0]

            response_text = response_text.strip()

            data = json.loads(response_text)

            if 'questions' not in data or not data['questions']:
                raise Exception("AI response did not contain any questions")

            return data

        except json.JSONDecodeError as e:
            raise Exception(f"Failed to parse AI response as JSON: {str(e)}\nResponse preview: {response_text[:200]}")
        except Exception as e:
            raise Exception(f"AI extraction failed: {str(e)}")

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

    def _build_generation_prompt(self, content: str, question_types: List[str]) -> str:
        """
        Prompt for GENERATING new questions based on the file content.
        Used by generate_questionnaire view.
        """
        return f"""You are an expert teacher. Based on the educational content below, generate high-quality exam questions.

CONTENT:
{content[:8000]}

TASK:
Generate questions of the following types: {', '.join(question_types)}
Create 5-10 high-quality questions per type based on the content.

QUESTION TYPES GUIDE:
- multiple_choice: question + 4 options (A-D) + correct answer (use lowercase: a, b, c, or d)
- true_false: statement + correct answer (lowercase: "true" or "false")
- identification: question requiring a specific term or concept
- essay: open-ended analytical question
- fill_blank: sentence with a blank + the answer
- matching: two columns to match

CRITICAL: Return ONLY a valid JSON object. No markdown, no code blocks, just pure JSON.

JSON Structure:
{{
    "questions": [
        {{
            "type": "multiple_choice",
            "question": "What is the primary function of X?",
            "options": {{
                "a": "First option",
                "b": "Second option",
                "c": "Third option",
                "d": "Fourth option"
            }},
            "correct_answer": "a",
            "explanation": "Brief explanation why this is correct",
            "difficulty": "medium",
            "points": 1
        }},
        {{
            "type": "true_false",
            "question": "Python is a compiled language.",
            "correct_answer": "false",
            "explanation": "Python is an interpreted language",
            "difficulty": "easy",
            "points": 1
        }},
        {{
            "type": "identification",
            "question": "What term describes a function that calls itself?",
            "correct_answer": "Recursion",
            "explanation": "Recursion is when a function calls itself",
            "difficulty": "medium",
            "points": 1
        }}
    ]
}}

JSON:"""

    def process_questionnaire(self, questionnaire, question_types: List[str], mode: str = 'extract'):
        """
        Main method to process uploaded questionnaire.

        mode='extract'  → copies questions already written in the file (default)
        mode='generate' → creates new questions based on the file content
        """
        from questionnaires.models import ExtractedQuestion, QuestionType

        # Read the file
        file_path = questionnaire.file.path
        content = self.extract_text_from_file(file_path)

        if not content.strip():
            raise Exception("No text content could be extracted from the file")

        # Process with AI using the correct mode
        extracted_data = self.extract_questions_with_ai(content, question_types, mode=mode)

        # Save questions to database
        created_questions = []
        for q_data in extracted_data.get('questions', []):
            try:
                question_type = QuestionType.objects.get(name=q_data['type'])

                question = ExtractedQuestion.objects.create(
                    questionnaire=questionnaire,
                    question_type=question_type,
                    question_text=q_data['question'],
                    option_a=q_data.get('options', {}).get('a'),
                    option_b=q_data.get('options', {}).get('b'),
                    option_c=q_data.get('options', {}).get('c'),
                    option_d=q_data.get('options', {}).get('d'),
                    correct_answer=q_data.get('correct_answer', ''),
                    explanation=q_data.get('explanation', ''),
                    difficulty=q_data.get('difficulty', 'medium'),
                    points=q_data.get('points', 1)
                )
                created_questions.append(question)
            except QuestionType.DoesNotExist:
                print(f"Warning: Question type '{q_data['type']}' not found in database")
                continue
            except Exception as e:
                print(f"Error creating question: {str(e)}")
                continue

        if not created_questions:
            raise Exception("No questions were found or created from the file")

        return created_questions