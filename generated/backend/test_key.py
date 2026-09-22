from openai import OpenAI
from app.core.config import settings

client = OpenAI(api_key=settings.xai_api_key, base_url="https://api.groq.com/openai/v1")

models = client.models.list()
for m in models.data:
    print(m.id)