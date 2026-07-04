import httpx
import json
from openai import OpenAI

client = OpenAI(
    base_url='http://localhost:11434/v1',
    api_key='ollama',
    http_client=httpx.Client(timeout=httpx.Timeout(300.0, connect=60.0))
)

response = client.chat.completions.create(
    model='llama3.2:3b',
    messages=[
        {'role': 'system', 'content': 'Return ONLY a valid JSON object with this exact format: {"patches": {"file.py": "fixed code here"}, "explanation": "what you fixed", "security_audit": "secure", "is_secure": true}'},
        {'role': 'user', 'content': 'Fix this bug: def greet(name): return "Hello " + name + 5'}
    ],
    temperature=0.1
)

raw = response.choices[0].message.content
print('=== RAW START ===')
print(raw)
print('=== RAW END ===')