import os, requests
from dotenv import load_dotenv
load_dotenv()

resp = requests.post(
    'https://google.serper.dev/search',
    headers={'X-API-KEY': os.getenv('SERPER_API_KEY'), 'Content-Type': 'application/json'},
    json={'q': 'software engineer new grad', 'num': 10}
)
data = resp.json()
for i, r in enumerate(data.get('organic', []), 1):
    link = r.get('link', '')
    title = r.get('title', '')
    print(f'{i}. {title}')
    print(f'   {link}')
    print()
