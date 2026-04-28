import os, requests
from dotenv import load_dotenv
load_dotenv()

key = os.getenv('SERPER_API_KEY')

endpoints = [
    'https://google.serper.dev/jobs',
    'https://google.serper.dev/search',
]

for url in endpoints:
    resp = requests.post(
        url,
        headers={'X-API-KEY': key, 'Content-Type': 'application/json'},
        json={'q': 'software engineer new grad', 'num': 3}
    )
    print(f'{url} -> {resp.status_code}')
    if resp.status_code == 200:
        data = resp.json()
        print(f'  Keys: {list(data.keys())}')
        if 'jobs' in data:
            print(f'  Jobs found: {len(data["jobs"])}')
        if 'organic' in data:
            print(f'  Organic found: {len(data["organic"])}')
    print()
