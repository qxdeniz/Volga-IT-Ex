from fastapi import FastAPI, Depends, HTTPException, status, Query
from sqlmodel import SQLModel, Field, create_engine, Session, select
from typing import List, Optional
from httpx import AsyncClient
import asyncio

from contextlib import asynccontextmanager


DATABASE_URL = 'postgresql+asyncpg://user:password@db:5432/hospital_db'
AUTH_SERVICE_URL = 'http://localhost:8081/api/Authentication/Validate'
ACCOUNT_SERVICE_URL = 'http://localhost:8081/api/Accounts/'
HOSPITAL_SERVICE_URL = 'http://localhost:8082/api/Hospitals/'


engine = create_engine(DATABASE_URL, echo=True, future=True)


class Room(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    hospital_id: Optional[int] = Field(default=None, foreign_key="hospital.id")

class Hospital(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    address: str
    contact_phone: str
    rooms: List[Room] = []


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


async def admin_required(token: dict = Depends(verify_token)):
    if token.get("role") != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only admins can perform this action")



@app.get("/api/Hospitals", response_model=List[Hospital])
async def get_hospitals(
    from_: int = Query(0, alias="from"),
    count: int = Query(10),
    session: Session = Depends(get_session),
    token: dict = Depends(verify_token)
):
    statement = select(Hospital).offset(from_).limit(count)
    result = await session.execute(statement)
    hospitals = result.scalars().all()
    return hospitals

@app.get("/api/Hospitals/{id}", response_model=Hospital)
async def get_hospital(
    id: int,
    session: Session = Depends(get_session),
    token: dict = Depends(verify_token)
):
    hospital = await session.get(Hospital, id)
    if not hospital:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Hospital not found")
    return hospital

@app.get("/api/Hospitals/{id}/Rooms", response_model=List[Room])
async def get_hospital_rooms(
    id: int,
    session: Session = Depends(get_session),
    token: dict = Depends(verify_token)
):
    statement = select(Room).where(Room.hospital_id == id)
    result = await session.execute(statement)
    rooms = result.scalars().all()
    return rooms

@app.post("/api/Hospitals", response_model=Hospital, status_code=status.HTTP_201_CREATED)
async def create_hospital(
    hospital: Hospital,
    session: Session = Depends(get_session),
    token: dict = Depends(admin_required)
):
    session.add(hospital)
    await session.commit()
    await session.refresh(hospital)
    return hospital

@app.put("/api/Hospitals/{id}", response_model=Hospital)
async def update_hospital(
    id: int,
    updated_hospital: Hospital,
    session: Session = Depends(get_session),
    token: dict = Depends(admin_required)
):
    hospital = await session.get(Hospital, id)
    if not hospital:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Hospital not found")

    hospital.name = updated_hospital.name
    hospital.address = updated_hospital.address
    hospital.contact_phone = updated_hospital.contact_phone
    await session.commit()
    return hospital

@app.delete("/api/Hospitals/{id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_hospital(
    id: int,
    session: Session = Depends(get_session),
    token: dict = Depends(admin_required)
):
    hospital = await session.get(Hospital, id)
    if not hospital:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Hospital not found")

    await session.delete(hospital)
    await session.commit()
