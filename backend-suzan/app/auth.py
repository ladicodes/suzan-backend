from fastapi import APIRouter, HTTPException, Depends
from sqlmodel import Session, select
from .db import engine
from .models import User
from .schema import UserCreate, UserLogin, UserResponse
from datetime import datetime

router = APIRouter()

@router.post("/signup", response_model=UserResponse)
def signup(user_data: UserCreate):
    # Validation
    if not user_data.phone_number.startswith("+234"):
         raise HTTPException(status_code=400, detail="Phone number must start with +234")

    with Session(engine) as session:
        # Check if user exists
        existing_user = session.exec(select(User).where(
            User.phone_number == user_data.phone_number
        )).first()

        if existing_user:
            raise HTTPException(status_code=409, detail="User with this number already exists")

        # Create User
        new_user = User(
            business_name=user_data.business_name,
            phone_number=user_data.phone_number,
            password_hash=user_data.password, # Note: using password_hash to match models.py
            bot_name="Suzan"
        )
        session.add(new_user)
        session.commit()
        session.refresh(new_user)
        
        # Return User + Token
        return {
            "id": new_user.id,
            "business_name": new_user.business_name,
            "phone_number": new_user.phone_number,
            "access_token": f"mock-token-{new_user.id}", # Temporary token
            "token_type": "bearer"
        }

@router.post("/login", response_model=UserResponse)
def login(login_data: UserLogin):
    if not login_data.phone_number.startswith("+234"):
         raise HTTPException(status_code=400, detail="Phone number must start with +234")

    with Session(engine) as session:
        # Find User
        user = session.exec(select(User).where(User.phone_number == login_data.phone_number)).first()

        # Verify Password (Simple check for now)
        if not user or user.password_hash != login_data.password:
             raise HTTPException(status_code=401, detail="Invalid credentials")

        # Return User + Token
        return {
            "id": user.id,
            "business_name": user.business_name,
            "phone_number": user.phone_number,
            "access_token": f"mock-token-{user.id}", # Temporary token
            "token_type": "bearer"
        }