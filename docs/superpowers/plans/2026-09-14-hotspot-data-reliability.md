# Hotspot mapping and data collection reliability

Implement the accepted conversation plan in the existing feature checkout, preserving pre-existing user edits. Do not send notifications or modify trading state during validation.

## Implementation decisions

- Use verified security-code membership for hotspot writeback. Broad sector groups remain display context; battery/car/oil-shipping scoring cannot be inferred from generic renewable-energy/shipping membership.
- Preserve baseline composite/model scores and eligibility. Hotspot component 0–0.15 contributes at most 0.015 to eligible ranking (1.5 points on a 100-point display), without stacking across themes. This resolves the prior ambiguous 10% description as component weight 0.10.
- Track matched-but-rejected candidates and reasons; matching is not investment confirmation. Validate freshness, direction, and market confirmation before granting ranking bonus.
- Reuse existing router/cache infrastructure. Bound third-party caller waits and concurrent pending work; do not claim thread cancellation terminates an underlying socket request. Preserve Baostock session serialization and price adjustment provenance.
- Surface partial-source failures and finite stale-cache age in report health. Missing optional ETF/cross-market data degrades its section; missing core evidence prevents formal picks.

## Work and verification

- Hotspot agent: mapping, candidate fields, baseline-preserving selector, report explanations and tests.
- Data agent: error categories, cache/circuit policy, production collector/ETF integration and tests.
- Coordinator: card/frontend presentation, integration review, targeted and full backend unittest validation; live run without push and isolated mock validation.
- Review implementation independently before completion. Report remaining limitations and actual validation results.
