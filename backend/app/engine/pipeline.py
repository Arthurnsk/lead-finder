"""One run of a project: sources → dedupe → prefilter → freshness → LLM → leads + live log."""

from __future__ import annotations

import time
import uuid
from collections import Counter
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

import app.sources.ddg  # noqa: F401  (register plugins)
import app.sources.rss  # noqa: F401
import app.sources.searxng  # noqa: F401
import app.sources.telegram  # noqa: F401
import app.sources.telegram_chat  # noqa: F401
import app.sources.tenders  # noqa: F401
import app.sources.web_watch  # noqa: F401
import app.sources.vk  # noqa: F401
from app.db import utcnow
from app.engine.contacts import extract_contacts
from app.engine.dates import extract_post_date, is_stale
from app.engine.enrich import enrich_forum_thread, outreach_for
from app.engine.evaluator import LeadEvaluator
from app.engine.filters import compile_patterns, prefilter_hit
from app.engine.llm import FallbackLlm, LlmClient, LlmConfig, LlmUnavailable
from app.integrations.dispatch import dispatch_lead, org_secrets
from app.models import Lead, LlmSettings, Project, Run, RunEvent, SeenUrl
from app.security import decrypt_json
from app.sources.base import REGISTRY, SourceContext, SourceError


class RunCancelled(Exception):
    pass


class RunBudgetExceeded(Exception):
    pass


# A run must always end: a stuck source or a slow provider can't hold the worker forever
RUN_BUDGET_SECONDS = 45 * 60


def llm_config_for(db: Session, org_id: uuid.UUID) -> LlmConfig:
    cfg = LlmConfig.default()
    s = db.scalar(select(LlmSettings).where(LlmSettings.organization_id == org_id))
    if s:
        cfg.base_url = s.base_url or cfg.base_url
        cfg.model = s.model or cfg.model
        cfg.disable_thinking = s.disable_thinking
        if s.api_key_enc:
            cfg.api_key = decrypt_json(s.api_key_enc).get("api_key", cfg.api_key)
    return cfg


def fallback_config_for(db: Session, org_id: uuid.UUID) -> LlmConfig | None:
    s = db.scalar(select(LlmSettings).where(LlmSettings.organization_id == org_id))
    if not s or not s.fallback_base_url:
        return None
    key = decrypt_json(s.fallback_api_key_enc).get("api_key", "local") if s.fallback_api_key_enc else "local"
    return LlmConfig(s.fallback_base_url, s.fallback_model, key, s.disable_thinking)


def build_llm(db: Session, org_id: uuid.UUID, on_switch=None, timeout: float = 180.0) -> FallbackLlm:
    backup_cfg = fallback_config_for(db, org_id)
    return FallbackLlm(
        LlmClient(llm_config_for(db, org_id), timeout=timeout),
        LlmClient(backup_cfg, timeout=timeout) if backup_cfg else None,
        on_switch=on_switch,
    )


def feedback_examples(db: Session, project_id: uuid.UUID, limit: int = 10) -> list[dict]:
    rows = db.scalars(
        select(Lead).where(Lead.project_id == project_id, Lead.feedback.in_(["good", "bad"]))
        .order_by(Lead.updated_at.desc()).limit(limit)
    ).all()
    return [{"text": f"{r.title} {r.text}"[:300], "is_fit": r.feedback == "good", "why": "оценка менеджера"}
            for r in reversed(rows)]


def _mark_source(db: Session, source, *, items: int | None = None, error: str = "") -> None:
    """Remember how the source behaved, so a silently broken one is visible in the UI."""
    if error:
        source.fail_streak += 1
        source.last_error = error[:1000]
    else:
        source.fail_streak = 0
        source.last_error = ""
        source.last_ok_at = utcnow()
        source.last_items = items or 0
    db.commit()


class RunLogger:
    def __init__(self, db: Session, run: Run):
        self.db, self.run = db, run

    def __call__(self, level: str, message: str) -> None:
        self.db.add(RunEvent(run_id=self.run.id, level=level, message=message[:2000]))
        self.db.commit()  # commit per event so the SSE stream sees it immediately


