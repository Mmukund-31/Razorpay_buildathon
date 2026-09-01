"""Runs all 4 baselines (ALWAYS_RETRY, STATIC_RULES, ML_ONLY, RECOVERYOS_FULL) against the
same held-out synthetic test set (ml/data/test.csv), reusing the REAL decision-making code —
the trained LightGBM model (ml/inference/predictor.py), the real
`app.services.optimizer_service` expected-value math, and the real `app.policies.policy_engine`
— for ML_ONLY and RECOVERYOS_FULL. Only the DB-persistence layer is out of scope here (no
live Postgres in this evaluation harness); the decision logic itself is unmodified production
code, imported directly from backend/app, run with `backend/.venv`'s Python (it has both the
ML stack and the app package installed) — see docs/decisions.md ADR-004.

Counterfactual outcomes: since each baseline may choose a DIFFERENT action than whichever one
the dataset's row happened to log, this asks "what would have happened under this baseline's
choice" using `ml.data.synthetic_generator.true_recovery_probability()` — the actual
ground-truth generating function of this synthetic world. That's legitimate here specifically
because the environment is fully known by construction; real logged data would need proper
off-policy correction to answer the same question honestly (see docs/ml-evaluation.md's
limitations section). `historical_recovery_rate` stands in for the latent
`true_recovery_propensity` the generator used internally (documented approximation — the CSV
doesn't persist that latent field, only its observable correlate).

ML scoring is batched across the whole test set (one Pipeline call per candidate action
across all rows, via `ml.inference.predictor.predict_proba_batch`) rather than row-by-row —
7,500 held-out rows x 7 actions x 2 ML-using baselines is 105,000 individual predictions,
which is fast in bulk and impractically slow one row at a time.

Writes results to `simulator/benchmark/results/latest.json` always, and to the
`experiments`/`experiment_results` tables when a database is reachable (best-effort — see
`_maybe_persist_to_db`). GET /api/analytics/benchmark reads only from the database, never
this JSON file, so what the dashboard shows is never out of sync with what's actually stored.
"""

