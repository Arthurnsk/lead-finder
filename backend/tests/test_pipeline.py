from datetime import date, timedelta

import pytest
from sqlalchemy import select

from app.engine.llm import parse_json, strip_thinking
from app.engine.pipeline import execute_run
from app.models import Lead, Project, ProjectSource, Run, RunEvent, SeenUrl
from app.sources.base import REGISTRY, Candidate, Source
from tests.conftest import Api, make_org, make_user

TODAY = date.today()

CANDIDATES = [
    Candidate(url="https://vk.com/wall-1_1", title="Получили гектар",
              text="Подскажите, получили дальневосточный гектар, не знаем что строить", source="fake",
              platform="vk", posted_at=TODAY),
    Candidate(url="https://vk.com/wall-1_2", title="Продаю участок",
              text="Продаю участок 15 соток, звоните", source="fake", platform="vk", posted_at=TODAY),
    Candidate(url="https://vk.com/wall-1_3", title="Ищу участок",
              text="Ищу участок под ИЖС, помогите проверить ЗОУИТ", source="fake", platform="vk",
              posted_at=TODAY - timedelta(days=400)),  # stale → dropped before LLM
    Candidate(url="https://example-agency.ru/blog", title="Помогите с гектаром",
              text="наш блог", source="fake", platform="web", posted_at=TODAY),  # blocked host
]


class FakeSource(Source):
    type = "fake"

    def fetch(self, ctx):
        ctx.log("info", "fake source")
        return list(CANDIDATES)


REGISTRY["fake"] = FakeSource


class FakeLlm:
    base_url = "fake://llm"
    model = "fake-model"

    def __init__(self, healthy=True):
        self.healthy = healthy
        self.calls = 0

    def health(self):
        return (True, "ok") if self.healthy else (False, "connection refused")

    def chat_json(self, system, user, max_tokens=500):
        self.calls += 1
        fit = "гектар" in user and "Продаю" not in user
        return {"is_fit": fit, "score": 0.9 if fit else 0.2, "reason": "fake", "segment": "гектар" if fit else "",
                "evidence_ok": True, "is_likely_spam_or_competitor": False, "stale": False}


@pytest.fixture
def project(db):
    org = make_org(db, "acme")
    make_user(db, "o@acme.ru", org=org)
    p = Project(organization_id=org.id, name="Земля", slug="zemlya", max_age_days=90,
                blocked_hosts=["example-agency.ru"], icp="гектар")
    db.add(p)
    db.flush()
    db.add(ProjectSource(organization_id=org.id, project_id=p.id, type="fake", name="Fake", config={}))
    db.commit()
    return p


def _run(db, project, llm):
    run = Run(organization_id=project.organization_id, project_id=project.id, status="running")
    db.add(run)
    db.commit()
    execute_run(db, run, llm=llm)
    return run


def test_run_creates_leads_and_dedupes(db, project):
    llm = FakeLlm()
    run = _run(db, project, llm)
    assert run.status == "succeeded", run.error
    leads = db.scalars(select(Lead)).all()
    assert [lead.url for lead in leads] == ["https://vk.com/wall-1_1"]
    assert run.stats["leads"] == 1 and run.stats["rejected"] == 1
    assert run.stats["dropped"]["stale"] == 1 and run.stats["dropped"]["blocked_host"] == 1
    assert llm.calls == 2  # stale and blocked never reach the model

    llm2 = FakeLlm()
    run2 = _run(db, project, llm2)
    # the stale one is remembered as well, so it is never downloaded again
    assert run2.stats["skipped_seen"] == 3 and llm2.calls == 0
    assert db.scalar(select(SeenUrl).where(SeenUrl.url == "https://vk.com/wall-1_3")).verdict == "stale"
    assert db.scalar(select(SeenUrl).where(SeenUrl.url == "https://vk.com/wall-1_2")).verdict == "reject"


def test_llm_unavailable_fails_clearly(db, project):
    run = _run(db, project, FakeLlm(healthy=False))
    assert run.status == "failed" and "LLM недоступна" in run.error
    assert db.scalars(select(Lead)).all() == []


def test_cancel_stops_run(db, project):
    class CancellingLlm(FakeLlm):
        def chat_json(self, *a, **kw):
            db.execute(Run.__table__.update().values(status="cancelled"))
            db.commit()
            return super().chat_json(*a, **kw)

    run = _run(db, project, CancellingLlm())
    assert run.status == "cancelled"


