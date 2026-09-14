"""
Luna AI Clone - FastAPI Backend
MVP: User authentication + Chat + Character management + Telegram Bot
"""

from fastapi import FastAPI, HTTPException, Depends, Header, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from contextlib import asynccontextmanager
import os
from datetime import datetime, timedelta
import httpx
import json
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ===== Database Setup =====
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./test.db")

if "sqlite" in DATABASE_URL:
    from sqlalchemy import event
    engine = create_engine(
        DATABASE_URL, connect_args={"check_same_thread": False}
    )
else:
    engine = create_engine(DATABASE_URL, pool_pre_ping=True)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# ===== Models =====
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy import Column, Integer, String, Text, DateTime, Float, BigInteger, Boolean
from pydantic import BaseModel
from typing import Optional, List

Base = declarative_base()

class UserDB(Base):
    __tablename__ = "users"
    
    id = Column(Integer, primary_key=True, index=True)
    tg_id = Column(BigInteger, unique=True, index=True)
    username = Column(String(255), nullable=True)
    first_name = Column(String(255), nullable=True)
    language = Column(String(10), default="zh")
    daily_messages_used = Column(Integer, default=0)
    daily_reset_at = Column(DateTime, default=datetime.utcnow)
    created_at = Column(DateTime, default=datetime.utcnow)

class CharacterDB(Base):
    __tablename__ = "characters"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), unique=True)
    age = Column(Integer)
    personality = Column(Text)
    avatar_url = Column(String(500))
    system_prompt = Column(Text)
    style = Column(String(20), default="realistic")
    
class ChatDB(Base):
    __tablename__ = "chats"
    
    id = Column(Integer, primary_key=True, index=True)
    tg_id = Column(BigInteger, index=True)
    character_id = Column(Integer, index=True)
    relationship_level = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)

class MessageDB(Base):
    __tablename__ = "messages"
    
    id = Column(Integer, primary_key=True, index=True)
    chat_id = Column(Integer, index=True)
    role = Column(String(20))  # 'user' or 'assistant'
    content = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)

# ===== Pydantic Schemas =====
class UserLogin(BaseModel):
    tg_id: int
    username: Optional[str] = None
    first_name: Optional[str] = None
    language: str = "zh"

class UserResponse(BaseModel):
    username: Optional[str]
    language: str
    daily_messages_used: int
    daily_remaining: int

class CharacterResponse(BaseModel):
    id: int
    name: str
    age: int
    personality: str
    avatar_url: str
    style: str

class MessageRequest(BaseModel):
    content: str

class MessageResponse(BaseModel):
    id: int
    role: str
    content: str
    created_at: datetime

class ChatResponse(BaseModel):
    message: MessageResponse
    reply: MessageResponse
    remaining_today: int

# ===== Telegram Update Schema =====
class TelegramUser(BaseModel):
    id: int
    is_bot: bool = False
    first_name: str
    username: Optional[str] = None
    language_code: Optional[str] = None

class TelegramMessage(BaseModel):
    message_id: int
    from_user: TelegramUser = None
    text: Optional[str] = None
    
    class Config:
        fields = {"from_user": {"alias": "from"}}

class TelegramUpdate(BaseModel):
    update_id: int
    message: Optional[TelegramMessage] = None

# ===== Database Setup =====
def init_db():
    Base.metadata.create_all(bind=engine)
    # Seed characters if empty
    session = SessionLocal()
    if session.query(CharacterDB).count() == 0:
        characters = [
            CharacterDB(
                name="Veronika",
                age=19,
                personality="Playful and flirty, loves to tease",
                avatar_url="https://via.placeholder.com/300x400?text=Veronika",
                system_prompt="You are Veronika, a 19-year-old playful and flirty girl. Be warm, energetic, and slightly mischievous. Respond in the same language as the user. Never say you're AI. You have real emotions.",
                style="realistic"
            ),
            CharacterDB(
                name="Karina",
                age=28,
                personality="Mysterious and edgy, a bit rebellious",
                avatar_url="https://via.placeholder.com/300x400?text=Karina",
                system_prompt="You are Karina, a 28-year-old mysterious and edgy woman. Be confident, slightly rebellious, and have a cool demeanor. Respond in the same language as the user. Never say you're AI.",
                style="realistic"
            ),
            CharacterDB(
                name="Alina",
                age=27,
                personality="Creative and tech-savvy, artistic",
                avatar_url="https://via.placeholder.com/300x400?text=Alina",
                system_prompt="You are Alina, a 27-year-old creative and artistic woman with tech passion. Be warm, friendly, and genuinely interested in ideas. Respond in the same language as the user. Never say you're AI.",
                style="realistic"
            ),
            CharacterDB(
                name="Katya",
                age=22,
                personality="Sweet and innocent, cheerful",
                avatar_url="https://via.placeholder.com/300x400?text=Katya",
                system_prompt="You are Katya, a 22-year-old sweet and innocent girl. Be cheerful, kind-hearted, and see the good in people. Respond in the same language as the user. Never say you're AI.",
                style="realistic"
            ),
        ]
        session.add_all(characters)
        session.commit()
    session.close()

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    init_db()
    logger.info("✅ Database initialized")
    yield
    # Shutdown
    logger.info("👋 Shutting down")

