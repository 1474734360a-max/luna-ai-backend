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
    voice_enabled = Column(Boolean, default=False)
    plus_expires_at = Column(DateTime, nullable=True)
    images_used_today = Column(Integer, default=0)
    images_reset_at = Column(DateTime, default=datetime.utcnow)
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
    # migrate old SQLite databases (columns added after first release)
    if "sqlite" in DATABASE_URL:
        from sqlalchemy import text
        with engine.connect() as conn:
            for stmt in [
                "ALTER TABLE users ADD COLUMN voice_enabled BOOLEAN DEFAULT 0",
                "ALTER TABLE users ADD COLUMN plus_expires_at DATETIME",
                "ALTER TABLE users ADD COLUMN images_used_today INTEGER DEFAULT 0",
                "ALTER TABLE users ADD COLUMN images_reset_at DATETIME",
            ]:
                try:
                    conn.execute(text(stmt))
                    conn.commit()
                except Exception:
                    pass  # column already exists
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
                    "max_tokens": 800
                }
            )
            
            if response.status_code == 200:
                data = response.json()
                msg = data["choices"][0]["message"]
                content = (msg.get("content") or "").strip()
                if not content and msg.get("reasoning_content"):
                    # reasoning model spent all tokens thinking - retry once with a nudge
                    logger.warning("Empty content (reasoning consumed tokens), retrying")
                    retry = await client.post(
                        "https://api.deepseek.com/chat/completions",
                        headers={
                            "Content-Type": "application/json",
                            "Authorization": f"Bearer {deepseek_key}"
                        },
                        json={
                            "model": "deepseek-v4-flash",
                            "messages": messages + [{"role": "user", "content": "(请直接用一两句话回答，不要思考过程)"}],
                            "temperature": 0.8,
                            "max_tokens": 800
                        }
                    )
                    if retry.status_code == 200:
                        content = (retry.json()["choices"][0]["message"].get("content") or "").strip()
                if not content:
                    logger.error(f"DeepSeek returned empty content twice: {json.dumps(data)[:200]}")
                return content or ""
            else:
                logger.error(f"DeepSeek error: {response.status_code} {response.text}")
                return ""
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
    
    # Check daily limit (Plus members unlimited)
    now = datetime.utcnow()
    if now - user.daily_reset_at > timedelta(days=1):
        user.daily_messages_used = 0
        user.daily_reset_at = now
        db.commit()
    
    if not is_plus(user) and user.daily_messages_used >= 3:
        return {"error": "Daily limit reached (3/day free). /plus to unlock unlimited!", "remaining": 0}
    
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

@app.get("/tgtest")
async def tgtest():
    """TEMP debug: send a real message and return Telegram's raw response"""
    async with httpx.AsyncClient() as c:
        r = await c.post(f"{TELEGRAM_API_URL}/sendMessage",
                         json={"chat_id": 2023780638, "text": "backend debug test"})
        return {"status": r.status_code, "body": r.text[:400],
                "token_prefix": (TELEGRAM_BOT_TOKEN or "NONE")[:12]}

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
    mark_vip(user, payload.username, db)
    
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
        r = await client.post(
            f"{TELEGRAM_API_URL}/sendMessage",
            json={"chat_id": chat_id, "text": text}
        )
        if r.status_code != 200:
            logger.error(f"sendMessage FAILED {r.status_code} to {chat_id}: {r.text[:300]} | text[:80]={repr(text[:80])}")
        return r

PLUS_PRICE_STARS = 150  # ~¥15/month

# VIP 白名单: 这些用户免订阅直接享受 Plus 待遇 (永久)
VIP_USERNAMES = {"wengui26"}
try:
    VIP_USERNAMES |= {u.strip().lstrip("@").lower() for u in os.getenv("VIP_USERS", "").split(",") if u.strip()}
except Exception:
    pass

def mark_vip(user, username: str | None, db) -> bool:
    """If the user is on the VIP list, grant permanent Plus. Returns True if VIP."""
    if username and username.lower() in VIP_USERNAMES and not is_plus(user):
        user.plus_expires_at = datetime(2099, 1, 1)
        db.commit()
        logger.info(f"VIP access granted to @{username} (tg {user.tg_id})")
        return True
    return False

