import asyncio
from app.db.database import AsyncSessionLocal
from app.models.review import Review
from sqlalchemy import select

async def main():
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Review).where(Review.pr_number == "5366").order_by(Review.created_at.desc())
        )
        reviews = result.scalars().all()
        for r in reviews:
            print(f"ID: {r.id}, PR: {r.pr_number}, Status: {r.status}, Created: {r.created_at}")

asyncio.run(main())
