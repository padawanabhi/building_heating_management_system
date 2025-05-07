from .database import engine # Removed create_db_and_tables from import
from .models import Base # Ensure models are imported so Base knows about them

def main():
    print("Initializing database...")
    # The following line will create tables if they don't exist.
    # In a real application, you might use Alembic for migrations.
    Base.metadata.create_all(bind=engine) 
    print("Database initialization complete.")
    print(f"Database tables created (if they didn't exist) for {engine.url}")

if __name__ == "__main__":
    main() 