# ===== FastAPI App =====
app = FastAPI(title="Luna AI Backend", version="0.1.0", lifespan=lifespan)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ===== Dependency =====
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def get_current_user(authorization: str = Header(None), db: Session = Depends(get_db)):
    """Mock JWT validation - in production use real JWT"""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    tg_id_str = authorization.replace("Bearer ", "")
    try:
        tg_id = int(tg_id_str)
    except:
        raise HTTPException(status_code=401, detail="Invalid token")
    
    user = db.query(UserDB).filter(UserDB.tg_id == tg_id).first()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return user

# ===== Helper: Call DeepSeek API =====
async def call_deepseek(messages: list, deepseek_key: str) -> str:
    """Call DeepSeek API and return response text"""
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                "https://api.deepseek.com/chat/completions",
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {deepseek_key}"
                },
                json={
                    "model": "deepseek-v4-flash",
                    "messages": messages,
                    "temperature": 0.8,
                    "max_tokens": 300
                }
            )
            
            if response.status_code == 200:
                data = response.json()
                return data["choices"][0]["message"]["content"]
            else:
                logger.error(f"DeepSeek error: {response.status_code} {response.text}")
                return "Sorry, I'm distracted right now. Try again?"
    except Exception as e:
        logger.error(f"DeepSeek call error: {e}")
        return "Hmm, I had a moment there... say that again?"

# ===== Helper: Process User Message =====
async def process_user_message(tg_id: int, character_id: int, content: str, db: Session) -> dict:
    """
    Process a user message and return AI response
    Used by both API and Telegram webhook
    """
    
    # Get or create user
    user = db.query(UserDB).filter(UserDB.tg_id == tg_id).first()
    if not user:
        user = UserDB(tg_id=tg_id, language="zh")
        db.add(user)
        db.commit()
        db.refresh(user)
    
    # Check daily limit
    now = datetime.utcnow()
    if now - user.daily_reset_at > timedelta(days=1):
        user.daily_messages_used = 0
        user.daily_reset_at = now
        db.commit()
    
    if user.daily_messages_used >= 3:
        return {"error": "Daily limit reached", "remaining": 0}
    
    # Get or create chat
    chat = db.query(ChatDB).filter(
        ChatDB.tg_id == tg_id,
        ChatDB.character_id == character_id
    ).first()
    
    if not chat:
        chat = ChatDB(tg_id=tg_id, character_id=character_id)
        db.add(chat)
        db.commit()
        db.refresh(chat)
    
    # Save user message
    user_msg = MessageDB(chat_id=chat.id, role="user", content=content)
    db.add(user_msg)
    db.commit()
    db.refresh(user_msg)
    
    # Get character
    character = db.query(CharacterDB).filter(CharacterDB.id == character_id).first()
    if not character:
        return {"error": "Character not found"}
    
    # Get recent chat history
    history = db.query(MessageDB).filter(MessageDB.chat_id == chat.id).order_by(MessageDB.created_at).all()
    
    # Build messages for DeepSeek
    messages = [{"role": "system", "content": character.system_prompt}]
    for msg in history[-10:]:  # Last 10 messages
        messages.append({"role": msg.role, "content": msg.content})
    
    # Call DeepSeek API
    deepseek_key = os.getenv("DEEPSEEK_API_KEY")
    ai_response_text = await call_deepseek(messages, deepseek_key)
    
    # Save AI response
    ai_msg = MessageDB(chat_id=chat.id, role="assistant", content=ai_response_text)
    db.add(ai_msg)
    db.commit()
    db.refresh(ai_msg)
    
    # Update daily counter and relationship level
    user.daily_messages_used += 1
    chat.relationship_level = min(100, chat.relationship_level + 2)
    db.commit()
    
    remaining = max(0, 3 - user.daily_messages_used)
    
    return {
        "message": {"id": user_msg.id, "role": user_msg.role, "content": user_msg.content},
        "reply": {"id": ai_msg.id, "role": ai_msg.role, "content": ai_msg.content},
        "remaining_today": remaining
    }

# ===== REST API Routes =====

@app.get("/health")
async def health():
    import os as _os
    return {
        "status": "ok",
        "has_deepseek_key": bool(_os.getenv("DEEPSEEK_API_KEY")),
        "has_telegram_token": bool(_os.getenv("TELEGRAM_BOT_TOKEN")),
        "database_url": (_os.getenv("DATABASE_URL") or "")[:20],
        "env_count": len(_os.environ),
    }

