import re

with open('.env', 'r', encoding='utf-8') as f:
    content = f.read()

m = re.search(r'JWT_PUBLIC_KEY=\"(.*?)\"', content, re.DOTALL)
if m:
    pub = m.group(1).replace('\r', '')
    with open('infra/kong/kong.yml', 'r', encoding='utf-8') as f:
        kong = f.read()
    
    indented_pub = ''.join(['          ' + line + '\n' for line in pub.split('\n')])
    
    new_consumers = f"""consumers:
  - username: platform-auth
    jwt_secrets:
      - key: "v1"
        algorithm: RS256
        rsa_public_key: |
{indented_pub}"""
    
    kong = kong.replace('consumers: []', new_consumers)
    
    with open('infra/kong/kong.yml', 'w', encoding='utf-8') as f:
        f.write(kong)
    print("Kong configuration updated successfully.")
else:
    print("JWT_PUBLIC_KEY not found in .env")
