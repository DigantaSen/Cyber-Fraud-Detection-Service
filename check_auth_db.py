import asyncio, asyncpg, os

async def check():
    url = os.environ.get('DATABASE_URL', '').replace('postgresql+asyncpg', 'postgresql')
    conn = await asyncpg.connect(url)
    tables = await conn.fetch(
        "SELECT table_name FROM information_schema.tables WHERE table_schema='auth' ORDER BY table_name"
    )
    print('Auth tables:', [t['table_name'] for t in tables])
    users = await conn.fetch('SELECT email, role, jurisdiction_id FROM auth.users LIMIT 20')
    print('Existing users:')
    for u in users:
        print(' ', u['email'], u['role'], u['jurisdiction_id'])
    await conn.close()

asyncio.run(check())
