# Stub for cleanup_after_close function
# This function can be added to grid_eod_decision.py if needed.

def cleanup_after_close(book: dict) -> bool:
    """Remove unconfirmed buy orders and zero-qty rebuy residue.

    Called from the 15:20 EOD task after the session closes.  It does NOT
    touch the ledger's cash, qty, or cost_cash — only stale bookkeeping
    fields that could confuse the next day's plan().
    """
    changed = False
    # Example: clear historical unconfirmed buy orders from migration policy
    # policy = migration_policy()
    # if policy and policy.get("historical_unconfirmed_buy_orders"):
    #     policy["historical_unconfirmed_buy_orders"] = []
    #     (ROOT / "migration.json").write_text(
    #         json.dumps(policy, ensure_ascii=False, indent=2), encoding="utf-8"
    #     )
    #     changed = True
    # Example: remove zero‑qty rebuy entries
    # for pos in book.get("positions", {}).values():
    #     rebuy = pos.get("rebuy")
    #     if rebuy:
    #         kept = [r for r in rebuy if int(r.get("qty", 0)) > 0]
    #         if len(kept) != len(rebuy):
    #             pos["rebuy"] = kept
    #             changed = True
    return changed
