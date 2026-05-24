from decouple import config

print("\n" + "="*60)
print("Testing Anthropic API Connection")
print("="*60)

api_key = config('ANTHROPIC_API_KEY', default='')

if not api_key:
    print("\n❌ ERROR: No API key found in .env file!")
    print("Please add ANTHROPIC_API_KEY to your .env file\n")
    exit()

print(f"\n✓ API Key found: {api_key[:25]}...")

try:
    from anthropic import Anthropic
    
    print("\n⏳ Connecting to Anthropic API...")
    client = Anthropic(api_key=api_key)
    
    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=100,
        messages=[
            {"role": "user", "content": "Say 'API connection successful!' and nothing else."}
        ]
    )
    
    response = message.content[0].text
    
    print("\n✅ SUCCESS! API is working!")
    print(f"✓ Claude Response: {response}")
    print("\n" + "="*60 + "\n")
    
except ImportError:
    print("\n❌ ERROR: anthropic package not installed")
    print("Run: pip install anthropic\n")
except Exception as e:
    print(f"\n❌ ERROR: {str(e)}")
    print("\nPossible issues:")
    print("1. Invalid API key")
    print("2. No internet connection")
    print("3. API key doesn't have proper permissions\n")
    print("="*60 + "\n")