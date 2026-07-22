import urllib.request, urllib.error, json, uuid

base = 'http://localhost:8000/api/v1'

def post(url, data, extra_headers={}):
    headers = {'Content-Type': 'application/json', **extra_headers}
    req = urllib.request.Request(url, data=json.dumps(data).encode(), headers=headers, method='POST')
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())

accounts = [
    {'email': 'telecom.admin@fraud.gov.in', 'password': 'Telecom@2024!', 'role': 'TELECOM_ADMIN'},
    {'email': 'bank.officer@fraud.gov.in',  'password': 'BankOff@2024!', 'role': 'BANK_OFFICIAL'},
]

for acc in accounts:
    body_data = {
        'email': acc['email'],
        'password': acc['password'],
        'phone': '+919000000000',
        'role': acc['role'],
        'jurisdiction_id': 'JUR_MH_MUMBAI',
        'orgId': None
    }
    s, b = post(f'{base}/auth/register', body_data, {'Idempotency-Key': str(uuid.uuid4())})
    role = acc['role']
    detail = b.get('data', {}) if s < 300 else b.get('detail', b)
    print(f'{role} register [{s}]: {str(detail)[:150]}')

    # Verify login works
    s2, b2 = post(f'{base}/auth/login', {'email': acc['email'], 'password': acc['password']})
    if s2 == 200:
        token = b2.get('data', {}).get('access_token', 'N/A')
        print(f'{role} login  [{s2}]: token={token[:40]}...')
    else:
        print(f'{role} login  [{s2}]: FAILED - {str(b2.get("detail", b2))[:150]}')
    print()
