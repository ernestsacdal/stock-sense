from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr

from app.models.user import UserRole


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: EmailStr
    role: UserRole
    business_name: str | None = None
    created_at: datetime
