import subprocess
from pathlib import Path
import sys

# Ensure database initializes on startup
from database.db import initialize_database

def main():
    # Initialize DB (safe if already exists)
    initialize_database()

    # Resolve the Streamlit entry point
    app_path = Path(__file__).resolve().parent / "main.py"

    # Launch Streamlit
    subprocess.run([sys.executable, "-m", "streamlit", "run", str(app_path)])

if __name__ == "__main__":
    main()
