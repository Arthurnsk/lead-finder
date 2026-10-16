"""Compare LLMs on labeled cases against a project's ICP.

    docker compose exec worker python -m app.eval --org demo --project land_agency_demo
    docker compose exec worker python -m app.eval --org demo --project land_agency_demo \\
        --base-url http://host.docker.internal:8081/v1 --model qwen3.6-35b-a3b
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path

import yaml
from sqlalchemy import select

from app.db import SessionLocal
from app.engine.dates import extract_post_date
from app.engine.evaluator import LeadEvaluator
from app.engine.llm import LlmClient
from app.engine.pipeline import llm_config_for
from app.models import Organization, Project

HERE = Path(__file__).resolve().parent


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--org", required=True)
    ap.add_argument("--project", required=True)
    ap.add_argument("--cases", default=None, help="YAML с разметкой (по умолчанию app/eval/<project>_cases.yaml)")
    ap.add_argument("--base-url")
    ap.add_argument("--model")
    ap.add_argument("--thinking", action="store_true", help="включить рассуждения модели (для сравнения)")
    args = ap.parse_args()

    with SessionLocal() as db:
        org = db.scalar(select(Organization).where(Organization.slug == args.org))
        project = org and db.scalar(select(Project).where(Project.organization_id == org.id,
                                                          Project.slug == args.project))
        if not project:
            raise SystemExit(f"Нет проекта {args.project} в {args.org}")
        cfg = llm_config_for(db, org.id)
    cfg.base_url = args.base_url or cfg.base_url
    cfg.model = args.model or cfg.model
    cfg.disable_thinking = not args.thinking
    llm = LlmClient(cfg)
    ok, why = llm.health()
    if not ok:
        raise SystemExit(f"LLM недоступна на {llm.base_url}: {why}")

    cases = yaml.safe_load(Path(args.cases or HERE / f"{args.project}_cases.yaml").read_text(encoding="utf-8"))
    ev = LeadEvaluator(llm, project)
    tp = fp = tn = fn = errors = 0
    times = []
    for i, case in enumerate(cases, 1):
        text = f"{case['title']} {case['snippet']}"
        posted = extract_post_date(text)
        cand = {"source": "eval", "platform": case.get("platform", "web"), "title": case["title"],
                "text": case["snippet"], "url": f"https://example.invalid/{i}", "query": "eval",
                "posted_at": posted.isoformat() if posted else ""}
        t0 = time.monotonic()
        v = ev.evaluate(cand)
        dt = time.monotonic() - t0
        times.append(dt)
        got = bool(v.get("is_fit")) and v.get("score", 0) >= project.min_score
        want = bool(case["expected"])
        if v.get("error"):
            errors, mark = errors + 1, "ERR"
        elif got == want:
            tp, tn = (tp + 1, tn) if want else (tp, tn + 1)
            mark = "ok "
        elif got:
            fp, mark = fp + 1, "FP "
        else:
            fn, mark = fn + 1, "FN "
        print(f"{mark} {dt:5.1f}s score={v.get('score', 0):.2f}  {case['title'][:60]} — {v.get('reason')}")

    n = len(cases)
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    print("\n" + "=" * 72)
    print(f"Модель: {llm.model} @ {llm.base_url}  thinking={'on' if args.thinking else 'off'}")
    print(f"Верно {tp + tn}/{n} · precision {precision:.0%} · recall {recall:.0%} · FP {fp} · FN {fn} · ошибок {errors}")
    print(f"Время на кандидата: среднее {sum(times) / n:.1f}s, макс {max(times):.1f}s")


if __name__ == "__main__":
    main()
