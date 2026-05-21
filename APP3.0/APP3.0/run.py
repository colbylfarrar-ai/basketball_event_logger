import os
import subprocess
from pathlib import Path
import sys

# Ensure database initializes on startup
from Database.db import initialize_database

def main():
    # Initialize DB (safe if already exists)
    initialize_database()

    # Resolve APP.py path
    app_path = Path(__file__).resolve().parent / "APP.py"

    # Launch Streamlit
    subprocess.run([sys.executable, "-m", "streamlit", "run", str(app_path)])

if __name__ == "__main__":
    main()