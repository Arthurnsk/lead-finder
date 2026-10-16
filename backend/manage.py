"""Admin CLI.

    python manage.py gen-key
    python manage.py create-superadmin --email you@example.com
    python manage.py create-org --name "Demo Land Agency" --slug demo --owner you@example.com
    python manage.py import-niche --org demo --file /seed/niches/land_agency_demo.yaml
"""

from __future__ import annotations

import argparse
import getpass
import sys

from sqlalchemy import func, select


def _password(prompt: str = "Пароль (мин. 10 символов): ") -> str:
    pw = getpass.getpass(prompt)
    if len(pw) < 10:
        sys.exit("Пароль слишком короткий")
    return pw


def cmd_gen_key(_args):
    from cryptography.fernet import Fernet
    import secrets

    print(f"FERNET_KEY={Fernet.generate_key().decode()}")
    print(f"SECRET_KEY={secrets.token_urlsafe(48)}")


def cmd_create_superadmin(args):
    from app.db import SessionLocal
    from app.models import User
    from app.security import hash_password

    with SessionLocal() as db:
        user = db.scalar(select(User).where(func.lower(User.email) == args.email.lower()))
        pw = args.password or _password()
        if user:
            user.is_superadmin = True
            user.password_hash = hash_password(pw)
            print(f"Пользователь {user.email} стал суперадмином, пароль обновлён")
        else:
            db.add(User(email=args.email.lower(), full_name=args.name, password_hash=hash_password(pw),
                        is_superadmin=True))
            print(f"Создан суперадмин {args.email}")
        db.commit()


def cmd_create_org(args):
    from app.db import SessionLocal
    from app.models import Membership, Organization, User

    with SessionLocal() as db:
        owner = db.scalar(select(User).where(func.lower(User.email) == args.owner.lower()))
        if not owner:
            sys.exit(f"Нет пользователя {args.owner}; сначала create-superadmin или добавьте его")
        if db.scalar(select(Organization).where(Organization.slug == args.slug)):
            sys.exit(f"Организация {args.slug} уже есть")
        org = Organization(name=args.name, slug=args.slug)
        db.add(org)
        db.flush()
        db.add(Membership(user_id=owner.id, organization_id=org.id, role="owner"))
        db.commit()
        print(f"Организация {org.name} ({org.slug}) создана, владелец {owner.email}")


def cmd_import_niche(args):
    from app.db import SessionLocal
    from app.models import Organization, Project
    from app.niche_yaml import build_sources, parse_niche_yaml
    from app.schemas import ProjectCreate

    with SessionLocal() as db:
        org = db.scalar(select(Organization).where(Organization.slug == args.org))
        if not org:
            sys.exit(f"Нет организации {args.org}")
        fields, sources = parse_niche_yaml(open(args.file, encoding="utf-8").read())
        payload = ProjectCreate(**fields)
        if db.scalar(select(Project).where(Project.organization_id == org.id, Project.slug == payload.slug)):
            sys.exit(f"Проект {payload.slug} уже есть в {org.slug}")
        project = Project(organization_id=org.id, **payload.model_dump())
        db.add(project)
        db.flush()
        db.add_all(build_sources(project, sources))
        db.commit()
        print(f"Проект {project.name} импортирован в {org.slug}: {len(sources)} источника")


