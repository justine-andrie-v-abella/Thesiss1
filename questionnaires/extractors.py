# ============================================================================
# FILE: questionnaires/extractors.py
# AI-Powered Question Extraction System using Anthropic Claude API
# ============================================================================

import os
import json
import re
import logging
from typing import List, Dict, Any
from django.conf import settings
import anthropic

logger = logging.getLogger(__name__)

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

    CLAUDE_MODEL = 'claude-3-haiku-20240307'

    def __init__(self):
        api_key = getattr(settings, 'ANTHROPIC_API_KEY', None)
        if not api_key:
            raise ValueError(
                "ANTHROPIC_API_KEY not found in settings. "
                "Please add ANTHROPIC_API_KEY to your .env file."
            )
        self.client = anthropic.Anthropic(api_key=api_key)

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
                logger.error("Error saving question: %s", e, exc_info=True)
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
            # Read paragraphs AND table cells so no content is missed
            # (answer keys are sometimes placed inside tables in Word documents)
            for block in doc.element.body:
                tag = block.tag.split('}')[-1] if '}' in block.tag else block.tag
                if tag == 'p':
                    # Plain paragraph
                    para_text = ''.join(
                        node.text for node in block.iter()
                        if node.tag.endswith('}t') and node.text
                    ).strip()
                    if para_text:
                        text.append(para_text)
                elif tag == 'tbl':
                    # Table — read every cell row by row
                    for row in block.iter('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}tr'):
                        row_cells = []
                        for cell in row.iter('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}tc'):
                            cell_text = ''.join(
                                node.text for node in cell.iter()
                                if node.tag.endswith('}t') and node.text
                            ).strip()
                            if cell_text:
                                row_cells.append(cell_text)
                        if row_cells:
                            text.append('  |  '.join(row_cells))
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

        # Claude Haiku supports up to 200k tokens.
        # Always preserve the END of the document — that's where answer keys live.
        MAX_CHARS = 150_000
        if len(content) > MAX_CHARS:
            head = content[:100_000]
            tail = content[-50_000:]
            content = head + "\n\n... (middle section truncated) ...\n\n" + tail

        if mode == 'generate':
            prompt = self._build_generation_prompt(content, type_names)
            temperature = 0.7
        else:
            prompt = self._build_extraction_prompt(content, type_names)
            temperature = 0.1

        try:
            response = self.client.messages.create(
                model=self.CLAUDE_MODEL,
                max_tokens=8096,
                temperature=temperature,
                system=(
                    "You are a precise document scanner that extracts exam questions. "
                    "You always respond with valid JSON only — no explanation, no markdown."
                ),
                messages=[
                    {"role": "user",      "content": prompt},
                    {"role": "assistant", "content": "["},   # force JSON array start
                ],
            )

            # Claude prefill: the response continues after our "[" prefix
            raw = "[" + response.content[0].text
            questions = self._parse_ai_response(raw)
            return questions

        except Exception as e:
            logger.error("Anthropic API error: %s", e, exc_info=True)
            raise Exception(f"AI extraction failed: {str(e)}") from e

    def _build_extraction_prompt(self, content: str, type_names: List[str]) -> str:
        """
        Prompt that tells Claude to copy questions from the file and match
        answers from any answer key section (inline or end-of-document).
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

        prompt = f"""You are scanning a test questionnaire document. Do exactly two things: extract every question, and find the correct answer for each one.

QUESTION TYPES TO FIND:
{types_list}

RULES FOR EXTRACTING QUESTIONS:
- Copy every question text EXACTLY word for word — do NOT rephrase or invent anything.
- Do NOT treat answer key entries as questions.
- If no questions are found at all, return [].

RULES FOR FINDING ANSWERS:
1. First, look for an answer key section anywhere in the document (usually at the end).
   It may be labeled: "Answer Key", "ANSWER KEY", "Key", "Answers", or similar.

2. The answer key often restarts numbering per section. For example:
     "Part I: 1. Subset   2. V   3. Cartesian Product ..."
     "Part II: 1. C   2. A   3. B ..."
   Here "Part II: 1. C" is the answer for the FIRST question under the Part II heading
   in the document body, NOT for question number 1 overall.
   Match answers by counting position within each section.

3. If the answer is a letter (A/B/C/D), store only that letter in uppercase.
   If the answer is text, store it exactly as written.
   For True/False, store "True" or "False".

4. If an answer is written inline next to a question (e.g. "Answer: X"), use that.

5. If no answer can be found for a question anywhere in the document, use "".

TEXT TO SCAN:
{content}

OUTPUT: Return ONLY a valid JSON array — no extra text, no markdown, no code fences.
Each element must have these fields:
  "type"        - one of {type_names}
  "question"    - exact question text copied from the document
  "option_a"    - (multiple choice only, otherwise omit)
  "option_b"    - (multiple choice only, otherwise omit)
  "option_c"    - (multiple choice only, otherwise omit)
  "option_d"    - (multiple choice only, otherwise omit)
  "answer"      - correct answer matched from the answer key, or ""
  "explanation" - any explanation text found, or ""
  "difficulty"  - "easy", "medium", or "hard"
  "points"      - point value if shown, otherwise 1

If no questions found, return: []"""

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

    def _parse_ai_response(self, response_text: str) -> List[Dict[str, Any]]:
        """Parse Claude's JSON response into a list of question dicts."""

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

        # Find JSON array if response has extra text around it
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
                        logger.debug("Skipping question %d — failed validation", i + 1)
                except Exception as e:
                    logger.warning("Error validating question %d: %s", i + 1, e)
                    continue

            logger.debug("Found %d valid questions in AI response", len(validated))
            return validated

        except json.JSONDecodeError as e:
            logger.error("Failed to parse AI response: %s\nPreview: %s", e, response_text[:500])

            # Try to recover individual objects from a malformed response
            try:
                objects = re.findall(r'\{[^{}]+\}', response_text, re.DOTALL)
                recovered = []
                for obj_str in objects:
                    try:
                        q = json.loads(obj_str)
                        if self._validate_question(q):
                            recovered.append(q)
                    except (ValueError, json.JSONDecodeError):
                        continue
                if recovered:
                    logger.warning("Recovered %d questions from malformed response", len(recovered))
                    return recovered
            except Exception as recover_err:
                logger.error("Recovery attempt failed: %s", recover_err)

            raise ValueError(f"Could not parse AI response: {str(e)}") from e

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