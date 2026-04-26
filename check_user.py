import asyncio
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from backend.app.core.config import settings
from backend.app.models import User

async def check_user():
    # 创建数据库引擎
    engine = create_async_engine(settings.DATABASE_URL)
    async_session = sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )
    
    async with async_session() as session:
        async with session.begin():
            # 查找test1用户
            from sqlalchemy import select
            result = await session.execute(select(User).where(User.username == "test1"))
            user = result.scalar_one_or_none()
            
            if user:
                print(f"用户存在: {user.username}")
                print(f"邮箱: {user.email}")
                print(f"密码哈希: {user.hashed_password}")
                print(f"是否活跃: {user.is_active}")
            else:
                print("用户不存在")
    
    # 关闭引擎
    await engine.dispose()

if __name__ == "__main__":
    asyncio.run(check_user())