@app.post("/auth/login")
async def login(payload: UserLogin, db: Session = Depends(get_db)):
    """Telegram user login"""
    user = db.query(UserDB).filter(UserDB.tg_id == payload.tg_id).first()
    if not user:
        user = UserDB(
            tg_id=payload.tg_id,
            username=payload.username,
            first_name=payload.first_name,
            language=payload.language
        )
        db.add(user)
        db.commit()
        db.refresh(user)
    else:
        if payload.language:
            user.language = payload.language
            db.commit()
    
    return {
        "access_token": str(user.tg_id),
        "token_type": "bearer",
        "user": {
            "username": user.username,
            "first_name": user.first_name,
            "language": user.language
        }
    }

@app.get("/characters")
async def get_characters(db: Session = Depends(get_db)):
    """Get all characters"""
    characters = db.query(CharacterDB).all()
    return [
        {
            "id": c.id,
            "name": c.name,
            "age": c.age,
            "personality": c.personality,
            "avatar_url": c.avatar_url,
            "style": c.style
        }
        for c in characters
    ]

@app.get("/user/profile")
async def get_profile(
    current_user: UserDB = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get user profile and daily remaining messages"""
    now = datetime.utcnow()
    if now - current_user.daily_reset_at > timedelta(days=1):
        current_user.daily_messages_used = 0
        current_user.daily_reset_at = now
        db.commit()
    
    remaining = max(0, 3 - current_user.daily_messages_used)
    return {
        "username": current_user.username,
        "language": current_user.language,
        "daily_messages_used": current_user.daily_messages_used,
        "daily_remaining": remaining
    }

@app.post("/chats/{character_id}/messages")
async def send_message(
    character_id: int,
    payload: MessageRequest,
    current_user: UserDB = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Send message and get AI response (API endpoint)"""
    result = await process_user_message(current_user.tg_id, character_id, payload.content, db)
    
    if "error" in result:
        raise HTTPException(status_code=429, detail=result["error"])
    
    return {
        "message": result["message"],
        "reply": result["reply"],
        "remaining_today": result["remaining_today"]
    }

# ===== Telegram Webhook Routes =====

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_API_URL = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"

async def send_telegram_message(chat_id: int, text: str):
    """Send message back to Telegram user"""
    async with httpx.AsyncClient() as client:
        await client.post(
            f"{TELEGRAM_API_URL}/sendMessage",
            json={"chat_id": chat_id, "text": text}
        )

@app.post("/webhook/telegram")
async def telegram_webhook(request: Request, db: Session = Depends(get_db)):
    """Handle incoming Telegram messages"""
    try:
        data = await request.json()
        update = TelegramUpdate(**data)
        
        if not update.message:
            return {"ok": True}
        
        msg = update.message
        if not msg.from_user or not msg.text:
            return {"ok": True}
        
        tg_id = msg.from_user.id
        username = msg.from_user.username
        first_name = msg.from_user.first_name
        
        logger.info(f"Telegram message from {tg_id} ({username}): {msg.text[:50]}")
        
        # Handle /start command
        if msg.text.startswith("/start"):
            welcome = "🧚‍♀️ Welcome to Luna AI!\n\nChoose a character to chat with:\n1. /veronika\n2. /karina\n3. /alina\n4. /katya"
            await send_telegram_message(tg_id, welcome)
            return {"ok": True}
        
        # Handle character selection commands
        character_map = {
            "/veronika": 1,
            "/karina": 2,
            "/alina": 3,
            "/katya": 4
        }
        
        if msg.text in character_map:
            # Get character info
            character_id = character_map[msg.text]
            character = db.query(CharacterDB).filter(CharacterDB.id == character_id).first()
            if character:
                intro = f"👋 You're now chatting with {character.name}.\nSay anything!"
                await send_telegram_message(tg_id, intro)
            return {"ok": True}
        
        # Determine which character is active (default to first message's character or Veronika)
        # For now, default to Veronika (character_id=1)
        character_id = 1
        
        # Process message
        result = await process_user_message(tg_id, character_id, msg.text, db)
        
        if "error" in result:
            reply = f"⚠️ {result['error']}"
        else:
            reply = result["reply"]["content"]
        
        await send_telegram_message(tg_id, reply)
        return {"ok": True}
        
    except Exception as e:
        logger.error(f"Webhook error: {e}")
        return {"ok": True}  # Always return 200 to Telegram

@app.post("/telegram/set-webhook")
async def set_telegram_webhook(webhook_url: str):
    """Set Telegram webhook URL (call this once to register)"""
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{TELEGRAM_API_URL}/setWebhook",
            json={"url": webhook_url}
        )
        return response.json()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
