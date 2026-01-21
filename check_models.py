from decouple import config
from google import genai

api_key = config('GEMINI_API_KEY', default='')
client = genai.Client(api_key=api_key)

print("\n" + "="*60)
print("Available Gemini Models:")
print("="*60 + "\n")

try:
    models = client.models.list()
    for model in models:
        print(f"✓ {model.name}")
        if hasattr(model, 'display_name'):
            print(f"  Display Name: {model.display_name}")
        print()
except Exception as e:
    print(f"Error: {e}")