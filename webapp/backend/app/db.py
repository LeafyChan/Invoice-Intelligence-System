import os
from contextlib import contextmanager

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError(
        "DATABASE_URL is not set. Expected the Supabase Session Pooler URI, "
        "e.g. postgresql://invoice_app.PROJECT_REF:PASSWORD@aws-REGION.pooler.supabase.com:5432/postgres"
    )
engine = create_engine(DATABASE_URL, pool_pre_ping=True, pool_size=5, max_overflow=5)
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)


@contextmanager
def _session_with_org(org_id: str):
    session = SessionLocal()
    try:
        session.execute(
            text("SELECT set_config('app.current_org_id', :org_id, false)"),
            {"org_id": str(org_id)},
        )
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.execute(text("RESET app.current_org_id"))
        session.close()


@contextmanager
def get_org_scoped_db(org_id: str):
    with _session_with_org(org_id) as session:
        yield session


def get_admin_db():
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()