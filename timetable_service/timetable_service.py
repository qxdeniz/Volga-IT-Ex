from fastapi import FastAPI, Depends, HTTPException, status, Query, Path
from sqlmodel import SQLModel, Field, create_engine, Session, select
from typing import List, Optional
from datetime import datetime, timedelta
from httpx import AsyncClient
from contextlib import asynccontextmanager


DATABASE_URL = 'postgresql+asyncpg://user:password@db:5432/timetable_db'
AUTH_SERVICE_URL = 'http://localhost:8081/api/Authentication/Validate'
HOSPITAL_SERVICE_URL = 'http://localhost:8082/api/Hospitals/'

engine = create_engine(DATABASE_URL, echo=True, future=True)

class Timetable(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    hospital_id: int
    doctor_id: int
    room: str
    from_time: datetime = Field(..., alias="from")
    to_time: datetime = Field(..., alias="to")

class Appointment(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    timetable_id: int
    patient_id: int
    time: datetime

class TimetableCreate(SQLModel):
    hospital_id: int
    doctor_id: int
    room: str
    from_time: datetime
    to_time: datetime

class AppointmentCreate(SQLModel):
    time: datetime



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

async def hospital_exists(hospital_id: int):
    async with AsyncClient() as client:
        response = await client.get(f"{HOSPITAL_SERVICE_URL}{hospital_id}")
        if response.status_code != 200:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Hospital not found")

async def admin_or_manager_required(token: dict = Depends(verify_token)):
    if token.get("role") not in ["admin", "manager"]:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only admins or managers allowed")


def validate_time_range(from_time: datetime, to_time: datetime):
    if to_time <= from_time:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="'to' must be after 'from'")
    if (to_time - from_time).total_seconds() > 12 * 3600:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Duration cannot exceed 12 hours")
    if from_time.minute % 30 != 0 or to_time.minute % 30 != 0 or from_time.second != 0 or to_time.second != 0:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Minutes must be a multiple of 30")


@app.post("/api/Timetable", response_model=Timetable, status_code=status.HTTP_201_CREATED)
async def create_timetable(
    timetable: TimetableCreate,
    session: Session = Depends(get_session),
    token: dict = Depends(admin_or_manager_required)
):
    validate_time_range(timetable.from_time, timetable.to_time)
    await hospital_exists(timetable.hospital_id)

    new_timetable = Timetable(**timetable.dict())
    session.add(new_timetable)
    await session.commit()
    await session.refresh(new_timetable)
    return new_timetable

@app.put("/api/Timetable/{id}", response_model=Timetable)
async def update_timetable(
    id: int,
    timetable: TimetableCreate,
    session: Session = Depends(get_session),
    token: dict = Depends(admin_or_manager_required)
):
    validate_time_range(timetable.from_time, timetable.to_time)
    existing_timetable = await session.get(Timetable, id)
    if not existing_timetable:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Timetable not found")

    for key, value in timetable.dict().items():
        setattr(existing_timetable, key, value)

    await session.commit()
    await session.refresh(existing_timetable)
    return existing_timetable

@app.delete("/api/Timetable/{id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_timetable(
    id: int,
    session: Session = Depends(get_session),
    token: dict = Depends(admin_or_manager_required)
):
    timetable = await session.get(Timetable, id)
    if not timetable:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Timetable not found")

    await session.delete(timetable)
    await session.commit()

@app.get("/api/Timetable/Hospital/{id}", response_model=List[Timetable])
async def get_timetable_for_hospital(
    id: int,
    from_time: datetime,
    to_time: datetime,
    session: Session = Depends(get_session),
    token: dict = Depends(verify_token)
):
    statement = select(Timetable).where(
        Timetable.hospital_id == id,
        Timetable.from_time >= from_time,
        Timetable.to_time <= to_time
    )
    result = await session.execute(statement)
    return result.scalars().all()
