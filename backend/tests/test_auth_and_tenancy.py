from pathlib import Path

from tests.conftest import PASSWORD, Api, make_org, make_user

NICHE_YAML = Path(__file__).resolve().parents[2] / "niches" / "land_agency_demo.yaml"


def test_login_and_me(db):
    org = make_org(db, "acme")
    make_user(db, "owner@acme.ru", org=org)
    api = Api("owner@acme.ru")
    me = api.get("/api/v1/auth/me").json()
    assert me["email"] == "owner@acme.ru"
    assert me["memberships"][0]["role"] == "owner"


def test_wrong_password_rejected(db):
    make_user(db, "u@x.ru")
    r = Api().c.post("/api/v1/auth/login", json={"email": "u@x.ru", "password": "nope-nope-nope"})
    assert r.status_code == 401


def test_unauthenticated_blocked():
    assert Api().get("/api/v1/projects").status_code == 401


def test_csrf_required_for_writes(db):
    org = make_org(db, "acme")
    make_user(db, "owner@acme.ru", org=org)
    api = Api("owner@acme.ru")
    r = api.c.post("/api/v1/projects", json={"name": "P1", "slug": "p1"})  # no CSRF header
    assert r.status_code == 403
    assert api.post("/api/v1/projects", json={"name": "P1", "slug": "p1"}).status_code == 201


def test_tenant_isolation(db):
    a, b = make_org(db, "org-a"), make_org(db, "org-b")
    make_user(db, "a@a.ru", org=a)
    make_user(db, "b@b.ru", org=b)
    api_a, api_b = Api("a@a.ru"), Api("b@b.ru")

    project_a = api_a.post("/api/v1/projects", json={"name": "Secret A", "slug": "secret"}).json()

    assert api_b.get("/api/v1/projects").json() == []
    assert api_b.get(f"/api/v1/projects/{project_a['id']}").status_code == 404
    assert api_b.patch(f"/api/v1/projects/{project_a['id']}", json={"name": "pwned"}).status_code == 404
    # B cannot switch into A's org by header
    api_b.org_id = a.id
    assert api_b.get("/api/v1/projects").status_code == 403


def test_viewer_cannot_write(db):
    org = make_org(db, "acme")
    make_user(db, "v@acme.ru", org=org, role="viewer")
    api = Api("v@acme.ru")
    assert api.get("/api/v1/projects").status_code == 200
    assert api.post("/api/v1/projects", json={"name": "P", "slug": "p"}).status_code == 403


def test_last_owner_protected(db):
    org = make_org(db, "acme")
    owner = make_user(db, "o@acme.ru", org=org)
    api = Api("o@acme.ru")
    r = api.patch(f"/api/v1/members/{owner.id}", json={"role": "admin"})
    assert r.status_code == 400


def test_admin_cannot_grant_owner(db):
    org = make_org(db, "acme")
    make_user(db, "o@acme.ru", org=org)
    make_user(db, "adm@acme.ru", org=org, role="admin")
    api = Api("adm@acme.ru")
    r = api.post("/api/v1/members", json={"email": "new@acme.ru", "role": "owner", "password": PASSWORD})
    assert r.status_code == 403
    r = api.post("/api/v1/members", json={"email": "new@acme.ru", "role": "manager", "password": PASSWORD})
    assert r.status_code == 201


def test_superadmin_creates_org(db):
    make_user(db, "root@saas.ru", superadmin=True)
    api = Api("root@saas.ru")
    r = api.post("/api/v1/admin/orgs", json={
        "name": "Client", "slug": "client", "owner_email": "boss@client.ru", "owner_password": PASSWORD,
    })
    assert r.status_code == 201, r.text
    assert Api("boss@client.ru").get("/api/v1/auth/me").json()["memberships"][0]["role"] == "owner"


def test_regular_user_not_superadmin(db):
    org = make_org(db, "acme")
    make_user(db, "o@acme.ru", org=org)
    assert Api("o@acme.ru").get("/api/v1/admin/orgs").status_code == 403


def test_import_niche_yaml(db):
    org = make_org(db, "acme")
    make_user(db, "o@acme.ru", org=org)
    api = Api("o@acme.ru")
    with open(NICHE_YAML, "rb") as f:
        r = api.post("/api/v1/projects/import", files={"file": ("land_agency_demo.yaml", f, "application/x-yaml")})
    assert r.status_code == 201, r.text
    project = r.json()
    assert project["slug"] == "land_agency_demo"
    types = {s["type"]: s for s in project["sources"]}
    assert {"vk", "searxng", "rss", "ddg", "tenders", "web_watch", "telegram_chat"} <= set(types)
    assert all("site:" not in q for q in types["vk"]["config"]["queries"])
    exported = api.get(f"/api/v1/projects/{project['id']}/export").text
    assert "land_agency_demo" in exported and "icp" in exported


def test_invalid_cron_rejected(db):
    org = make_org(db, "acme")
    make_user(db, "o@acme.ru", org=org)
    api = Api("o@acme.ru")
    p = api.post("/api/v1/projects", json={"name": "Proj", "slug": "p1"}).json()
    r = api.patch(f"/api/v1/projects/{p['id']}", json={"schedule_cron": "every day", "schedule_enabled": True})
    assert r.status_code == 422
    r = api.patch(f"/api/v1/projects/{p['id']}", json={"schedule_cron": "0 */3 * * *", "schedule_enabled": True})
    assert r.status_code == 200 and r.json()["next_run_at"]
