from pathlib import Path

from dotenv import load_dotenv


def load_environment(base_dir: Path) -> None:
    """Load local settings without overriding exported environment variables."""
    load_dotenv(base_dir / ".env", override=False)
