"""Game Customer Service - Data Models"""
import datetime
from sqlalchemy import Column, Integer, String, Text, DateTime, Enum, ForeignKey, Float, Boolean
from sqlalchemy.orm import relationship
from database import Base
import enum


class TicketPriority(str, enum.Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    URGENT = "urgent"


class TicketStatus(str, enum.Enum):
    OPEN = "open"
    IN_PROGRESS = "in_progress"
    WAITING_PLAYER = "waiting_player"
    RESOLVED = "resolved"
    CLOSED = "closed"


class TicketCategory(str, enum.Enum):
    ACCOUNT = "account"
    PAYMENT = "payment"
    GAMEPLAY = "gameplay"
    BUG = "bug"
    REPORT = "report"
    OTHER = "other"


class Agent(Base):
    __tablename__ = "agents"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    email = Column(String(200), unique=True, nullable=False)
    role = Column(String(50), default="agent")  # agent, supervisor, admin
    avatar = Column(String(10), default="👤")
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    tickets = relationship("Ticket", back_populates="assigned_agent", foreign_keys="Ticket.assigned_to")


class Player(Base):
    __tablename__ = "players"

    id = Column(Integer, primary_key=True, index=True)
    player_id = Column(String(50), unique=True, index=True, nullable=False)
    nickname = Column(String(100), nullable=False)
    server = Column(String(50), default="S1")
    level = Column(Integer, default=1)
    vip_level = Column(Integer, default=0)
    total_recharge = Column(Float, default=0.0)
    register_date = Column(DateTime, default=datetime.datetime.utcnow)
    last_login = Column(DateTime, default=datetime.datetime.utcnow)
    status = Column(String(20), default="active")  # active, banned, frozen
    language = Column(String(10), default="zh-CN")  # Player language: zh-CN, pt-BR, en, es, etc.
    notes = Column(Text, default="")

    tickets = relationship("Ticket", back_populates="player")


class Ticket(Base):
    __tablename__ = "tickets"

    id = Column(Integer, primary_key=True, index=True)
    ticket_id = Column(String(20), unique=True, index=True, nullable=False)
    title = Column(String(200), nullable=False)
    description = Column(Text, nullable=False)
    category = Column(Enum(TicketCategory), default=TicketCategory.OTHER)
    priority = Column(Enum(TicketPriority), default=TicketPriority.MEDIUM)
    status = Column(Enum(TicketStatus), default=TicketStatus.OPEN)
    ai_mode = Column(Boolean, default=True)  # AI-assisted mode on/off

    player_id = Column(Integer, ForeignKey("players.id"))
    assigned_to = Column(Integer, ForeignKey("agents.id"), nullable=True)

    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)
    resolved_at = Column(DateTime, nullable=True)

    player = relationship("Player", back_populates="tickets")
    assigned_agent = relationship("Agent", back_populates="tickets", foreign_keys=[assigned_to])
    messages = relationship("TicketMessage", back_populates="ticket", order_by="TicketMessage.created_at", cascade="all, delete-orphan")


class TicketMessage(Base):
    __tablename__ = "ticket_messages"

    id = Column(Integer, primary_key=True, index=True)
    ticket_id = Column(Integer, ForeignKey("tickets.id"))
    sender_type = Column(String(20))  # agent, player, system
    sender_name = Column(String(100))
    content = Column(Text, nullable=False)
    # Multi-language support
    original_language = Column(String(10), default="zh-CN")  # Original message language
    translated_content = Column(Text, nullable=True)  # Auto-translated version
    is_ai_suggested = Column(Boolean, default=False)  # Whether AI suggested this reply
    is_internal = Column(Boolean, default=False)  # internal notes, not shown to player
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    ticket = relationship("Ticket", back_populates="messages")


class ApiKey(Base):
    __tablename__ = "api_keys"

    id = Column(Integer, primary_key=True, index=True)
    key = Column(String(64), unique=True, index=True, nullable=False)
    name = Column(String(100), nullable=False)
    website_url = Column(String(500), default="")
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)


class KnowledgeArticle(Base):
    __tablename__ = "knowledge_base"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(200), nullable=False)
    content = Column(Text, nullable=False)
    category = Column(String(50), default="general")
    tags = Column(String(500), default="")
    helpful_count = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)