def cmd_import_legacy_leads(args):
    """Move leads from the Streamlit pilot's SQLite (database/leads.db) into a project."""
    import sqlite3
    from datetime import datetime, timezone

    from app.db import SessionLocal
    from app.models import Lead, Organization, Project

    with SessionLocal() as db:
        org = db.scalar(select(Organization).where(Organization.slug == args.org))
        project = org and db.scalar(select(Project).where(Project.organization_id == org.id,
                                                          Project.slug == args.project))
        if not project:
            sys.exit(f"Нет проекта {args.project} в организации {args.org}")
        con = sqlite3.connect(args.file)
        con.row_factory = sqlite3.Row
        rows = con.execute("SELECT * FROM leads").fetchall()
        existing = set(db.scalars(select(Lead.url).where(Lead.project_id == project.id)))
        added = 0
        for r in rows:
            if r["user_link"] in existing:
                continue
            keys = r.keys()
            found = r["found_at"] if "found_at" in keys and r["found_at"] else None
            text = r["comment_text"] or ""
            db.add(Lead(
                organization_id=org.id, project_id=project.id, source="legacy", platform=r["platform"] or "",
                url=r["user_link"], title=text.split("\n", 1)[0][:500], text=text, score=r["score"] or 0,
                reason=r["reason"] or "", interest_signal=r["interest_signal"] if "interest_signal" in keys else "",
                display_name=(r["display_name"] if "display_name" in keys else "") or "",
                feedback=(r["feedback"] if "feedback" in keys else "") or "",
                found_at=datetime.fromisoformat(found).replace(tzinfo=timezone.utc) if found
                else datetime.now(timezone.utc),
            ))
            added += 1
        db.commit()
        print(f"Перенесено лидов: {added} (пропущено дублей: {len(rows) - added})")


def cmd_telegram_login(args):
    """Interactive one-time login of YOUR Telegram account (the code from Telegram is typed by you)."""
    import os

    from telethon.sync import TelegramClient

    from app.db import SessionLocal
    from app.integrations.dispatch import org_secrets
    from app.models import Organization
    from app.sources.telegram_chat import SESSION_DIR, session_path

    api_id, api_hash = os.getenv("TELEGRAM_API_ID", ""), os.getenv("TELEGRAM_API_HASH", "")
    if args.org:
        with SessionLocal() as db:
            org = db.scalar(select(Organization).where(Organization.slug == args.org))
            if not org:
                sys.exit(f"Нет организации {args.org}")
            secrets = org_secrets(db, org.id)
            api_id = secrets.get("tg_api_id") or api_id
            api_hash = secrets.get("tg_api_hash") or api_hash
    if not (api_id and api_hash):
        sys.exit("Нет api_id/api_hash. Получите их на my.telegram.org и добавьте интеграцию "
                 "«Telegram-аккаунт» (Настройки → Интеграции) или задайте TELEGRAM_API_ID/HASH в .env")

    SESSION_DIR.mkdir(parents=True, exist_ok=True)
    print("Сейчас Telegram пришлёт код в приложение. Введите номер и код — они никуда не сохраняются,")
    print(f"сохраняется только файл сессии: {session_path()}.session\n")
    with TelegramClient(str(session_path()), int(api_id), api_hash) as client:
        me = client.get_me()
        print(f"Готово: вошли как {me.first_name} (@{me.username or me.id}). "
              "Теперь источник «Telegram-чаты» может читать ваши чаты.")


def main():
    ap = argparse.ArgumentParser(description="Lead Finder admin CLI")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("gen-key").set_defaults(fn=cmd_gen_key)

    p = sub.add_parser("create-superadmin")
    p.add_argument("--email", required=True)
    p.add_argument("--name", default="")
    p.add_argument("--password", help="лучше не передавать в аргументах — будет запрошен")
    p.set_defaults(fn=cmd_create_superadmin)

    p = sub.add_parser("create-org")
    p.add_argument("--name", required=True)
    p.add_argument("--slug", required=True)
    p.add_argument("--owner", required=True, help="email существующего пользователя")
    p.set_defaults(fn=cmd_create_org)

    p = sub.add_parser("import-niche")
    p.add_argument("--org", required=True, help="slug организации")
    p.add_argument("--file", required=True)
    p.set_defaults(fn=cmd_import_niche)

    p = sub.add_parser("import-legacy-leads")
    p.add_argument("--org", required=True)
    p.add_argument("--project", required=True)
    p.add_argument("--file", required=True, help="путь к leads.db пилота")
    p.set_defaults(fn=cmd_import_legacy_leads)

    p = sub.add_parser("telegram-login", help="однократный вход в Telegram для чтения чатов")
    p.add_argument("--org", help="slug организации, чьи api_id/api_hash использовать")
    p.set_defaults(fn=cmd_telegram_login)

    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
