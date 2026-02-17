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
    pass  # These will be installed


class AIQuestionExtractor:
    """
    Extracts questions from uploaded files using Gemini AI.
    Supports: PDF, DOCX, TXT, XLSX, XLS
    """
    
    def __init__(self):
        # Initialize Gemini client
        api_key = getattr(settings, 'GEMINI_API_KEY', None)
        if not api_key:
            raise ValueError(
                "GEMINI_API_KEY not found in settings. "
                "Please add GEMINI_API_KEY to your settings.py"
            )
        genai.configure(api_key=api_key)
        self.model = genai.GenerativeModel('gemini-2.5-flash')  # Gemini Flash 2.5
    
    def process_questionnaire(self, questionnaire, type_names: List[str]) -> List:
        """
        Main method to extract questions from a questionnaire file.
        
        Args:
            questionnaire: Questionnaire model instance
            type_names: List of question type names to extract (e.g., ['multiple_choice', 'true_false'])
        
        Returns:
            List of created ExtractedQuestion objects
        """
        from questionnaires.models import ExtractedQuestion, QuestionType
        
        # Step 1: Read file content
        file_content = self._read_file(questionnaire.file.path, questionnaire.file_type)
        
        if not file_content.strip():
            raise ValueError("File is empty or could not be read")
        
        # Step 2: Extract questions using Gemini AI
        extracted_data = self._extract_with_ai(file_content, type_names)
        
        # Step 3: Create ExtractedQuestion objects
        created_questions = []
        for question_data in extracted_data:
            try:
                # Get or create question type
                question_type = QuestionType.objects.get(name=question_data['type'])
                
                # Create ExtractedQuestion
                question = ExtractedQuestion.objects.create(
                    questionnaire=questionnaire,
                    question_type=question_type,
                    question_text=question_data['question'],
                    option_a=question_data.get('option_a'),
                    option_b=question_data.get('option_b'),
                    option_c=question_data.get('option_c'),
                    option_d=question_data.get('option_d'),
                    correct_answer=question_data['answer'],
                    explanation=question_data.get('explanation', ''),
                    points=question_data.get('points', 1),
                    difficulty=question_data.get('difficulty', 'medium'),
                    is_approved=False  # Teacher will review
                )
                created_questions.append(question)
            except Exception as e:
                print(f"Error creating question: {e}")
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
        """Read plain text file"""
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            return f.read()
    
    def _read_pdf(self, file_path: str) -> str:
        """Extract text from PDF"""
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
        """Extract text from Word document"""
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
        """Extract text from Excel spreadsheet"""
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
    
    def _extract_with_ai(self, content: str, type_names: List[str]) -> List[Dict[str, Any]]:
        """
        Use Gemini AI to extract questions from content.
        
        Returns a list of question dictionaries with structure:
        {
            'type': 'multiple_choice',
            'question': 'What is...?',
            'option_a': 'Answer A',
            'option_b': 'Answer B',
            'option_c': 'Answer C',
            'option_d': 'Answer D',
            'answer': 'A',
            'explanation': 'Because...',
            'difficulty': 'medium',
            'points': 1
        }
        """
        
        # Limit content length to avoid token limits (about 30000 chars ~ 7500 tokens)
        if len(content) > 30000:
            content = content[:30000] + "\n... (content truncated)"
        
        # Build the prompt for Gemini
        prompt = self._build_extraction_prompt(content, type_names)
        
        # Call Gemini API
        try:
            response = self.model.generate_content(
                prompt,
                generation_config=genai.GenerationConfig(
                    temperature=0.2,  # Lower temperature for more consistent extraction
                    max_output_tokens=8000,
                    response_mime_type="application/json",  # Request JSON response
                )
            )
            
            # Parse Gemini's response
            response_text = response.text
            questions = self._parse_ai_response(response_text)
            
            return questions
            
        except Exception as e:
            print(f"Gemini API Error: {str(e)}")
            raise Exception(f"AI extraction failed: {str(e)}")
    
    def _build_extraction_prompt(self, content: str, type_names: List[str]) -> str:
        """Build the prompt for Gemini AI"""
        
        # Map type names to readable descriptions
        type_descriptions = {
            'multiple_choice': 'Multiple Choice (with 4 options A, B, C, D)',
            'true_false': 'True/False',
            'identification': 'Identification (short answer)',
            'essay': 'Essay (requires detailed answer)',
            'fill_blank': 'Fill in the Blanks',
            'matching': 'Matching Type'
        }
        
        types_to_extract = [type_descriptions.get(t, t) for t in type_names]
        types_list = '\n'.join([f"- {t}" for t in types_to_extract])
        
        prompt = f"""Extract ALL questions from the following educational material and return them as a JSON array.

QUESTION TYPES TO EXTRACT:
{types_list}

CONTENT TO ANALYZE:
{content}

INSTRUCTIONS:
1. Find ALL questions in the content that match the specified types
2. For each question, extract:
   - type: one of {type_names}
   - question: the question text
   - For multiple_choice: option_a, option_b, option_c, option_d (all 4 required)
   - answer: the correct answer
   - explanation: brief explanation (optional, can be empty string)
   - difficulty: "easy", "medium", or "hard"
   - points: integer (default 1)

3. Return ONLY a valid JSON array, nothing else.

EXAMPLE OUTPUT FORMAT:
[
  {{
    "type": "multiple_choice",
    "question": "What is the capital of France?",
    "option_a": "London",
    "option_b": "Paris",
    "option_c": "Berlin",
    "option_d": "Madrid",
    "answer": "B",
    "explanation": "Paris is the capital of France",
    "difficulty": "easy",
    "points": 1
  }},
  {{
    "type": "true_false",
    "question": "Python is interpreted",
    "answer": "True",
    "explanation": "",
    "difficulty": "medium",
    "points": 1
  }}
]

Extract all questions now:"""
        
        return prompt
    
    def _parse_ai_response(self, response_text: str) -> List[Dict[str, Any]]:
        """Parse Gemini's JSON response into question dictionaries"""
        
        # Clean the response
        response_text = response_text.strip()
        
        # Remove markdown code blocks if present
        if '```json' in response_text:
            # Extract content between ```json and ```
            match = re.search(r'```json\s*\n(.*?)\n```', response_text, re.DOTALL)
            if match:
                response_text = match.group(1).strip()
        elif '```' in response_text:
            # Remove ``` markers
            response_text = re.sub(r'^```\s*\n', '', response_text)
            response_text = re.sub(r'\n```\s*$', '', response_text)
            response_text = response_text.strip()
        
        # Find JSON array in the response (look for [ ... ])
        if not response_text.startswith('['):
            json_match = re.search(r'\[.*\]', response_text, re.DOTALL)
            if json_match:
                response_text = json_match.group(0)
        
        try:
            questions = json.loads(response_text)
            
            if not isinstance(questions, list):
                print(f"WARNING: Response is not a list, got {type(questions)}")
                return []
            
            # Validate and clean each question
            validated_questions = []
            for i, q in enumerate(questions):
                try:
                    if self._validate_question(q):
                        validated_questions.append(q)
                    else:
                        print(f"WARNING: Question {i+1} failed validation: {q.get('question', 'unknown')[:50]}")
                except Exception as e:
                    print(f"WARNING: Error validating question {i+1}: {str(e)}")
                    continue
            
            print(f"Successfully parsed {len(validated_questions)} questions")
            return validated_questions
            
        except json.JSONDecodeError as e:
            # Log the problematic response for debugging
            print(f"ERROR: Failed to parse AI response")
            print(f"Response text (first 1000 chars):\n{response_text[:1000]}")
            print(f"JSON Error: {str(e)}")
            
            # Try to extract individual question objects
            try:
                # Look for individual question objects
                objects = re.findall(r'\{[^}]+\}', response_text, re.DOTALL)
                questions = []
                for obj_str in objects:
                    try:
                        q = json.loads(obj_str)
                        if self._validate_question(q):
                            questions.append(q)
                    except:
                        continue
                
                if questions:
                    print(f"Recovered {len(questions)} questions from malformed JSON")
                    return questions
            except:
                pass
            
            raise ValueError(f"Invalid JSON response from AI: {str(e)}")
    
    def _validate_question(self, question: Dict[str, Any]) -> bool:
        """Validate a question dictionary has required fields"""
        
        required_fields = ['type', 'question', 'answer']
        
        # Check required fields
        for field in required_fields:
            if field not in question or not question[field]:
                return False
        
        # Validate multiple choice has all options
        if question['type'] == 'multiple_choice':
            required_options = ['option_a', 'option_b', 'option_c', 'option_d']
            for option in required_options:
                if option not in question or not question[option]:
                    return False
        
        # Set defaults for optional fields
        if 'difficulty' not in question or question['difficulty'] not in ['easy', 'medium', 'hard']:
            question['difficulty'] = 'medium'
        
        if 'points' not in question:
            question['points'] = 1
        
        if 'explanation' not in question:
            question['explanation'] = ''
        
        return True


def get_extractor():
    """Factory function to get an extractor instance"""
    return AIQuestionExtractor()