import asyncio
import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = REPO_ROOT / "backend"
for path in (REPO_ROOT, BACKEND_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from ml.data.synthetic_generator import true_recovery_probability  # noqa: E402
from ml.evaluation.metrics import all_metrics  # noqa: E402
from ml.features.feature_definitions import FEATURE_NAMES  # noqa: E402
from ml.inference.predictor import ActiveModel, load_active_model, predict_proba_batch  # noqa: E402

DATA_DIR = REPO_ROOT / "ml" / "data"
RESULTS_DIR = Path(__file__).resolve().parent / "results"

ACTIONS = (
    "SMART_RETRY",
    "DELAYED_RETRY",
    "CUSTOMER_NOTIFICATION",
    "CUSTOMER_ACTION_REQUEST",
    "HINGLISH_VOICE",
    "ESCALATION",
    "NO_ACTION",
)

STATIC_RULES_TABLE = {
    "INSUFFICIENT_FUNDS": "DELAYED_RETRY",
    "AUTH_FAILURE": "CUSTOMER_ACTION_REQUEST",
    "GATEWAY_TIMEOUT": "SMART_RETRY",
    "BANK_DECLINE": "CUSTOMER_ACTION_REQUEST",
    "NETWORK_ERROR": "SMART_RETRY",
    "RISK_BLOCKED": "ESCALATION",
    "OTHER": "CUSTOMER_NOTIFICATION",
}
STATIC_RULES_MAX_ATTEMPTS = 3

_COST_TABLE = {
    "SMART_RETRY": 20, "DELAYED_RETRY": 20, "CUSTOMER_NOTIFICATION": 20,
    "CUSTOMER_ACTION_REQUEST": 20, "HINGLISH_VOICE": 500, "ESCALATION": 0, "NO_ACTION": 0,
}


def _value_tier_buckets(df: pd.DataFrame) -> pd.Series:
    """Terciles of the test set's own customer_lifetime_value distribution — self-calibrating
    to whatever scale the dataset happens to use, rather than a hardcoded absolute threshold.
    """
    q1, q2 = df["customer_lifetime_value"].quantile([1 / 3, 2 / 3])
    return df["customer_lifetime_value"].apply(lambda v: "low" if v <= q1 else ("mid" if v <= q2 else "high"))


def _simulate_outcomes_vectorized(df: pd.DataFrame, actions: pd.Series, seed: int) -> np.ndarray:
    """Counterfactual Bernoulli outcome for each row under `actions[i]` — one
    `true_recovery_probability` call per row (pure Python arithmetic, not model inference, so
    this loop is cheap regardless of row count)."""
    rng = np.random.default_rng(seed)
    outcomes = np.empty(len(df), dtype=bool)
    for i, (_, row) in enumerate(df.iterrows()):
        p = true_recovery_probability(
            failure_class=row["failure_class"],
            action=actions.iloc[i],
            retry_count=int(row["retry_count"]),
            historical_recovery_rate=float(row["historical_recovery_rate"]),
            has_history=float(row["historical_recovery_rate"]) != 0.3,
            value_tier=row["_value_tier"],
            true_recovery_propensity=float(row["historical_recovery_rate"]),
            last_response=row["previous_response_to_intervention"],
            time_since_failure_hours=float(row["time_since_failure_hours"]),
        )
        outcomes[i] = rng.random() < p
    return outcomes


def _score_all_actions_bulk(model: ActiveModel, df: pd.DataFrame) -> pd.DataFrame:
    """Returns a DataFrame shaped (len(df), len(ACTIONS)) of P(recovery) — one batched
    Pipeline call per action across every row, instead of one call per (row, action) pair.
    """
    base = df[[f for f in FEATURE_NAMES if f != "candidate_action"]]
    scores = {}
    for action in ACTIONS:
        rows = base.copy()
        rows["candidate_action"] = action
        scores[action] = predict_proba_batch(model, rows.to_dict("records"))
    return pd.DataFrame(scores, index=df.index)


def run_always_retry(df: pd.DataFrame, seed: int) -> list[dict]:
    actions = pd.Series(["SMART_RETRY"] * len(df), index=df.index)
    recovered = _simulate_outcomes_vectorized(df, actions, seed)
    return [
        {
            "action": "SMART_RETRY",
            "recovered": bool(recovered[i]),
            "amount": int(row["amount"]),
            "expected_recovery": int(row["amount"]) if recovered[i] else 0,
            "intervention_cost": _COST_TABLE["SMART_RETRY"],
            "abstained": False,
            "policy_rejected": False,
            "attempts": 1,
        }
        for i, (_, row) in enumerate(df.iterrows())
    ]


def run_static_rules(df: pd.DataFrame, seed: int) -> list[dict]:
    outcomes = []
    chosen_actions = []
    for _, row in df.iterrows():
        if int(row["retry_count"]) >= STATIC_RULES_MAX_ATTEMPTS:
            chosen_actions.append("NO_ACTION")
        else:
            chosen_actions.append(STATIC_RULES_TABLE[row["failure_class"]])
    actions = pd.Series(chosen_actions, index=df.index)
    recovered = _simulate_outcomes_vectorized(df, actions, seed)

    for i, (_, row) in enumerate(df.iterrows()):
        action = chosen_actions[i]
        if action == "NO_ACTION":
            outcomes.append(
                {"action": "NO_ACTION", "recovered": False, "amount": int(row["amount"]),
                 "expected_recovery": 0, "intervention_cost": 0, "abstained": True,
                 "policy_rejected": False, "attempts": int(row["retry_count"])}
            )
            continue
        outcomes.append(
            {
                "action": action,
                "recovered": bool(recovered[i]),
                "amount": int(row["amount"]),
                "expected_recovery": int(row["amount"]) if recovered[i] else 0,
                "intervention_cost": _COST_TABLE[action],
                "abstained": False,
                "policy_rejected": False,
                "attempts": 1,
            }
        )
    return outcomes


def run_ml_only(df: pd.DataFrame, model: ActiveModel, seed: int) -> tuple[list[dict], list[float]]:
    scores = _score_all_actions_bulk(model, df)
    best_actions = scores.idxmax(axis=1)
    best_probs = scores.max(axis=1)
    recovered = _simulate_outcomes_vectorized(df, best_actions, seed)

    outcomes = []
    for i, (_, row) in enumerate(df.iterrows()):
        action = best_actions.iloc[i]
        prob = float(best_probs.iloc[i])
        outcomes.append(
            {
                "action": action,
                "recovered": bool(recovered[i]),
                "amount": int(row["amount"]),
                "expected_recovery": prob * int(row["amount"]),
                "intervention_cost": _COST_TABLE[action],
                "abstained": False,
                "policy_rejected": False,
                "attempts": 1,
            }
        )
    return outcomes, best_probs.tolist()


def run_recoveryos_full(df: pd.DataFrame, model: ActiveModel, seed: int) -> tuple[list[dict], list[float]]:
    from app.core.config import get_settings
    from app.domain.enums import ActionType
    from app.policies.policy_engine import PolicyEngine
    from app.policies.rules import PolicyContext
    from app.services.optimizer_service import intervention_cost_paise, risk_cost_paise

    settings = get_settings()
    engine = PolicyEngine()
    now = datetime.now(UTC)

    scores = _score_all_actions_bulk(model, df)
    cost_by_action = {a: intervention_cost_paise(ActionType(a), settings) for a in ACTIONS}
    risk_by_action = {a: risk_cost_paise(ActionType(a), settings) for a in ACTIONS}

    chosen_actions, chosen_probs, expected_values = [], [], []
    for i, (_, row) in enumerate(df.iterrows()):
        amount = int(row["amount"])
        best_action, best_prob, best_ev = None, 0.0, float("-inf")
        for action in ACTIONS:
            probability = float(scores.iloc[i][action])
            ev = probability * amount - cost_by_action[action] - risk_by_action[action]
            if ev > best_ev:
                best_ev, best_action, best_prob = ev, action, probability
        chosen_actions.append(best_action)
        chosen_probs.append(best_prob)
        expected_values.append(best_ev)

    actions_series = pd.Series(chosen_actions, index=df.index)
    recovered = _simulate_outcomes_vectorized(df, actions_series, seed)

    outcomes = []
    for i, (_, row) in enumerate(df.iterrows()):
        action = chosen_actions[i]
        action_enum = ActionType(action)
        consent = (
            row["previous_response_to_intervention"] == "voice"
            if action_enum == ActionType.HINGLISH_VOICE
            else True
        )
        context = PolicyContext(
            already_recovered=False,
            attempt_count=int(row["retry_count"]),
            max_attempts=settings.max_retries,
            recovery_window_expires_at=None,
            now=now,
            customer_opted_out=False,
            candidate_action=action_enum,
            opportunity_type="ONE_TIME_PAYMENT_FAILURE",
            expected_value=expected_values[i],
            min_expected_value=settings.min_expected_value * int(row["amount"]),
            confidence=chosen_probs[i],
            min_confidence=settings.min_confidence,
            consent_recorded=consent,
        )
        decision = engine.evaluate(context)

        if not decision.allowed:
            outcomes.append(
                {"action": action, "recovered": False, "amount": int(row["amount"]),
                 "expected_recovery": 0, "intervention_cost": 0, "abstained": False,
                 "policy_rejected": True, "attempts": int(row["retry_count"])}
            )
            continue

        outcomes.append(
            {
                "action": action,
                "recovered": bool(recovered[i]),
                "amount": int(row["amount"]),
                "expected_recovery": chosen_probs[i] * int(row["amount"]),
                "intervention_cost": cost_by_action[action],
                "abstained": False,
                "policy_rejected": False,
                "attempts": 1,
            }
        )
    return outcomes, chosen_probs


async def _maybe_persist_to_db(results: dict) -> bool:
    try:
        from sqlalchemy import text

        from app.db.base import register_all_models
        from app.db.session import get_sessionmaker
        from app.domain.models.experiment import Experiment
        from app.domain.models.experiment_result import ExperimentResult

        register_all_models()
        session_factory = get_sessionmaker()
        async with session_factory() as session:
            await session.execute(text("SELECT 1"))
            for baseline_type, payload in results.items():
                experiment = Experiment(
                    name=f"benchmark-{baseline_type.lower()}-{int(time.time())}",
                    baseline_type=baseline_type,
                    dataset_ref=str(DATA_DIR / "test.csv"),
                    status="COMPLETED",
                )
                session.add(experiment)
                await session.flush()
                for metric_name, value in payload["metrics"].items():
                    session.add(
                        ExperimentResult(
                            experiment_id=experiment.id, metric_name=metric_name, metric_value=value
                        )
                    )
            await session.commit()
        return True
    except Exception:  # noqa: BLE001 — DB persistence is best-effort in this offline harness
        return False


def run_all_baselines(*, seed: int = 42, max_rows: int | None = None) -> dict:
    df = pd.read_csv(DATA_DIR / "test.csv")
    if max_rows is not None:
        df = df.iloc[:max_rows].copy()
    df["_value_tier"] = _value_tier_buckets(df)

    model = load_active_model()
    if model is None:
        raise RuntimeError("No active ML model — run ml/training/train_lightgbm.py first.")

    results: dict[str, dict] = {}

    results["ALWAYS_RETRY"] = {"metrics": all_metrics(run_always_retry(df, seed))}
    results["STATIC_RULES"] = {"metrics": all_metrics(run_static_rules(df, seed))}

    ml_only_outcomes, ml_only_probs = run_ml_only(df, model, seed)
    results["ML_ONLY"] = {"metrics": all_metrics(ml_only_outcomes, predicted_probabilities=ml_only_probs)}

    full_outcomes, full_probs = run_recoveryos_full(df, model, seed)
    results["RECOVERYOS_FULL"] = {"metrics": all_metrics(full_outcomes, predicted_probabilities=full_probs)}

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    (RESULTS_DIR / "latest.json").write_text(json.dumps(results, indent=2, default=str))

    persisted = asyncio.run(_maybe_persist_to_db(results))
    results["_persisted_to_db"] = persisted
    return results


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--max-rows", type=int, default=None)
    args = parser.parse_args()

    output = run_all_baselines(max_rows=args.max_rows)
    print(json.dumps(output, indent=2, default=str))
