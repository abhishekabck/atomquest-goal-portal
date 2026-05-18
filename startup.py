"""
Auto-run before server start on cloud platforms.
Creates the data/ directory and seeds the DB if it's empty.
"""
import os
import sys

# Ensure data directory exists
os.makedirs("data", exist_ok=True)

# Check if DB is already seeded
db_path = os.path.join("data", "app.db")
if not os.path.exists(db_path) or os.path.getsize(db_path) == 0:
    print("Seeding database...")
    import seed_data  # noqa: runs the seed script
    print("Database seeded.")
else:
    print("Database already exists, skipping seed.")
