import uuid
from sqlalchemy import text
from sqlalchemy.orm import Session
from app.db import SessionLocal

def resolve_org_and_user(clerk_org_id: str, clerk_user_id: str, email: str = None) -> dict:
    session: Session = SessionLocal()
    try:
        org_row = session.execute(
            text("SELECT org_id FROM orgs WHERE clerk_org_id = :cid"),
            {"cid": clerk_org_id},
        ).fetchone()

        if org_row:
            org_id = org_row[0]
        else:
            org_id = str(uuid.uuid4())
            session.execute(
                text(
                    "INSERT INTO orgs (org_id, clerk_org_id, name) "
                    "VALUES (:oid, :cid, :name)"
                ),
                {"oid": org_id, "cid": clerk_org_id, "name": f"Org {clerk_org_id}"},
            )
        new_user_id = str(uuid.uuid4())
        session.execute(
            text("SELECT set_config('app.current_org_id', :oid, false)"),
            {"oid": str(org_id)},
        )
        result = session.execute(
            text(
                "INSERT INTO users (user_id, clerk_user_id, org_id, email) "
                "VALUES (:uid, :cid, :oid, :email) "
                "ON CONFLICT (clerk_user_id) DO UPDATE SET org_id = EXCLUDED.org_id "
                "RETURNING user_id"
            ),
            {"uid": new_user_id, "cid": clerk_user_id, "oid": org_id, "email": email or ""},
        )
        user_id = result.scalar()
        session.commit()
        session.execute(text("RESET app.current_org_id"))
        return {"org_id": org_id, "user_id": user_id}
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()