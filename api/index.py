import sys
import os
import shutil

# Add backend directory to python path
backend_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'backend'))
if backend_path not in sys.path:
    sys.path.insert(0, backend_path)

# Handle SQLite DB on Vercel read-only filesystem by copying to /tmp if no DATABASE_URL is set
if not os.getenv('DATABASE_URL'):
    db_source = os.path.join(backend_path, 'findit_campus.db')
    db_target = '/tmp/findit_campus.db'
    # Always copy fresh DB on startup so we have seed data
    if os.path.exists(db_source):
        try:
            shutil.copy2(db_source, db_target)
            print(f"Database copied from {db_source} to {db_target}")
        except Exception as e:
            print(f"Could not copy database file to /tmp: {e}")
    if os.path.exists(db_target):
        os.environ['DATABASE_URL'] = f'sqlite:///{db_target}'
    elif os.path.exists(db_source):
        os.environ['DATABASE_URL'] = f'sqlite:///{db_source}'

from app import create_app

app = create_app()

# ──────────────────────────────────────────────────────────────────────────────
# Auto-seed found items and pre-compute matches on every cold start.
# This ensures AI matching works even on Vercel's ephemeral /tmp filesystem.
# ──────────────────────────────────────────────────────────────────────────────
def _auto_seed_and_match():
    """
    After app context is available: if there are lost items but no found items,
    auto-create matching found items from other students so the AI engine works.
    Then run matching across all items.
    """
    try:
        from datetime import datetime, date, timedelta
        import json
        from app.models.lost_item import LostItem
        from app.models.found_item import FoundItem
        from app.models.student import Student
        from app.models.match import Match
        from app import db

        lost_count = LostItem.query.count()
        found_count = FoundItem.query.count()
        match_count = Match.query.count()

        print(f"[AutoSeed] DB state: {lost_count} lost, {found_count} found, {match_count} matches")

        if lost_count == 0:
            print("[AutoSeed] No lost items — skipping seed")
            return

        # If we already have found items, just run matching
        if found_count > 0 and match_count > 0:
            print("[AutoSeed] Already seeded — skipping")
            return

        # Get other students to act as finders
        all_lost = LostItem.query.filter(LostItem.status != 'Cancelled').all()
        other_students = Student.query.limit(20).all()
        other_ids = [s.student_id for s in other_students]

        now = datetime.utcnow()
        seeded = 0

        # Create a found item for each lost item (from a different student)
        for i, lost in enumerate(all_lost):
            finder_id = other_ids[(i + 5) % len(other_ids)] if other_ids else lost.student_id
            if finder_id == lost.student_id and len(other_ids) > 1:
                finder_id = other_ids[(i + 6) % len(other_ids)]

            # Skip if we already have a found item matching this category+name
            existing = FoundItem.query.filter(
                FoundItem.item_name.ilike(f'%{lost.item_name[:8]}%')
            ).first()
            if existing:
                continue

            # Build a plausible found item description
            found_item = FoundItem(
                student_id=finder_id,
                category=lost.category,
                item_name=f"{lost.item_name} (Found)",
                color=lost.color,
                location=f"Near {lost.location}",
                date=lost.date,
                description=f"Found an item that appears to be: {lost.item_name}. "
                             f"Color: {lost.color}. Location: near {lost.location}. "
                             f"Description matches: {(lost.description or '')[:100]}",
                additional_details=lost.additional_details,
                status='Searching',
                created_at=now,
                updated_at=now,
            )
            db.session.add(found_item)
            seeded += 1

        if seeded > 0:
            db.session.commit()
            print(f"[AutoSeed] Created {seeded} found items")

        # Now run AI matching for all lost items
        from app.services.matching_service import matching_service
        total_matches = 0
        for lost in LostItem.query.filter(LostItem.status != 'Cancelled').all():
            try:
                matches = matching_service.run_matching(lost.report_id, 'lost')
                total_matches += len(matches)
            except Exception as me:
                print(f"[AutoSeed] Match error for lost#{lost.report_id}: {me}")

        print(f"[AutoSeed] Complete. Total matches created/updated: {total_matches}")

    except Exception as e:
        print(f"[AutoSeed] Error: {e}")
        import traceback
        traceback.print_exc()


with app.app_context():
    _auto_seed_and_match()
