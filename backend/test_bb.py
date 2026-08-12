import asyncio
from app.db.database import AsyncSessionLocal
from app.services.settings_service import SettingsService
from app.services.bitbucket_service import BitbucketService
from app.services.encryption_service import EncryptionService

async def main():
    async with AsyncSessionLocal() as session:
        settings_service = SettingsService(session)
        cfg = await settings_service.get()
        enc = EncryptionService()
        bb_token = enc.decrypt(cfg.bitbucket_access_token)
        
        bb = BitbucketService(
            workspace="freshconcepts",
            access_token=bb_token,
            email=None
        )
        
        user_data = await bb._get("/user")
        print(user_data.get("account_id"))
        print(user_data.get("display_name"))

asyncio.run(main())
