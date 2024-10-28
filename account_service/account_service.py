from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from sqlalchemy import Column, Integer, String, select
from jose import JWTError, jwt
import datetime
from contextlib import asynccontextmanager


DATABASE_URL = 'postgresql+asyncpg://user:password@db:5432/account_db'
SECRET_KEY = "key"
ALGORITHM = "HS256"

engine = create_async_engine(DATABASE_URL, echo=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine, class_=AsyncSession)
Base = declarative_base()

class User(Base):
    __tablename__ = 'users'
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, nullable=False)
    password = Column(String, nullable=False)
    first_name = Column(String)
    last_name = Column(String)
    role = Column(String, nullable=False)


class UserCreate(BaseModel):
    username: str
    password: str
    firstName: str
    lastName: str
    role: str = "user"

class UserResponse(BaseModel):
    id: int
    username: str
    firstName: str
    lastName: str
    role: str

class Token(BaseModel):
    access_token: str
    refresh_token: str


oauth2_scheme = OAuth2PasswordBearer(tokenUrl="api/Authentication/SignIn")

@asynccontextmanager
async def create_tables(app: FastAPI):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        yield

@asynccontextmanager
async def lifespan(app: FastAPI):

    async with create_tables(app):
        yield  #

app = FastAPI(lifespan=lifespan)


async def get_db() -> AsyncSession:
    async with SessionLocal() as db:
        yield db


def create_token(data: dict, expires_delta: datetime.timedelta):
    to_encode = data.copy()
    to_encode.update({"exp": datetime.datetime.utcnow() + expires_delta})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

@app.post("/api/Authentication/SignIn", response_model=Token)
async def sign_in(username: str, password: str, db: AsyncSession = Depends(get_db)):
    statement = select(User).where(User.username == username)
    result = await db.execute(statement)
    user = result.scalars().first()

    if not user or user.password != password:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")


    access_token = create_token(
        {"user_id": user.id, "role": user.role},
        datetime.timedelta(hours=1)
    )
    refresh_token = create_token(
        {"user_id": user.id, "role": user.role},
        datetime.timedelta(days=7)
    )
    return {"access_token": access_token, "refresh_token": refresh_token}



@app.post("/api/Authentication/SignUp", response_model=UserResponse)
async def sign_up(user: UserCreate, db: AsyncSession = Depends(get_db)):
    new_user = User(**user.dict())
    db.add(new_user)
    await db.commit()
    await db.refresh(new_user)
    return new_user


@app.get("/api/Authentication/Validate")
async def validate_token(token: str = Depends(oauth2_scheme)):
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return {"valid": True, "user_id": payload.get("user_id")}
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")


@app.get("/api/Accounts/Me", response_model=UserResponse)
async def get_me(token: str = Depends(oauth2_scheme), db: AsyncSession = Depends(get_db)):
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id = payload.get("user_id")
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

    statement = select(User).where(User.id == user_id)
    result = await db.execute(statement)
    user = result.scalars().first()

    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    return user
