import os
import re
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization

# Generate private key
private_key = rsa.generate_private_key(
    public_exponent=65537,
    key_size=2048,
)

# Generate public key
public_key = private_key.public_key()

# Serialize private key to PEM
private_pem = private_key.private_bytes(
    encoding=serialization.Encoding.PEM,
    format=serialization.PrivateFormat.PKCS8,
    encryption_algorithm=serialization.NoEncryption()
).decode('utf-8').replace('\n', r'\n')

# Serialize public key to PEM
public_pem = public_key.public_bytes(
    encoding=serialization.Encoding.PEM,
    format=serialization.PublicFormat.SubjectPublicKeyInfo
).decode('utf-8').replace('\n', r'\n')

with open('.env', 'r') as f:
    content = f.read()

content = re.sub(r'JWT_PRIVATE_KEY=\".*?\"', f'JWT_PRIVATE_KEY=\"{private_pem}\"', content, flags=re.DOTALL)
content = re.sub(r'JWT_PUBLIC_KEY=\".*?\"', f'JWT_PUBLIC_KEY=\"{public_pem}\"', content, flags=re.DOTALL)

with open('.env', 'w') as f:
    f.write(content)
print('Keys generated and updated in .env')