def is_plus(user) -> bool:
    return bool(user.plus_expires_at and user.plus_expires_at > datetime.utcnow())

def reset_image_quota_if_needed(user, db):
    now = datetime.utcnow()
    if now - (user.images_reset_at or now) > timedelta(days=1):
        user.images_used_today = 0
        user.images_reset_at = now
        db.commit()

async def send_telegram_photo(chat_id: int, photo_bytes: bytes, caption: str = ""):
    async with httpx.AsyncClient(timeout=90.0) as client:
        await client.post(
            f"{TELEGRAM_API_URL}/sendPhoto",
            data={"chat_id": str(chat_id), "caption": caption[:1000]},
            files={"photo": ("image.jpg", photo_bytes, "image/jpeg")}
        )

async def send_telegram_voice(chat_id: int, voice_bytes: bytes):
    async with httpx.AsyncClient(timeout=90.0) as client:
        r = await client.post(
            f"{TELEGRAM_API_URL}/sendVoice",
            data={"chat_id": str(chat_id)},
            files={"voice": ("voice.mp3", voice_bytes, "audio/mpeg")}
        )
        if r.status_code != 200:
            logger.error(f"sendVoice FAILED {r.status_code} to {chat_id}: {r.text[:200]}")

# ===== Image generation (Pollinations/Flux, free; swap to Replicate later) =====
async def generate_image(prompt: str) -> bytes | None:
    try:
        import urllib.parse
        url = "https://image.pollinations.ai/prompt/" + urllib.parse.quote(
            f"photorealistic portrait, {prompt}, detailed, soft lighting", safe="")
        async with httpx.AsyncClient(timeout=120.0) as client:
            r = await client.get(url, params={"width": 768, "height": 1024, "nologo": "true"})
            if r.status_code == 200 and len(r.content) > 5000:
                return r.content
            logger.error(f"Image gen failed: {r.status_code} len={len(r.content)}")
            return None
    except Exception as e:
        logger.error(f"Image gen error: {e}")
        return None

# ===== Voice synthesis (Edge TTS, free) =====
EDGE_VOICES = {
    "zh": {"veronika": ("zh-CN-XiaoyiNeural", "+10%", "+2Hz"),
           "karina":   ("zh-CN-XiaoxiaoNeural", "-8%", "-4Hz"),
           "alina":    ("zh-CN-XiaoxiaoNeural", "+2%", "+1Hz"),
           "katya":    ("zh-CN-XiaoyiNeural", "+6%", "+6Hz")},
    "en": {"veronika": ("en-US-AnaNeural", "+8%", "+2Hz"),
           "karina":   ("en-US-AriaNeural", "-6%", "-4Hz"),
           "alina":    ("en-US-JennyNeural", "+2%", "+0Hz"),
           "katya":    ("en-US-AvaNeural", "+5%", "+6Hz")},
}
VOICE_FALLBACK = {"ja": "ja-JP-NanamiNeural", "ko": "ko-KR-SunHiNeural"}

def detect_reply_language(text: str) -> str:
    if any('\u3040' <= c <= '\u30ff' for c in text): return "ja"
    if any('\uac00' <= c <= '\ud7af' for c in text): return "ko"
    if any('\u4e00' <= c <= '\u9fff' for c in text): return "zh"
    return "en"

async def generate_voice(text: str, character_name: str) -> bytes | None:
    try:
        import asyncio
        import edge_tts
        lang = detect_reply_language(text)
        key = character_name.lower()
        if lang in EDGE_VOICES and key in EDGE_VOICES[lang]:
            voice, rate, pitch = EDGE_VOICES[lang][key]
        else:
            voice = VOICE_FALLBACK.get(lang, "en-US-AvaNeural"); rate, pitch = "+2%", "+0Hz"

        async def _synth():
            communicate = edge_tts.Communicate(text, voice, rate=rate, pitch=pitch)
            chunks = []
            async for chunk in communicate.stream():
                if chunk["type"] == "audio":
                    chunks.append(chunk["data"])
            return b"".join(chunks) if chunks else None

        # hard 30s cap so a stuck TTS connection can never hang the bot
        return await asyncio.wait_for(_synth(), timeout=30.0)
    except asyncio.TimeoutError:
        logger.error("Voice gen timed out after 30s")
        return None
    except Exception as e:
        logger.error(f"Voice gen error: {e}")
        return None

