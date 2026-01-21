from decouple import config

print("\n" + "="*60)
print("Testing Google Gemini API Connection")
print("="*60)

api_key = config('GEMINI_API_KEY', default='')

if not api_key:
    print("\n❌ ERROR: No Gemini API key found in .env file!")
    print("Please add GEMINI_API_KEY to your .env file\n")
    exit()

print(f"\n✓ API Key found: {api_key[:20]}...")

try:
    from google import genai
    
    print("\n⏳ Connecting to Google Gemini API...")
    client = genai.Client(api_key=api_key)
    
    response = client.models.generate_content(
        model='gemini-2.5-flash',
        contents='Say "API connection successful!" and nothing else.'
    )
    
    print("\n✅ SUCCESS! Gemini API is working!")
    print(f"✓ Gemini Response: {response.text}")
    print("\n" + "="*60 + "\n")
    
except ImportError:
    print("\n❌ ERROR: google-genai package not installed")
    print("Run: pip install google-genai\n")
except Exception as e:
    print(f"\n❌ ERROR: {str(e)}")
    print("\nPossible issues:")
    print("1. Invalid API key")
    print("2. No internet connection")
    print("3. API quota exceeded\n")
    print("="*60 + "\n")