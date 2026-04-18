from sqlalchemy import create_engine, select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker
from db.models import User
from sqlalchemy.future import select

DATABASE_URL = "postgresql+asyncpg://username:password@localhost/dbname"  # Измени на свои данные

engine = create_async_engine(DATABASE_URL, echo=True)
async_session_maker = sessionmaker(
    engine, class_=AsyncSession, expire_on_commit=False
)

async def get_user(telegram_id: int):
    async with async_session_maker() as session:
        result = await session.execute(select(User).where(User.telegram_id == telegram_id))
        return result.scalar_one_or_none()

async def create_user(telegram_id: int, username: str):
    async with async_session_maker() as session:
        user = User(telegram_id=telegram_id, username=username)
        session.add(user)
        await session.commit()

async def update_subscription_status(user_id: int, status: bool):
    async with async_session_maker() as session:
        result = await session.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        if user:
            user.is_active = status
            await session.commit()

async def update_traffic_limit(user_id: int, limit: int):
    async with async_session_maker() as session:
        result = await session.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        if user:
            user.traffic_limit = limit
            await session.commit()