# Background: heavy chat processing after webhook returns immediately
async def process_and_reply(tg_id: int, character_id: int, text: str):
    db = SessionLocal()
    try:
        user = db.query(UserDB).filter(UserDB.tg_id == tg_id).first()
        character = db.query(CharacterDB).filter(CharacterDB.id == character_id).first()
        result = await process_user_message(tg_id, character_id, text, db)
        if "error" in result:
            await send_telegram_message(tg_id, f"⚠️ {result['error']}")
            return
        reply = result["reply"]["content"]
        if not reply.strip():
            reply = "*她眨了眨眼，好像走神了* ……嗯？你刚才说什么？再说一遍好不好？"
        await send_telegram_message(tg_id, reply)
        if user and user.voice_enabled and character:
            audio = await generate_voice(reply, character.name)
            if audio:
                await send_telegram_voice(tg_id, audio)
    except Exception as e:
        logger.error(f"background reply error: {e}")
    finally:
        db.close()

@app.post("/webhook/telegram")
async def telegram_webhook(request: Request, db: Session = Depends(get_db)):
    """Handle incoming Telegram messages (raw dict parsing - avoids pydantic 'from' alias issues)"""
    try:
        data = await request.json()

        # ---- Telegram Stars payment: pre-checkout ----
        pcq = data.get("pre_checkout_query")
        if pcq:
            async with httpx.AsyncClient() as client:
                await client.post(f"{TELEGRAM_API_URL}/answerPreCheckoutQuery",
                                  json={"pre_checkout_query_id": pcq["id"], "ok": True})
            return {"ok": True}

        msg = data.get("message") or {}
        frm = msg.get("from") or {}
        tg_id = frm.get("id")

        # ---- Successful payment → activate Plus ----
        sp = msg.get("successful_payment")
        if tg_id and sp:
            user = db.query(UserDB).filter(UserDB.tg_id == tg_id).first()
            if not user:
                user = UserDB(tg_id=tg_id, username=frm.get("username"),
                              first_name=frm.get("first_name"), language="zh")
                db.add(user)
            base = user.plus_expires_at if (user.plus_expires_at and user.plus_expires_at > datetime.utcnow()) else datetime.utcnow()
            user.plus_expires_at = base + timedelta(days=30)
            db.commit()
            logger.info(f"Plus activated for {tg_id}: {user.plus_expires_at}")
            await send_telegram_message(tg_id, "👑 Luna Plus 已开通（30 天）！\n\n✅ 无限聊天\n✅ 无限图片生成\n✅ 语音回复\n\n祝你玩得开心~")
            return {"ok": True}

        text = msg.get("text")
        username = frm.get("username")

        if not tg_id or not text:
            return {"ok": True}

        logger.info(f"Telegram message from {tg_id} ({username}): {text[:50]}")

        # Auto-register user
        user = db.query(UserDB).filter(UserDB.tg_id == tg_id).first()
        if not user:
            user = UserDB(tg_id=tg_id, username=username, first_name=frm.get("first_name"), language="zh")
            db.add(user)
            db.commit()
        mark_vip(user, username, db)

        # Handle /start command
        if text.startswith("/start"):
            await send_telegram_message(tg_id,
                "🧚‍♀️ Welcome to Luna AI!\n\n"
                "Choose a character to chat with:\n"
                "1. /veronika\n2. /karina\n3. /alina\n4. /katya\n\n"
                "📸 /imagine <描述> — generate a photo\n"
                "🎙 /voice — toggle voice replies\n"
                "👑 /plus — unlock unlimited (Stars)\n"
                "ℹ️ /status — your usage\n\n"
                "Then just send any message and she will reply 💬")
            return {"ok": True}

        # /help
        if text.startswith("/help"):
            await send_telegram_message(tg_id,
                "📖 Luna AI 命令:\n\n"
                "/veronika /karina /alina /katya — 选择角色\n"
                "/imagine <描述> — 生成照片 (免费3张/天)\n"
                "/voice — 开关语音回复\n"
                "/status — 查看额度\n"
                "/plus — 开通 Plus (150 Stars/月)\n\n"
                "免费版: 3条消息+3张图/天 | Plus: 无限")
            return {"ok": True}

        # /status
        if text.startswith("/status"):
            reset_image_quota_if_needed(user, db)
            now = datetime.utcnow()
            if now - user.daily_reset_at > timedelta(days=1):
                user.daily_messages_used = 0; user.daily_reset_at = now; db.commit()
            plus = is_plus(user)
            await send_telegram_message(tg_id,
                f"📊 你的状态\n\n"
                f"👑 Plus: {'✅ 至 ' + user.plus_expires_at.strftime('%Y-%m-%d') if plus else '未开通'}\n"
                f"💬 今日消息: {user.daily_messages_used}/{'∞' if plus else '3'}\n"
                f"📸 今日图片: {user.images_used_today}/{'∞' if plus else '3'}\n"
                f"🎙 语音回复: {'开' if user.voice_enabled else '关'}")
            return {"ok": True}

        # /voice toggle
        if text.startswith("/voice"):
            user.voice_enabled = not user.voice_enabled
            db.commit()
            await send_telegram_message(tg_id,
                f"🎙 语音回复已{'开启，她的每条回复都会附带语音' if user.voice_enabled else '关闭'}")
            return {"ok": True}

        # /plus
        if text.startswith("/plus"):
            if is_plus(user):
                await send_telegram_message(tg_id, f"👑 你已经是 Plus（至 {user.plus_expires_at.strftime('%Y-%m-%d')}）")
                return {"ok": True}
            async with httpx.AsyncClient(timeout=30.0) as client:
                r = await client.post(f"{TELEGRAM_API_URL}/sendInvoice", json={
                    "chat_id": tg_id,
                    "title": "Luna Plus (30 days)",
                    "description": "无限聊天 + 无限图片生成 + 语音回复",
                    "payload": "plus_30d",
                    "currency": "XTR",
                    "prices": [{"label": "Luna Plus", "amount": PLUS_PRICE_STARS}]
                })
                logger.info(f"sendInvoice: {r.status_code} {r.text[:120]}")
            return {"ok": True}

        # /imagine <prompt>
        if text.startswith("/imagine"):
            prompt = text.replace("/imagine", "").strip()
            if not prompt:
                await send_telegram_message(tg_id, "用法: /imagine 一个红裙子的女孩在咖啡馆\n(或: /imagine a girl in red dress)")
                return {"ok": True}
            reset_image_quota_if_needed(user, db)
            if not is_plus(user) and user.images_used_today >= 3:
                await send_telegram_message(tg_id, "📸 今日 3 张免费图片已用完。\n👑 /plus 解锁无限生成")
                return {"ok": True}
            await send_telegram_message(tg_id, "🎨 正在生成，请等 10-30 秒...")
            img = await generate_image(prompt)
            if img:
                user.images_used_today += 1
                db.commit()
                await send_telegram_photo(tg_id, img, caption=f"🎨 {prompt[:200]}")
            else:
                await send_telegram_message(tg_id, "😔 生成失败了，换一个描述试试？")
            return {"ok": True}

        # Handle character selection commands
        character_map = {"veronika": 1, "karina": 2, "alina": 3, "katya": 4}
        cmd = text.lstrip("/").split("@")[0].lower()
        if cmd in character_map:
            character_id = character_map[cmd]
            character = db.query(CharacterDB).filter(CharacterDB.id == character_id).first()
            if character:
                chat = db.query(ChatDB).filter(
                    ChatDB.tg_id == tg_id, ChatDB.character_id == character_id).first()
                if not chat:
                    chat = ChatDB(tg_id=tg_id, character_id=character_id)
                    db.add(chat)
                    db.commit()
                await send_telegram_message(tg_id, f"👋 You're now chatting with {character.name}.\nSay anything!")
            return {"ok": True}

        # Use the character the user last chatted with, default Veronika
        last_chat = db.query(ChatDB).filter(ChatDB.tg_id == tg_id).order_by(ChatDB.created_at.desc()).first()
        character_id = last_chat.character_id if last_chat else 1

        # Process in background so the webhook returns 200 immediately (avoids Telegram 502 on slow AI/voice)
        import asyncio
        asyncio.create_task(process_and_reply(tg_id, character_id, text))

        return {"ok": True}

    except Exception as e:
        logger.error(f"Webhook error: {e}")
        return {"ok": True}

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
