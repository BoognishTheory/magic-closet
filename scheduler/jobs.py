from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from db.database import get_session
from db.models import Player, Quest
from datetime import datetime, timedelta

scheduler = AsyncIOScheduler()


def quest_tick():
    """Daily job - increment day_count on active quests, fail expired ones."""
    session = get_session()
    try:
        active_quests = session.query(Quest).filter_by(status="active").all()
        for quest in active_quests:
            quest.day_count += 1
            if quest.day_count >= 5:
                quest.status = "failed"
                print(f"Quest {quest.id} expired for player {quest.player_id}")
        session.commit()
        print(f"[quest_tick] Processed {len(active_quests)} active quests.")
    finally:
        session.close()


def weekly_reset():
    """Monday midnight - nothing to reset in DB yet, placeholder for future logic."""
    print(f"[weekly_reset] Weekly reset fired at {datetime.utcnow()}")


def rent_engine():
    """Daily job - check inactivity and drain coin or set debt flag."""
    session = get_session()
    try:
        players = session.query(Player).all()
        now = datetime.utcnow()
        affected = 0

        for player in players:
            if not player.last_active:
                continue

            days_inactive = (now - player.last_active).days

            if days_inactive >= 30:
                player.debt = True
                affected += 1
            elif days_inactive >= 7:
                drain = 5 * (days_inactive - 6)
                player.coin = max(0, player.coin - drain)
                affected += 1

        session.commit()
        print(f"[rent_engine] Processed {affected} players.")
    finally:
        session.close()


def start_scheduler():
    scheduler.add_job(
        quest_tick,
        CronTrigger(hour=0, minute=0),
        id="quest_tick",
        replace_existing=True
    )
    scheduler.add_job(
        weekly_reset,
        CronTrigger(day_of_week="mon", hour=0, minute=0),
        id="weekly_reset",
        replace_existing=True
    )
    scheduler.add_job(
        rent_engine,
        CronTrigger(hour=0, minute=1),
        id="rent_engine",
        replace_existing=True
    )
    scheduler.start()
    print("Scheduler started.")