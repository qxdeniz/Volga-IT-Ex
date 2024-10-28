from fastapi import FastAPI, Depends, HTTPException, status
from sqlmodel import SQLModel, Field, create_engine, Session, select
from typing import List, Optional
from datetime import datetime
from httpx import AsyncClient
from contextlib import asynccontextmanager


DATABASE_URL = 'postgresql+asyncpg://user:password@db:5432/document_db'
AUTH_SERVICE_URL = 'http://localhost:8081/api/Authentication/Validate'
ACCOUNT_SERVICE_URL = 'http://localhost:8081/api/Accounts/'
HOSPITAL_SERVICE_URL = 'http://localhost:8082/api/Hospitals/'


engine = create_engine(DATABASE_URL, echo=True, future=True)

class History(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    date: datetime
    pacient_id: int
    hospital_id: int
    doctor_id: int
    room: str
    data: str

class HistoryCreate(SQLModel):
    date: datetime
    pacient_id: int
    hospital_id: int
    doctor_id: int
    room: str
    data: str

class HistoryUpdate(SQLModel):
    date: datetime
    hospital_id: int
    doctor_id: int
    room: str
    data: str




@asynccontextmanager
async def lifespan(app: FastAPI):
    async with engine.begin() as conn:

        await conn.run_sync(SQLModel.metadata.create_all)
        yield

app = FastAPI(lifespan=lifespan)


async def get_session() -> Session:
    async with Session(engine) as session:
        yield session


async def verify_token(token: str) -> dict:
    async with AsyncClient() as client:
        headers = {"Authorization": f"Bearer {token}"}
        response = await client.get(AUTH_SERVICE_URL, headers=headers)
        if response.status_code != 200 or not response.json().get("valid"):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
        return response.json()


async def verify_user_role(user_id: int):
    async with AsyncClient() as client:
        response = await client.get(f"{ACCOUNT_SERVICE_URL}{user_id}")
        if response.status_code != 200 or response.json().get("role") != "user":
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid pacient role")


async def doctor_or_owner_required(
    history_id: int,
    token: dict = Depends(verify_token),
    session: Session = Depends(get_session)
):
    statement = select(History).where(History.id == history_id)
    result = await session.execute(statement)
    history = result.scalars().first()

    if not history or (token["role"] != "doctor" and token["user_id"] != history.pacient_id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

async def admin_or_medical_required(token: dict = Depends(verify_token)):
    if token["role"] not in ["admin", "manager", "doctor"]:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")



@app.get("/api/History/Account/{id}", response_model=List[History])
async def get_history_by_account(
    id: int,
    session: Session = Depends(get_session),
    token: dict = Depends(verify_token)
):
    statement = select(History).where(History.pacient_id == id)
    result = await session.execute(statement)
    return result.scalars().all()

@app.get("/api/History/{id}", response_model=History)
async def get_history_details(
    id: int,
    session: Session = Depends(get_session),
    token: dict = Depends(doctor_or_owner_required)
):
    history = await session.get(History, id)
    if not history:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="History not found")
    return history

@app.post("/api/History", response_model=History, status_code=status.HTTP_201_CREATED)
async def create_history(
    history: HistoryCreate,
    session: Session = Depends(get_session),
    token: dict = Depends(admin_or_medical_required)
):
    await verify_user_role(history.pacient_id)
    new_history = History(**history.dict())
    session.add(new_history)
    await session.commit()
    await session.refresh(new_history)
    return new_history

@app.put("/api/History/{id}", response_model=History)
async def update_history(
    id: int,
    updated_history: HistoryUpdate,
    session: Session = Depends(get_session),
    token: dict = Depends(admin_or_medical_required)
):
    history = await session.get(History, id)
    if not history:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="History not found")

    for key, value in updated_history.dict().items():
        setattr(history, key, value)

    await session.commit()
    await session.refresh(history)
    return history
