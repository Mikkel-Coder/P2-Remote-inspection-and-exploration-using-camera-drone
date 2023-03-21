#https://fastapi.tiangolo.com/tutorial/security/oauth2-jwt/
#uvicorn main:app --reload
#pip install "python-jose[cryptography]"
#pip install "passlib[bcrypt]"
from datetime import datetime, timedelta
from fastapi import Depends, FastAPI, HTTPException, status, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from jose import JWTError, jwt #jwt & pyjwt
from passlib.context import CryptContext
from pydantic import BaseModel
import time

SECRET_KEY = "DuJwTmBr35qLU7HHqg2AMG+jkmx92JZk" #https://cloud.google.com/network-connectivity/docs/vpn/how-to/generating-pre-shared-key

fake_users_db = { #TODO: Use MongoDB
    "admin": {
        "username": "admin",
        "hashed_password": "$2b$12$mE3KlrNxXcdb7Hn4g3Je2ulIcXwQj/vhLa8ez412aojaSJGf/5VIG", #123
        "disabled": False,
    }
}

class Token(BaseModel):
    access_token: str
    token_type: str

class TokenData(BaseModel):
    username: str | None = None
    
class User(BaseModel):
    username: str
    disabled: bool | None = None

class UserInDB(User):
    hashed_password: str


pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
#pwd_context.hash("password")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")

app = FastAPI()

origins = [ # Which request the API will allow
    "http://localhost",
    "http://localhost:3000",
    "http://192.168.1.142:3000",
    "http://172.26.50.10:3000"
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"]
)

@app.get("/")
def handle(request: Request = None):
    #NOTE: PERMANENT REDIRECT to "/login" if user not authorized
    ...

@app.get('/v1/auth/protected')
def handle(request: Request = None):
    ...

@app.post('/v1/auth/register')
def handle(request: Request = None):
    #NOTE: PERMANENT REDIRECT to "/login" after user has signed up
    ...

@app.post("/v1/auth/logout")
async def handle(request: Request = None):
    request = await request.json()
    token = request.get("access_token")

    # Validate token
    if not is_user_authorized(token):
        raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Not Authorized",
                headers={"WWW-Authenticate": "Bearer"}
        )
    
    # Client-side deletes the token from the cookie.
    return { "message": "OK" }
        

@app.post("/v1/auth/login", response_model=Token)
async def handle(request: Request = None):
        request = await request.json()
        token = request.get("access_token")
        
        # Is the user authorized? (is the token valid)
        if is_user_authorized(token):
            # Generate new token to user? Or update token with new datetime exp?
            raise HTTPException(
                status_code=status.HTTP_307_TEMPORARY_REDIRECT,
                detail="/",
                headers={"WWW-Authenticate": "Bearer"}
            )

        user = authenticate_user(request.get("username"), request.get("password"))
        
        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Incorrect username or password",
                headers={"WWW-Authenticate": "Bearer"}
            )

        # Generate new HS256 access token
        token = generate_access_token(data={"sub": user.username})
        return {"access_token": token, "token_type": "bearer"}

def verify_password(plain_password, hashed_password):
    return pwd_context.verify(plain_password, hashed_password)

def get_user(db, username: str):
    if username in db:
        user_dict = db[username]
        return UserInDB(**user_dict)

def authenticate_user(username: str, password: str):
    fake_db = fake_users_db
    user = get_user(fake_db, username)
    if not user:
        return False
    if not verify_password(password, user.hashed_password):
        return False
    return user

def is_user_authorized(access_token: str):
    try:
        # Decode access token
        payload = decode_access_token(access_token)

        # Decode username from payload
        username = payload.get('sub')

        if username is None:
            return False
        return True
    except JWTError:
        return False

def generate_access_token(data: dict):
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(minutes=30)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm="HS256")
    return encoded_jwt

def decode_access_token(encoded_jwt: str):
    return jwt.decode(encoded_jwt, SECRET_KEY, algorithms=["HS256"])