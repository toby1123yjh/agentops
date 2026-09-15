"""Local credentials and sessions, stored in the same private PostgreSQL database."""

import os
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import Column, DateTime, ForeignKey, String, UUID, inspect, select, text
from werkzeug.security import check_password_hash, generate_password_hash

from agentops.common.local_mode import validate_local_settings
from agentops.common.orm import BaseModel, get_engine, session_scope
from agentops.opsboard.models import (
    UserModel, OrgModel, UserOrgModel, OrgInviteModel, ProjectModel, OrgRoles,
)


class LocalCredential(BaseModel):
    __tablename__ = "local_credentials"
    __table_args__ = {"schema": "public"}
    user_id = Column(UUID, ForeignKey("public.users.id"), primary_key=True)
    email = Column(String, unique=True, nullable=False)
    password_hash = Column(String, nullable=False)


class LocalSession(BaseModel):
    __tablename__ = "local_sessions"
    __table_args__ = {"schema": "public"}
    id = Column(UUID, primary_key=True)
    user_id = Column(UUID, ForeignKey("public.users.id"), nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False)


def bootstrap() -> None:
    """Initialize a dedicated empty database; never reset existing users or passwords."""
    validate_local_settings()
    email = os.getenv("AGENTOPS_LOCAL_EMAIL", "").strip().lower()
    password = os.getenv("AGENTOPS_LOCAL_PASSWORD", "")
    if "@" not in email or len(password) < 12:
        raise RuntimeError("Set AGENTOPS_LOCAL_EMAIL and a password of at least 12 characters")
    tables = [model.__table__ for model in (
        UserModel, OrgModel, UserOrgModel, OrgInviteModel, ProjectModel, LocalCredential, LocalSession,
    )]
    engine = get_engine()
    with engine.begin() as conn:
        # Serialize initialization across starts. Do not initialize over a business/cloud schema.
        conn.execute(text("SELECT pg_advisory_xact_lock(1734829101)"))
        existing = set(inspect(conn).get_table_names(schema="public"))
        if existing and "local_credentials" not in existing:
            raise RuntimeError("Local bootstrap requires an empty dedicated database")
        BaseModel.metadata.create_all(conn, tables=tables)
    with session_scope() as orm:
        orm.execute(text("SELECT pg_advisory_xact_lock(1734829101)"))
        if orm.scalar(select(LocalCredential.user_id).limit(1)) is not None:
            return
        user_id, org_id = uuid.uuid4(), uuid.uuid4()
        orm.add(UserModel(id=user_id, email=email, full_name="Local administrator", survey_is_complete=True))
        orm.add(OrgModel(id=org_id, name="Local workspace"))
        orm.flush()
        orm.add(UserOrgModel(user_id=user_id, org_id=org_id, role=OrgRoles.owner, user_email=email, is_paid=True))
        orm.add(LocalCredential(user_id=user_id, email=email, password_hash=generate_password_hash(password)))
        orm.add(ProjectModel(org_id=org_id, name="Local project"))


def authenticate(email: str, password: str) -> uuid.UUID | None:
    with session_scope() as orm:
        credential = orm.scalar(select(LocalCredential).where(LocalCredential.email == email.strip().lower()))
        if credential and check_password_hash(credential.password_hash, password):
            return credential.user_id
    return None


def create_session(session_id: uuid.UUID, user_id: uuid.UUID, ttl: int) -> None:
    with session_scope() as orm:
        orm.add(LocalSession(id=session_id, user_id=user_id, expires_at=datetime.now(timezone.utc) + timedelta(seconds=ttl)))


def get_session_user(session_id: str | uuid.UUID) -> uuid.UUID | None:
    try:
        session_id = uuid.UUID(str(session_id))
    except ValueError:
        return None
    with session_scope() as orm:
        session = orm.get(LocalSession, session_id)
        if session and session.expires_at > datetime.now(timezone.utc):
            return session.user_id
    return None


def update_session(session_id: uuid.UUID, ttl: int | None) -> None:
    with session_scope() as orm:
        session = orm.get(LocalSession, session_id)
        if session:
            if ttl is None:
                orm.delete(session)
            elif session.expires_at > datetime.now(timezone.utc):
                session.expires_at = datetime.now(timezone.utc) + timedelta(seconds=ttl)


if __name__ == "__main__":
    bootstrap()
    print("Local database initialized. Existing accounts and API keys are preserved.")
