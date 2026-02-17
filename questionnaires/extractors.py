# ============================================================================
# FILE: questionnaires/extractors.py
# AI-Powered Question Extraction System using Gemini API
# ============================================================================

import os
import json
import re
from typing import List, Dict, Any
from django.conf import settings
import google.generativeai as genai

# File reading libraries
try:
    import PyPDF2
    from docx import Document
    import openpyxl
except ImportError:
    pass


class AIQuestionExtractor:
    """
    Scans uploaded files and extracts questions that are already written there.
    Does NOT generate or create new questions.
    Supports: PDF, DOCX, TXT, XLSX, XLS
    """

    def __init__(self):
        api_key = getattr(settings, 'GEMINI_API_KEY', None)
        if not api_key:
            raise ValueError(
                "GEMINI_API_KEY not found in settings. "
                "Please add GEMINI_API_KEY to your settings.py"
            )
        genai.configure(api_key=api_key)
        self.model = genai.GenerativeModel('gemini-2.5-flash')

    def process_questionnaire(self, questionnaire, type_names: List[str], mode: str = 'extract') -> List:
        """
        Process the questionnaire file.

        Args:
            questionnaire: Questionnaire model instance
            type_names: List of question type names to look for
            mode: 'extract' — copy questions already in the file (default)
                  'generate' — create new questions based on the file content

        Returns:
            List of created ExtractedQuestion objects
        """
        from questionnaires.models import ExtractedQuestion, QuestionType

        # Step 1: Read file content
        file_content = self._read_file(questionnaire.file.path, questionnaire.file_type)

        if not file_content.strip():
            raise ValueError("File is empty or could not be read")

        # Step 2: Extract or generate questions depending on mode
        extracted_data = self._extract_with_ai(file_content, type_names, mode=mode)

        # Step 3: Save questions to the database
        created_questions = []
        for question_data in extracted_data:
            try:
                question_type = QuestionType.objects.get(name=question_data['type'])

                question = ExtractedQuestion.objects.create(
                    questionnaire=questionnaire,
                    question_type=question_type,
                    question_text=question_data['question'],
                    option_a=question_data.get('option_a'),
                    option_b=question_data.get('option_b'),
                    option_c=question_data.get('option_c'),
                    option_d=question_data.get('option_d'),
                    correct_answer=question_data.get('answer', ''),
                    explanation=question_data.get('explanation', ''),
                    points=question_data.get('points', 1),
                    difficulty=question_data.get('difficulty', 'medium'),
                    is_approved=False
                )
                created_questions.append(question)
            except Exception as e:
                print(f"Error saving question: {e}")
                continue

        return created_questions

    def _read_file(self, file_path: str, file_type: str) -> str:
        """Read content from various file types"""
        if file_type == 'txt':
            return self._read_txt(file_path)
        elif file_type == 'pdf':
            return self._read_pdf(file_path)
        elif file_type in ['docx', 'doc']:
            return self._read_docx(file_path)
        elif file_type in ['xlsx', 'xls']:
            return self._read_xlsx(file_path)
        else:
            raise ValueError(f"Unsupported file type: {file_type}")

    def _read_txt(self, file_path: str) -> str:
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            return f.read()

    def _read_pdf(self, file_path: str) -> str:
        text = []
        try:
            with open(file_path, 'rb') as f:
                pdf_reader = PyPDF2.PdfReader(f)
                for page in pdf_reader.pages:
                    page_text = page.extract_text()
                    if page_text:
                        text.append(page_text)
        except Exception as e:
            raise ValueError(f"Failed to read PDF: {str(e)}")
        return '\n\n'.join(text)

    def _read_docx(self, file_path: str) -> str:
        try:
            doc = Document(file_path)
            text = []
            for paragraph in doc.paragraphs:
                if paragraph.text.strip():
                    text.append(paragraph.text)
            return '\n'.join(text)
        except Exception as e:
            raise ValueError(f"Failed to read DOCX: {str(e)}")

    def _read_xlsx(self, file_path: str) -> str:
        try:
            workbook = openpyxl.load_workbook(file_path)
            text = []
            for sheet in workbook.worksheets:
                text.append(f"\n=== {sheet.title} ===\n")
                for row in sheet.iter_rows(values_only=True):
                    row_text = '\t'.join([str(cell) if cell is not None else '' for cell in row])
                    if row_text.strip():
                        text.append(row_text)
            return '\n'.join(text)
        except Exception as e:
            raise ValueError(f"Failed to read XLSX: {str(e)}")

    def _extract_with_ai(self, content: str, type_names: List[str], mode: str = 'extract') -> List[Dict[str, Any]]:
        """
        Scan or generate questions depending on mode.
        mode='extract'  → copies questions already written in the file
        mode='generate' → creates new questions based on the file content
        """

        # Limit content to avoid token limits
        if len(content) > 30000:
            content = content[:30000] + "\n... (content truncated)"

        if mode == 'generate':
            prompt = self._build_generation_prompt(content, type_names)
            temperature = 0.7  # Higher — more creative for generation
        else:
            prompt = self._build_extraction_prompt(content, type_names)
            temperature = 0.1  # Very low — exact copying, no creativity

        try:
            response = self.model.generate_content(
                prompt,
                generation_config=genai.GenerationConfig(
                    temperature=temperature,
                    max_output_tokens=8000,
                    response_mime_type="application/json",
                )
            )

            questions = self._parse_ai_response(response.text)
            return questions

        except Exception as e:
            print(f"Gemini API Error: {str(e)}")
            raise Exception(f"AI extraction failed: {str(e)}")

    def _build_extraction_prompt(self, content: str, type_names: List[str]) -> str:
        """
        Prompt that strictly tells Gemini to copy questions from the file,
        not generate new ones.
        """

        type_descriptions = {
            'multiple_choice': 'Multiple Choice (has options A, B, C, D)',
            'true_false':      'True/False (answer is True or False)',
            'identification':  'Identification (short answer, one word or phrase)',
            'essay':           'Essay (requires a long written answer)',
            'fill_blank':      'Fill in the Blank (sentence with a blank to complete)',
            'matching':        'Matching Type (match items from two columns)',
        }

        types_list = '\n'.join([
            f"- {type_descriptions.get(t, t)}" for t in type_names
        ])

        prompt = f"""You are a question scanner. Your ONLY job is to find and copy questions that are ALREADY WRITTEN in the text below.

STRICT RULES — READ CAREFULLY:
- DO NOT create, generate, invent, or add any new questions whatsoever
- DO NOT rephrase, rewrite, or improve any question — copy the text EXACTLY word for word
- ONLY include questions that are literally present in the provided text
- If the text contains no questions, return an empty array []

QUESTION TYPES TO LOOK FOR:
{types_list}

TEXT TO SCAN:
{content}

FOR EACH QUESTION YOU FIND IN THE TEXT, return a JSON object with:
- "type": classify it as one of {type_names}
- "question": copy the question text EXACTLY as it appears in the file
- "option_a", "option_b", "option_c", "option_d": copy the options exactly (multiple choice only, leave out for other types)
- "answer": copy the correct answer if it is shown in the text, otherwise use ""
- "explanation": copy any explanation if it is shown in the text, otherwise use ""
- "difficulty": estimate "easy", "medium", or "hard" based on the question
- "points": copy the point value if shown, otherwise use 1

Return ONLY a valid JSON array with no extra text, no markdown formatting.
If no questions are found in the text, return: []

JSON:"""

        return prompt

    def _build_generation_prompt(self, content: str, type_names: List[str]) -> str:
        """
        Prompt for GENERATING new questions based on the file content.
        Used by the generate_questionnaire view.
        """

        type_descriptions = {
            'multiple_choice': 'Multiple Choice (4 options A, B, C, D)',
            'true_false':      'True/False',
            'identification':  'Identification (short answer)',
            'essay':           'Essay (detailed answer)',
            'fill_blank':      'Fill in the Blank',
            'matching':        'Matching Type',
        }

        types_list = '\n'.join([
            f"- {type_descriptions.get(t, t)}" for t in type_names
        ])

        prompt = f"""You are an expert teacher. Based on the educational content below, generate high-quality exam questions.

QUESTION TYPES TO GENERATE:
{types_list}

CONTENT TO BASE QUESTIONS ON:
{content}

INSTRUCTIONS:
1. Generate questions that test understanding of the content
2. For each question provide:
   - "type": one of {type_names}
   - "question": the question text
   - "option_a", "option_b", "option_c", "option_d": all 4 options (multiple choice only)
   - "answer": the correct answer
   - "explanation": brief explanation of why the answer is correct
   - "difficulty": "easy", "medium", or "hard"
   - "points": 1 for easy, 2 for medium, 3 for hard

3. Generate a good mix of difficulties
4. Return ONLY a valid JSON array, no extra text

JSON:"""

        return prompt
        """Parse Gemini's JSON response"""

        response_text = response_text.strip()

        # Remove markdown code blocks if present
        if '```json' in response_text:
            match = re.search(r'```json\s*\n(.*?)\n```', response_text, re.DOTALL)
            if match:
                response_text = match.group(1).strip()
        elif '```' in response_text:
            response_text = re.sub(r'^```\s*\n', '', response_text)
            response_text = re.sub(r'\n```\s*$', '', response_text)
            response_text = response_text.strip()

        # Find JSON array
        if not response_text.startswith('['):
            json_match = re.search(r'\[.*\]', response_text, re.DOTALL)
            if json_match:
                response_text = json_match.group(0)

        try:
            questions = json.loads(response_text)

            if not isinstance(questions, list):
                return []

            validated = []
            for i, q in enumerate(questions):
                try:
                    if self._validate_question(q):
                        validated.append(q)
                    else:
                        print(f"Skipping question {i+1} — failed validation")
                except Exception as e:
                    print(f"Error validating question {i+1}: {str(e)}")
                    continue

            print(f"Found {len(validated)} questions in file")
            return validated

        except json.JSONDecodeError as e:
            print(f"Failed to parse AI response: {str(e)}")
            print(f"Response preview:\n{response_text[:500]}")

            # Try to recover individual objects
            try:
                objects = re.findall(r'\{[^{}]+\}', response_text, re.DOTALL)
                recovered = []
                for obj_str in objects:
                    try:
                        q = json.loads(obj_str)
                        if self._validate_question(q):
                            recovered.append(q)
                    except:
                        continue
                if recovered:
                    print(f"Recovered {len(recovered)} questions from malformed response")
                    return recovered
            except:
                pass

            raise ValueError(f"Could not parse AI response: {str(e)}")

    def _validate_question(self, question: Dict[str, Any]) -> bool:
        """Validate a question has the minimum required fields"""

        # Must have type and question text at minimum
        if not question.get('type') or not question.get('question'):
            return False

        # Multiple choice must have all 4 options
        if question['type'] == 'multiple_choice':
            for option in ['option_a', 'option_b', 'option_c', 'option_d']:
                if not question.get(option):
                    return False

        # Set defaults for optional fields
        if question.get('difficulty') not in ['easy', 'medium', 'hard']:
            question['difficulty'] = 'medium'

        if not question.get('points'):
            question['points'] = 1

        if 'explanation' not in question:
            question['explanation'] = ''

        if 'answer' not in question:
            question['answer'] = ''

        return True


def get_extractor():
    """Factory function to get an extractor instance"""
    return AIQuestionExtractor()