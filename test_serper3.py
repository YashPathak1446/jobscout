import os, requests
from dotenv import load_dotenv
load_dotenv()

queries = [
    'software engineer new grad 2026 site:greenhouse.io',
    'software engineer new grad 2026 site:lever.co',
    'ML engineer new grad site:linkedin.com/jobs/view',
]

for q in queries:
    resp = requests.post(
        'https://google.serper.dev/search',
        headers={'X-API-KEY': os.getenv('SERPER_API_KEY'), 'Content-Type': 'application/json'},
        json={'q': q, 'num': 5}
    )
    data = resp.json()
    results = data.get('organic', [])
    print(f'Query: "{q}" -> {len(results)} results')
    for r in results[:3]:
        print(f'  {r.get("title", "")[:60]}')
        print(f'  {r.get("link", "")}')
    print()
