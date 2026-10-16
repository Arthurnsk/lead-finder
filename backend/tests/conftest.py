import os

# Never inherit DATABASE_URL: tests drop all tables. Use TEST_DATABASE_URL or in-memory SQLite.
os.environ["DATABASE_URL"] = os.getenv("TEST_DATABASE_URL", "sqlite://")
os.environ.setdefault("SECRET_KEY", "test-secret-key-that-is-long-enough-for-hs256")
os.environ.setdefault("FERNET_KEY", "5b7tKq3Qx1bI0mZ8oJ3d2rWb3Q8Qj1a4Z3m7m0Jb8vY=")
os.environ.setdefault("LOGIN_RATE_PER_MINUTE", "1000")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.db import Base, SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Membership, Organization, User  # noqa: E402
from app.security import CSRF_COOKIE, hash_password  # noqa: E402

PASSWORD = "correct-horse-battery"


@pytest.fixture(autouse=True)
def fresh_db():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield


@pytest.fixture
def db():
    with SessionLocal() as session:
        yield session


def make_user(db, email, *, org=None, role="owner", superadmin=False):
    user = User(email=email, password_hash=hash_password(PASSWORD), is_superadmin=superadmin)
    db.add(user)
    db.flush()
    if org:
        db.add(Membership(user_id=user.id, organization_id=org.id, role=role))
    db.commit()
    return user


def make_org(db, slug):
    org = Organization(name=slug.upper(), slug=slug)
    db.add(org)
    db.commit()
    return org


class Api:
    """TestClient wrapper that logs in and sends the CSRF header like the SPA does."""

    def __init__(self, email=None, org_id=None):
        self.c = TestClient(app)
        self.org_id = org_id
        if email:
            r = self.c.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
            assert r.status_code == 200, r.text

    def _headers(self):
        h = {}
        if CSRF_COOKIE in self.c.cookies:
            h["X-CSRF-Token"] = self.c.cookies[CSRF_COOKIE]
        if self.org_id:
            h["X-Org-Id"] = str(self.org_id)
        return h

    def get(self, url, **kw):
        return self.c.get(url, headers=self._headers(), **kw)

    def post(self, url, **kw):
        return self.c.post(url, headers=self._headers(), **kw)

    def patch(self, url, **kw):
        return self.c.patch(url, headers=self._headers(), **kw)

    def delete(self, url, **kw):
        return self.c.delete(url, headers=self._headers(), **kw)
