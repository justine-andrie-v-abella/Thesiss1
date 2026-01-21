from decouple import config

print("\n" + "="*60)
print("Testing .env Configuration")
print("="*60)

api_key = config('GEMINI_API_KEY', default='')
secret_key = config('SECRET_KEY', default='')
debug = config('DEBUG', default=True, cast=bool)

print(f"\n✓ SECRET_KEY loaded: {'YES' if secret_key else 'NO'}")
if secret_key:
    print(f"  Preview: {secret_key[:20]}...")

print(f"\n✓ DEBUG mode: {debug}")

print(f"\n✓ ANTHROPIC_API_KEY loaded: {'YES' if api_key else 'NO'}")
if api_key:
    print(f"  Preview: {api_key[:25]}...")
else:
    print("  ✗ ERROR: API Key not found in .env file!")

print("\n" + "="*60 + "\n")