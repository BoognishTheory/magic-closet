from sqlalchemy import (
    Column, Integer, Text, Boolean, DateTime, ForeignKey, create_engine
)
from sqlalchemy.orm import declarative_base, relationship
from datetime import datetime

Base = declarative_base()


class Player(Base):
    __tablename__ = "players"

    id                      = Column(Integer, primary_key=True)
    discord_id              = Column(Text, unique=True, nullable=False)
    shop_level              = Column(Integer, default=1)
    xp                      = Column(Integer, default=0)
    coin                    = Column(Integer, default=0)
    cycle_start             = Column(DateTime, nullable=True)
    prep_complete           = Column(Boolean, default=False)
    shop_complete           = Column(Boolean, default=False)
    dungeon_complete        = Column(Boolean, default=False)
    daily_customers         = Column(Text, nullable=True)
    shop_name               = Column(Text, nullable=True)
    town_name               = Column(Text, nullable=True)
    name_last_changed_shop  = Column(DateTime, nullable=True)
    name_last_changed_town  = Column(DateTime, nullable=True)
    last_active             = Column(DateTime, nullable=True)
    created_at              = Column(DateTime, default=datetime.utcnow)
    debt                    = Column(Boolean, default=False)
    # Character progression
    char_level              = Column(Integer, default=1)
    char_xp                 = Column(Integer, default=0)
    combat_wins             = Column(Integer, default=0)
    social_wins             = Column(Integer, default=0)

    skill_points = relationship("SkillPoints", back_populates="player", uselist=False)
    bank_items   = relationship("BankItem",    back_populates="player")
    active_run   = relationship("ActiveRun",   back_populates="player", uselist=False)
    quests       = relationship("Quest",       back_populates="player")
    run_history  = relationship("RunHistory",  back_populates="player")


class SkillPoints(Base):
    __tablename__ = "skill_points"

    id              = Column(Integer, primary_key=True)
    player_id       = Column(Integer, ForeignKey("players.id"), nullable=False)
    unspent_points  = Column(Integer, default=0)
    keen_eye        = Column(Integer, default=0)
    smooth_talker   = Column(Integer, default=0)
    heavy_hauler    = Column(Integer, default=0)

    player = relationship("Player", back_populates="skill_points")


class BankItem(Base):
    __tablename__ = "bank_items"

    id          = Column(Integer, primary_key=True)
    player_id   = Column(Integer, ForeignKey("players.id"), nullable=False)
    item_id     = Column(Text, nullable=False)
    rarity      = Column(Text, nullable=False)
    on_floor    = Column(Boolean, default=False)
    acquired_at = Column(DateTime, default=datetime.utcnow)

    player = relationship("Player", back_populates="bank_items")


class ActiveRun(Base):
    __tablename__ = "active_runs"

    id              = Column(Integer, primary_key=True)
    player_id       = Column(Integer, ForeignKey("players.id"), nullable=False)
    dungeon_id      = Column(Text, nullable=False)
    strikes         = Column(Integer, default=0)
    nodes_completed = Column(Integer, default=0)
    node_sequence   = Column(Text)
    loot_this_run   = Column(Text)
    weapon_slot     = Column(Text)
    spell_slot      = Column(Text)
    item_slot       = Column(Text)
    started_at      = Column(DateTime, default=datetime.utcnow)

    player = relationship("Player", back_populates="active_run")


class Quest(Base):
    __tablename__ = "quests"

    id          = Column(Integer, primary_key=True)
    player_id   = Column(Integer, ForeignKey("players.id"), nullable=False)
    item_id     = Column(Text, nullable=False)
    dungeon_id  = Column(Text, nullable=False)
    day_count   = Column(Integer, default=0)
    week_number = Column(Integer, nullable=False)
    status      = Column(Text, default="active")
    created_at  = Column(DateTime, default=datetime.utcnow)

    player = relationship("Player", back_populates="quests")


class RunHistory(Base):
    __tablename__ = "run_history"

    id              = Column(Integer, primary_key=True)
    player_id       = Column(Integer, ForeignKey("players.id"), nullable=False)
    dungeon_id      = Column(Text, nullable=False)
    outcome         = Column(Text, nullable=False)
    nodes_completed = Column(Integer, default=0)
    items_recovered = Column(Text)
    coin_spent      = Column(Integer, default=0)
    created_at      = Column(DateTime, default=datetime.utcnow)

    player = relationship("Player", back_populates="run_history")