def test_source_error_does_not_kill_run(db, project):
    class Broken(Source):
        type = "broken"

        def fetch(self, ctx):
            raise RuntimeError("boom")

    REGISTRY["broken"] = Broken
    db.add(ProjectSource(organization_id=project.organization_id, project_id=project.id, type="broken", config={}))
    db.commit()
    run = _run(db, project, FakeLlm())
    assert run.status == "succeeded" and run.stats["source_errors"] == 1 and run.stats["leads"] == 1
    assert any("boom" in e.message for e in db.scalars(select(RunEvent)))


def test_leads_api_isolation_and_update(db, project):
    _run(db, project, FakeLlm())
    other = make_org(db, "other")
    make_user(db, "x@other.ru", org=other)
    api = Api("o@acme.ru")
    page = api.get("/api/v1/leads").json()
    assert page["total"] == 1
    lead_id = page["items"][0]["id"]
    assert Api("x@other.ru").get(f"/api/v1/leads/{lead_id}").status_code == 404
    r = api.patch(f"/api/v1/leads/{lead_id}", json={"status": "contacted", "feedback": "good"})
    assert r.status_code == 200 and r.json()["feedback"] == "good"
    assert api.get("/api/v1/leads", params={"status": ["new"]}).json()["total"] == 0
    dash = api.get("/api/v1/dashboard").json()
    assert dash["total"] == 1 and dash["feedback"]["precision"] == 1.0
    assert "wall-1_1" in api.get("/api/v1/leads/export.csv").text


def test_run_api_conflict_and_events(db, project):
    api = Api("o@acme.ru")
    r = api.post(f"/api/v1/projects/{project.id}/runs")
    assert r.status_code == 201
    assert api.post(f"/api/v1/projects/{project.id}/runs").status_code == 409
    run_id = r.json()["id"]
    assert api.post(f"/api/v1/runs/{run_id}/cancel").json()["status"] == "cancelled"


def test_integration_secret_is_masked(db, project):
    api = Api("o@acme.ru")
    r = api.post("/api/v1/integrations", json={"type": "vk_token", "config": {"token": "vk1.a.SUPERSECRETTOKEN123"}})
    assert r.status_code == 201
    assert "SUPERSECRET" not in r.text
    assert "SUPERSECRET" not in api.get("/api/v1/integrations").text
    r = api.post("/api/v1/integrations", json={"type": "webhook", "config": {"url": "http://insecure"}})
    assert r.status_code == 422


def test_llm_json_parsing():
    assert parse_json('<think>{x}</think>```json\n{"a": {"b": 1}}\n``` trailing') == {"a": {"b": 1}}
    assert strip_thinking('reasoning…</think>{"a":1}') == '{"a":1}'


def test_fallback_llm_switches_on_outage():
    from app.engine.llm import FallbackLlm, LlmUnavailable

    class Down:
        base_url, model = "http://down/v1", "primary"

        def health(self):
            return False, "connection refused"

        def chat_json(self, *a, **kw):
            raise LlmUnavailable("rate limit")

        def chat(self, *a, **kw):
            raise LlmUnavailable("rate limit")

    class Up:
        base_url, model = "https://backup/v1", "backup"

        def health(self):
            return True, "ok"

        def chat_json(self, *a, **kw):
            return {"is_fit": True}

        def chat(self, *a, **kw):
            return "ok"

    notes: list[str] = []
    llm = FallbackLlm(Down(), Up(), on_switch=notes.append)
    assert llm.health()[0] is True          # health check already moves to the backup
    assert llm.chat_json("s", "u") == {"is_fit": True}
    assert llm.model == "backup" and notes  # and the switch is reported to the run log

    alone = FallbackLlm(Down(), None)
    assert alone.health()[0] is False
    with pytest.raises(LlmUnavailable):
        alone.chat_json("s", "u")  # a dead endpoint fails fast, no waiting


def test_fallback_waits_only_for_quota_errors():
    from app.engine.llm import FallbackLlm, LlmUnavailable

    class Quota:
        base_url, model = "https://quota/v1", "m"
        calls = 0

        def health(self):
            return True, "ok"

        def chat_json(self, *a, **kw):
            Quota.calls += 1
            raise LlmUnavailable("rate limit", retryable=True)

    llm = FallbackLlm(Quota(), None)
    llm.WAIT_SECONDS = (0.01, 0.01)  # keep the test fast
    with pytest.raises(LlmUnavailable):
        llm.chat_json("s", "u")
    assert Quota.calls == 3  # first try + two waits
