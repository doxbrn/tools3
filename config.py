# config.py

import os

# Chave da API
API_KEY = os.getenv("API_KEY")
if not API_KEY:
    raise ValueError("API_KEY environment variable is not set")

# Caminho local para armazenamento temporário
LOCAL_STORAGE_PATH = os.getenv("LOCAL_STORAGE_PATH", "/tmp")

# URL padrão de música de fundo (pode ser None)
DEFAULT_BACKGROUND_MUSIC_URL = os.getenv("DEFAULT_BACKGROUND_MUSIC_URL")

# S3-compatible
S3_ENDPOINT_URL = os.getenv("S3_ENDPOINT_URL", "")
S3_ACCESS_KEY    = os.getenv("S3_ACCESS_KEY", "")
S3_SECRET_KEY    = os.getenv("S3_SECRET_KEY", "")
S3_BUCKET_NAME   = os.getenv("S3_BUCKET_NAME", "")
S3_REGION        = os.getenv("S3_REGION", "us-east-1")