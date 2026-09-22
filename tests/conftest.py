import os

os.environ.setdefault("SECRET_KEY", "test-secret-key-min-32-characters-long")
os.environ.setdefault("POSTGRES_PASSWORD", "test-strong-postgres-password")
os.environ.setdefault("MINIO_ACCESS_KEY", "testminioaccess12")
os.environ.setdefault("MINIO_SECRET_KEY", "test-strong-minio-secret-key")
