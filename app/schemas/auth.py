from pydantic import BaseModel, EmailStr, Field


class RegisterIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    business_name: str | None = Field(default=None, max_length=160)


class LoginIn(BaseModel):
    email: EmailStr
    password: str


class AccessTokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"


class ProfileUpdateIn(BaseModel):
    business_name: str | None = Field(default=None, max_length=160)
    current_password: str | None = None
    new_password: str | None = Field(
        default=None, min_length=8, max_length=128
    )
