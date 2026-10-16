import { CheckCircle2, Circle, Clock, Loader2, OctagonX, ThumbsDown, ThumbsUp, XCircle } from "lucide-react";
import type { LeadStatus, Run } from "../api/types";
import { LEAD_STATUS, RUN_STATUS } from "../lib/format";
import { Badge } from "./ui";

export function RunStatusBadge({ status }: { status: Run["status"] }) {
  const map = {
    queued: { tone: "neutral", icon: <Clock className="size-3" /> },
    running: { tone: "accent", icon: <Loader2 className="size-3 animate-spin" /> },
    succeeded: { tone: "good", icon: <CheckCircle2 className="size-3" /> },
    failed: { tone: "bad", icon: <XCircle className="size-3" /> },
    cancelled: { tone: "warn", icon: <OctagonX className="size-3" /> },
  } as const;
  const { tone, icon } = map[status];
  return (
    <Badge tone={tone} icon={icon}>
      {RUN_STATUS[status]}
    </Badge>
  );
}

export function LeadStatusBadge({ status }: { status: LeadStatus }) {
  const tone = ({ new: "accent", in_progress: "warn", contacted: "neutral", won: "good", lost: "neutral", spam: "bad" } as const)[
    status
  ];
  return (
    <Badge tone={tone} icon={<Circle className="size-2 fill-current" />}>
      {LEAD_STATUS[status]}
    </Badge>
  );
}

export function ScorePill({ score }: { score: number }) {
  const tone = score >= 0.8 ? "good" : score >= 0.65 ? "accent" : "neutral";
  return <Badge tone={tone}>{Math.round(score * 100)}%</Badge>;
}

export function FeedbackIcon({ feedback }: { feedback: string }) {
  if (feedback === "good") return <ThumbsUp className="size-3.5 text-good" aria-label="Хороший лид" />;
  if (feedback === "bad") return <ThumbsDown className="size-3.5 text-bad" aria-label="Плохой лид" />;
  return null;
}
