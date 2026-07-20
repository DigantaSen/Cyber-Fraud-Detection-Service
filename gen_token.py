import urllib.request
import urllib.error
import json
import uuid

base_url = 'http://localhost:8000/api/v1'

def post(url, data, headers={}):
    req = urllib.request.Request(
        url, 
        data=json.dumps(data).encode('utf-8'), 
        headers={'Content-Type': 'application/json', **headers}, 
        method='POST'
    )
    try:
        with urllib.request.urlopen(req) as response:
            return response.status, response.read().decode('utf-8')
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode('utf-8')

body = {
    'email': f'banker_ui_{uuid.uuid4().hex[:6]}@example.com',
    'password': 'Password123',
    'phone': '+919000000000',
    'role': 'BANK_OFFICIAL',
    'jurisdiction_id': 'JUR_MH_MUMBAI'
}
status, _ = post(f'{base_url}/auth/register', body, {'Idempotency-Key': str(uuid.uuid4())})

status, text = post(f'{base_url}/auth/login', {'email': body['email'], 'password': 'Password123'})

if status == 200:
    token = json.loads(text)['data']['access_token']
    with open('frontend/bank/.env.local', 'w') as f:
        f.write(f'VITE_BANK_TOKEN="{token}"\n')
        f.write('VITE_API_BASE_URL=""\n')
    print('Successfully generated token and wrote to frontend/bank/.env.local')
else:
    print('Failed to login:', status, text)