def execute_run(db: Session, run: Run, llm: LlmClient | None = None) -> None:
    project = db.scalar(select(Project).options(selectinload(Project.sources)).where(Project.id == run.project_id))
    log = RunLogger(db, run)
    stats: Counter = Counter()
    dropped: Counter = Counter()
    by_source: Counter = Counter()

    started = time.monotonic()

    def check_cancel():
        db.expire(run, ["status"])
        if run.status == "cancelled":
            raise RunCancelled()
        if time.monotonic() - started > RUN_BUDGET_SECONDS:
            raise RunBudgetExceeded()

    try:
        llm = llm or build_llm(db, project.organization_id, on_switch=lambda msg: log("warn", msg))
        ok, why = llm.health()
        if not ok:
            raise LlmUnavailable(f"LLM недоступна на {llm.base_url}: {why}. Запустите MTPLX на Mac.")

        since = date.today() - timedelta(days=project.max_age_days) if project.max_age_days else None
        known = set(db.scalars(select(SeenUrl.url).where(SeenUrl.project_id == project.id)))
        known |= set(db.scalars(select(Lead.url).where(Lead.project_id == project.id)))
        examples = feedback_examples(db, project.id)
        evaluator = LeadEvaluator(llm, project, examples)
        demand_re = compile_patterns(project.demand_patterns or [])
        exclude_re = compile_patterns(project.exclude_patterns or [])
        secrets = org_secrets(db, project.organization_id)

        sources = [s for s in project.sources if s.enabled]
        log("info", f"Проект «{project.name}»: источников {len(sources)}, свежесть ≤{project.max_age_days} дн., "
                    f"модель {llm.model or 'авто'}" + (f", примеров 👍/👎: {len(examples)}" if examples else ""))
        if not sources:
            log("warn", "Нет включённых источников — включите хотя бы один в настройках проекта")

        seen_in_run: set[str] = set()
        for source in sources:
            check_cancel()
            plugin = REGISTRY.get(source.type)
            if not plugin:
                log("error", f"Неизвестный тип источника: {source.type}")
                continue
            log("info", f"▶ {source.name or source.type}")
            ctx = SourceContext(config=source.config or {}, region=project.region, timelimit=project.timelimit,
                                since=since, secrets=secrets, log=log)
            try:
                candidates = plugin().fetch(ctx)
            except SourceError as exc:
                stats["source_errors"] += 1
                _mark_source(db, source, error=str(exc))
                log("error", f"{source.type}: {exc}")
                continue
            except Exception as exc:  # a broken source must not kill the run
                stats["source_errors"] += 1
                _mark_source(db, source, error=repr(exc))
                log("error", f"{source.type}: непредвиденная ошибка: {exc!r}")
                continue
            _mark_source(db, source, items=len(candidates))
            if not candidates:
                log("warn", f"{source.name or source.type}: ничего не вернул — проверьте настройки источника")

            for cand in candidates:
                if stats["leads"] >= project.max_leads_per_run:
                    break
                url = cand.url
                if url in seen_in_run:
                    continue
                seen_in_run.add(url)
                stats["candidates"] += 1
                if url in known:
                    stats["skipped_seen"] += 1
                    continue
                # A tender notice IS the demand — no need to look for «подскажите» in it
                structured = cand.source in ("tenders",)
                ok, reason = prefilter_hit(
                    url, cand.title, cand.text, project.blocked_hosts or [],
                    demand_re, exclude_re, require_demand=not structured,
                )
                if not ok:
                    dropped[reason] += 1
                    continue
                check_cancel()
                # A forum link alone isn't actionable, and the feed date is the LAST REPLY:
                # open the thread to get the author, their profile, the full question and its real date
                enriched = enrich_forum_thread(url) if cand.platform == "forum" else {}
                if enriched.get("text"):
                    cand.text = enriched["text"]
                if enriched.get("author"):
                    cand.author = cand.author or enriched["author"]
                if enriched.get("posted_at"):
                    if cand.posted_at:
                        cand.extra["bumped_at"] = cand.posted_at.isoformat()  # last activity, for context
                    cand.posted_at = enriched["posted_at"]
                else:
                    cand.posted_at = cand.posted_at or extract_post_date(f"{cand.title} {cand.text}")

                if since and is_stale(cand.posted_at, project.max_age_days):
                    dropped["stale"] += 1
                    # remember it: otherwise every run downloads this old thread again
                    db.add(SeenUrl(project_id=project.id, url=url, verdict="stale", score=0.0))
                    db.commit()
                    known.add(url)
                    continue
                contacts = extract_contacts(url, cand.title, cand.text)
                contact_data = contacts.as_dict()
                contact_data["outreach"] = outreach_for(url, cand.platform, contact_data, enriched)
                if enriched.get("profile_url"):
                    contact_data["profile_url"] = enriched["profile_url"]
                payload = cand.to_dict() | {"contacts_summary": contacts.summary_line()}
                t0 = time.monotonic()
                verdict = evaluator.evaluate(payload)
                took = time.monotonic() - t0
                stats["evaluated"] += 1

                if verdict.get("error"):
                    stats["llm_errors"] += 1
                    log("warn", f"  ⚠ {verdict['reason']}")
                    continue

                is_lead = verdict["is_fit"] and verdict["score"] >= project.min_score
                db.add(SeenUrl(project_id=project.id, url=url, verdict="lead" if is_lead else "reject",
                               score=verdict["score"]))
                known.add(url)
                if is_lead:
                    lead = Lead(
                        organization_id=project.organization_id, project_id=project.id, run_id=run.id,
                        source=cand.source, platform=cand.platform, url=url, title=cand.title[:500],
                        text=cand.text, query=cand.query, posted_at=cand.posted_at, score=verdict["score"],
                        reason=verdict["reason"], segment=verdict["segment"],
                        interest_signal=verdict["interest_signal"],
                        display_name=verdict["display_name"] or cand.author[:200],
                        contact_hint=verdict["contact_hint"], contacts=contact_data,
                    )
                    db.add(lead)
                    db.commit()
                    stats["leads"] += 1
                    by_source[cand.source] += 1
                    log("lead", f"✓ {verdict['score']:.2f} [{cand.platform}] {verdict['reason']} ({took:.0f}с)")
                    dispatch_lead(db, lead, project, log)
                else:
                    db.commit()
                    stats["rejected"] += 1
                    log("info", f"  ✗ {verdict['score']:.2f} {cand.title[:70]} — {verdict['reason']} ({took:.0f}с)")

        run.status = "succeeded"
        log("info", f"Готово: лидов {stats['leads']}, отклонено моделью {stats['rejected']}, "
                    f"отсеяно фильтрами {sum(dropped.values())}, уже видели {stats['skipped_seen']}")
    except RunCancelled:
        run.status = "cancelled"
        log("warn", "Запуск остановлен пользователем")
    except RunBudgetExceeded:
        run.status = "succeeded"
        log("warn", f"Достигнут лимит времени запуска ({RUN_BUDGET_SECONDS // 60} мин) — завершаю с тем, что нашлось")
    except LlmUnavailable as exc:
        run.status = "failed"
        done, total = stats["evaluated"], stats["candidates"]
        hint = ("Квоты моделей исчерпаны. Найденное сохранено; повторите позже "
                "или переключите основную модель на локальную (MTPLX на вашем Mac) — у неё нет лимитов."
                if getattr(exc, "retryable", False) else
                "Проверьте адрес и ключ в Настройках → Модель.")
        run.error = f"{exc}\n\nОбработано {done} кандидатов из {total}. {hint}"
        log("error", f"{exc}")
        log("warn", f"Обработано {done} из {total} кандидатов. {hint}")
    except Exception as exc:
        db.rollback()
        run.status = "failed"
        run.error = repr(exc)[:2000]
        log("error", f"Сбой запуска: {exc!r}")
    finally:
        run.stats = {**stats, "dropped": dict(dropped), "leads_by_source": dict(by_source)}
        run.finished_at = utcnow()
        db.commit()
