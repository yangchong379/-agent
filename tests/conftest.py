import os


os.environ.setdefault("APP_API_KEY", "test-api-key-value")
os.environ.setdefault("DATABASE_URL", "sqlite:///./data/test_agent.db")
os.environ.setdefault("LLM_PROVIDER", "mock")
os.environ.setdefault("AUTO_CREATE_SCHEMA", "true")

