"""Create all database tables. Run once (or use Alembic for real migrations)."""
from app.db.models import Base
from app.db.session import get_engine

if __name__ == "__main__":
    Base.metadata.create_all(get_engine())
    print("Tables created.")
