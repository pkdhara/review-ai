import asyncio
import httpx
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
import base64
from app.services.encryption_service import EncryptionService

DATABASE_URL = 'postgresql://reviewai:reviewai_pass@postgres:5432/reviewai'
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def get_token():
    with SessionLocal() as db:
        return db.execute(text('SELECT bitbucket_access_token FROM system_settings LIMIT 1')).scalar()

async def main():
    tok = get_token()
    enc = EncryptionService()
    dec_tok = enc.decrypt(tok)
    auth_header = f"Bearer {dec_tok}"

    diff_headers = {
        "Authorization": auth_header,
        "Accept": "*/*"
    }

    diff_headers_with_content_type = {
        "Authorization": auth_header,
        "Content-Type": "application/json",
        "Accept": "*/*"
    }

    async with httpx.AsyncClient(timeout=10.0, follow_redirects=False) as client:
        print("\nTesting WITHOUT Content-Type...")
        resp = await client.get("https://api.bitbucket.org/2.0/repositories/freshconcepts/fc-angular/pullrequests/5359/diff", headers=diff_headers)
        print(f"Status: {resp.status_code}")
        if resp.status_code == 302:
            loc = resp.headers.get("Location")
            loc_cleaned = loc.replace("%0D", "..").replace("\r", "..")
            resp3 = await client.get(loc_cleaned, headers=diff_headers)
            print(f"Redirect Status Code: {resp3.status_code}")
        
        print("\nTesting WITH Content-Type: application/json...")
        resp2 = await client.get("https://api.bitbucket.org/2.0/repositories/freshconcepts/fc-angular/pullrequests/5359/diff", headers=diff_headers_with_content_type)
        print(f"Status: {resp2.status_code}")
        if resp2.status_code == 302:
            loc = resp2.headers.get("Location")
            loc_cleaned = loc.replace("%0D", "..").replace("\r", "..")
            resp4 = await client.get(loc_cleaned, headers=diff_headers_with_content_type)
            print(f"Redirect Status Code: {resp4.status_code}")

if __name__ == "__main__":
    asyncio.run(main())
