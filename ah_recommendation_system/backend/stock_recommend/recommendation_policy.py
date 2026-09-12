"""Conservative, pure recommendation policy and research-basket constraints."""
import math
from datetime import datetime, timedelta

MODEL_VERSION = "recommendation-policy-v1"
WEIGHTS = {"short": {"trend": .30, "flow": .25, "catalyst": .15, "quality": .15, "value": .05, "risk": -.10},
           "swing": {"trend": .25, "flow": .15, "catalyst": .15, "quality": .25, "value": .10, "risk": -.10},
           "medium": {"trend": .10, "flow": .05, "catalyst": .15, "quality": .35, "value": .25, "risk": -.15}}

def _score(c, horizon):
    vals, total, denom = {}, 0.0, 0.0
    for name, weight in WEIGHTS[horizon].items():
        f = c.get("factors", {}).get(name) or {}; raw = f.get("score")
        value = raw if isinstance(raw, (int, float)) and math.isfinite(raw) else None
        vals[name] = value
        if value is not None:
            total += weight * (100 - value if name == "risk" else value) * max(0.0, min(1.0, f.get("confidence", 0) * f.get("completeness", 0)))
            denom += abs(weight)
    return (round(total / denom, 2) if denom else None), vals

def build_decisions(candidates, *, as_of):
    out = []
    for c in candidates:
        sig = c.get("signals") or {}; quality = (c.get("quality") or {}).get("status", "degraded")
        scores = {}; factor_values = {}
        for h in WEIGHTS:
            scores[h], factor_values[h] = _score(c, h)
        evidence = c.get("evidence") or []
        support = [e for e in evidence if e.get("active") and e.get("direction") == "support"]
        contradictions = [e for e in evidence if e.get("active") and e.get("direction") == "contradict"]
        explicit_main = all(sig.get(k) is True for k in ("trend_confirmed", "relative_strength_improving", "volume_confirmed", "liquidity_ok")) and not sig.get("p0") and c.get("price") is not None and sig.get("support_price") is not None and sig.get("stop_price") is not None
        explicit_slow = sig.get("slow_variable_improving") is True and not sig.get("p0") and not sig.get("invalidated")
        if sig.get("invalidated"): state = "已失效"
        elif quality == "rejected" or sig.get("p0"): state = "回避"
        elif quality != "passed": state = "降级观察"
        elif explicit_main: state = "当前主攻"
        elif explicit_slow and scores.get("medium", 0) is not None and scores["medium"] >= 45: state = "可小仓埋伏"
        else: state = "等待触发"
        status = {"当前主攻":"有效", "右侧确认":"需确认", "可小仓埋伏":"需确认", "等待触发":"需确认", "降级观察":"降级观察", "回避":"回避", "已失效":"已失效"}[state]
        try: dt = datetime.fromisoformat(as_of.replace("Z", "+00:00")); review = (dt + timedelta(days=1)).isoformat()
        except Exception: review = as_of
        out.append({"candidate_id": c.get("candidate_id"), "symbol": c.get("symbol"), "market": c.get("market"), "theme": c.get("theme"), "state": state, "status_label": status, "horizon_scores": {h:{"score":scores[h],"factors":factor_values[h]} for h in WEIGHTS}, "model_version": MODEL_VERSION, "quality": c.get("quality"), "selected": state in ("当前主攻", "可小仓埋伏"), "evidence_refs": [e.get("evidence_id") for e in support], "supporting_evidence": support, "contradictions": contradictions, "trigger": "右侧确认趋势、量能与相对强度" if state != "已失效" else None, "invalidation": "跌破止损位或出现P0证伪", "verification_window": "1-5个交易日" if state == "当前主攻" else "10-30个交易日", "next_review_at": review, "execution_conditions": {k:sig[k] for k in ("support_price","stop_price") if sig.get(k) is not None}, "trial_position_limit": 0.2 if state == "可小仓埋伏" else None, "confidence": "high" if quality == "passed" and support else "low"})
    return out

def constrain_portfolio(decisions, candidates):
    seen, selected = set(), []
    for d in decisions:
        if not d.get("selected") or d.get("symbol") in seen: d["selected"] = False; continue
        seen.add(d.get("symbol")); selected.append(d)
    theme_counts = {}
    for d in selected: theme_counts[d.get("theme") or "unknown"] = theme_counts.get(d.get("theme") or "unknown", 0) + 1
    n = len(selected); weights = {}
    for d in selected:
        cap = min(0.2, 0.4 / theme_counts[d.get("theme") or "unknown"])
        d["model_weight"] = cap; weights[d.get("theme") or "unknown"] = weights.get(d.get("theme") or "unknown", 0) + cap
    return {"decisions": decisions, "constraints": {"scope":"MODEL research basket", "security_cap":0.2, "theme_cap":0.4, "theme_weights":weights, "cash_weight":max(0.0, 1-sum(d.get("model_weight",0) for d in selected)), "correlation_status":"unassessed_missing_data"}}
