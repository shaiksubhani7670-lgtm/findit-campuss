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
        # If /tmp copy failed, fallback to source (read-only but at least readable)
        os.environ['DATABASE_URL'] = f'sqlite:///{db_source}'

from app import create_app

app = create_app()
