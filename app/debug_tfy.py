import os
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

token = os.environ["TFY_API_TOKEN"]
print(token[:12], "...", token[-12:])

client = OpenAI(
    api_key=token,
    base_url="https://gateway.truefoundry.ai",
)

resp = client.chat.completions.create(
    model="bedrock/deepseek.v3.2",
    messages=[{"role": "user", "content": "Reply with exactly: ok"}],
)

print(resp.choices[0].message.content)