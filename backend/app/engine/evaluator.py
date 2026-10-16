"""Strict lead qualification — no invented people/URLs/contacts."""

from __future__ import annotations

from datetime import date
from typing import Any

from app.engine.llm import LlmClient, LlmUnavailable
from app.models import Project

EVAL_SYSTEM = """
Ты строгий квалификатор лидов для компании «{name}» ({site}).
Что продаёт компания: {offer}

Правила анти-фейка (обязательны):
1) Оценивай ТОЛЬКО переданные поля. Ничего не выдумывай и не дополняй «из знаний».
2) is_fit=true только если виден АКТУАЛЬНЫЙ СПРОС автора (ищу/куплю/нужна помощь/как оформить/что делать СЕЙЧАС),
   и эту задачу решают услуги компании.
3) НЕ лид: рассказ о прошлом опыте без новой задачи, обзоры, SEO-статьи, каталоги, агентства, курсы, блогеры, новости.
4) Заголовок-инструкция («Как купить…», «Пошаговая…») без личного вопроса в тексте — is_fit=false.
5) Сегодня {today}. Возраст поста система проверяет сама (допустимо {max_age} дней), заново дату не суди.
   stale=true ставь, только если из ТЕКСТА видно, что вопрос уже решён или потерял смысл.
6) display_name / contact_hint только из текста; иначе пустые строки. Не изобретай телефон/email/@ник.
7) evidence_ok=false если данных мало, чтобы понять, чего хочет автор.
""".strip()

RESULT_SCHEMA = """{
  "is_fit": true/false,
  "score": 0.0-1.0,
  "reason": "до 18 слов",
  "segment": "короткая метка сегмента из ICP или пусто",
  "display_name": "имя или канал из текста или пусто",
  "contact_hint": "ник/город/@handle из текста или пусто",
  "interest_signal": "коротко что именно интересует",
  "is_likely_spam_or_competitor": true/false,
  "stale": true/false,
  "evidence_ok": true/false
}"""


def format_examples(examples: list[dict], limit: int = 14) -> str:
    lines = []
    for ex in examples[-limit:]:
        text = str(ex.get("text") or "").replace("\n", " ")[:300]
        verdict = "ЛИД" if ex.get("is_fit") else "НЕ ЛИД"
        why = f" — {ex['why']}" if ex.get("why") else ""
        lines.append(f"- [{verdict}] {text}{why}")
    return "\n".join(lines)


class LeadEvaluator:
    def __init__(self, llm: LlmClient, project: Project, feedback_examples: list[dict] | None = None):
        self.llm = llm
        self.project = project
        self.examples = [*(project.examples or []), *(feedback_examples or [])]

    def _system(self) -> str:
        p = self.project
        return EVAL_SYSTEM.format(
            name=p.name, site=p.site or "—", offer=p.offer or "—",
            today=date.today().isoformat(), max_age=p.max_age_days,
        )

    def evaluate(self, cand: dict) -> dict[str, Any]:
        examples = (
            f"\nЭталонные примеры разметки (ориентируйся на них):\n{format_examples(self.examples)}\n"
            if self.examples else ""
        )
        user = f"""
ICP:
{self.project.icp}
{examples}
Кандидат из РЕАЛЬНОГО источника (не выдумывай поля):
- source: {cand.get('source')} / {cand.get('platform')}
- title: {cand.get('title')}
- url: {cand.get('url')}
- text: {(cand.get('text') or '')[:1500]}
- posted_at: {cand.get('posted_at') or 'неизвестно'}
- author: {cand.get('author') or 'неизвестно'}
- query: {cand.get('query')}
- extracted_contacts: {cand.get('contacts_summary') or 'нет'}

Верни JSON:
{RESULT_SCHEMA}
""".strip()
        try:
            data = self.llm.chat_json(self._system(), user, max_tokens=500)
        except LlmUnavailable:
            raise
        except Exception as exc:
            return {"is_fit": False, "score": 0.0, "reason": f"Сбой оценки: {exc}"[:240], "error": True}

        score = max(0.0, min(1.0, float(data.get("score") or 0)))
        evidence_ok = bool(data.get("evidence_ok", True))
        spam = bool(data.get("is_likely_spam_or_competitor", False))
        stale = bool(data.get("stale", False))
        return {
            "is_fit": bool(data.get("is_fit")) and evidence_ok and not spam and not stale and score >= 0.55,
            "score": score,
            "reason": str(data.get("reason") or "")[:240],
            "segment": str(data.get("segment") or "")[:80],
            "display_name": str(data.get("display_name") or "")[:200],
            "contact_hint": str(data.get("contact_hint") or "")[:200],
            "interest_signal": str(data.get("interest_signal") or "")[:300],
            "spam": spam,
            "stale": stale,
            "evidence_ok": evidence_ok,
        }
