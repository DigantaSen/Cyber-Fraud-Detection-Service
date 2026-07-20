import urllib.request
import urllib.error
import re

with open('frontend/bank/.env.local', 'r') as f:
    env = f.read()
token = re.search(r'VITE_BANK_TOKEN="(.*?)"', env).group(1)

req = urllib.request.Request('http://localhost:8000/api/v1/bank/transactions/flagged', headers={'Authorization': f'Bearer {token}'})
try:
    with urllib.request.urlopen(req) as response:
        print('HTTP', response.status)
        print(response.read().decode('utf-8'))
except urllib.error.HTTPError as e:
    print('Error HTTP', e.code)
    print(e.read().decode('utf-8'))
