from __future__ import annotations
import os
from dotenv import load_dotenv
load_dotenv()
class Settings:
    JIRA_BASE_URL: str = os.getenv("JIRA_BASE_URL", "").rstrip("/")
    JIRA_EMAIL: str = os.getenv("JIRA_EMAIL", "")
    JIRA_API_TOKEN: str = os.getenv("JIRA_API_TOKEN", "")
    JIRA_PROJECT_KEY: str = os.getenv("JIRA_PROJECT_KEY", "REL")
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
    LLM_MODEL: str = os.getenv("LLM_MODEL", "gemini-flash-lite-latest")
    @classmethod
    def validate(cls) -> None:
        missing = [
            name
            for name in [
                "JIRA_BASE_URL",
                "JIRA_EMAIL",
                "JIRA_API_TOKEN",
                "JIRA_PROJECT_KEY",
                "GEMINI_API_KEY",
            ]
            if not getattr(cls, name)
        ]
        if missing:
            raise ValueError(f"Missing required environment variables: {', '.join(missing)}")
settings = Settings()