"""Role -> tier -> provider routing, retries and cost ceilings (SYSTEM S4.3–S4.5)."""
from __future__ import annotations

import time
from dataclasses import dataclass, field

from . import providers
from .personas import Persona
from .providers import Message, Provider, ProviderError

TIERS = ["fast", "mid", "top"]


class BudgetExceeded(RuntimeError):
    pass


class RoleFailed(RuntimeError):
    pass


class ConfigError(ProviderError):
    """Missing or invalid model configuration: not retried, reported to the user."""


@dataclass
class CallResult:
    text: str
    tier: str
    model: str
    input_tokens: int
    output_tokens: int
    cost_usd: float
    duration_s: float
    attempts: int


@dataclass
class Router:
    config: dict
    overrides: dict[str, Provider] = field(default_factory=dict)  # tier -> provider (tests, dry runs)
    spent_usd: float = 0.0
    calls: int = 0

    def tier_for(self, persona: Persona) -> str:
        return self.config.get("roles", {}).get(persona.name, persona.tier)

    def _spec(self, tier: str) -> dict:
        spec = self.config.get("models", {}).get(tier)
        if not spec:
            raise ConfigError(f"no model configured for tier '{tier}' in .sparkwright/config.yaml")
        return spec

    def _provider(self, tier: str) -> tuple[Provider, str, dict]:
        if tier in self.overrides:
            return self.overrides[tier], f"override-{tier}", {}
        spec = self._spec(tier)
        return providers.make(spec), str(spec.get("model", "")), spec

    @staticmethod
    def _cost(spec: dict, usage) -> float:
        price = spec.get("price_per_mtok") or {}
        return (usage.input_tokens * float(price.get("input", 0)) + usage.output_tokens * float(price.get("output", 0))) / 1e6

    def max_calls(self) -> int:
        return int(self.config.get("budgets", {}).get("max_calls_per_run", 40) or 40)

    def _priced(self, tier: str) -> bool:
        if tier in self.overrides:
            return True  # tests and dry runs
        spec = self.config.get("models", {}).get(tier) or {}
        price = spec.get("price_per_mtok") or {}
        try:  # a zero price would disable both the dollar ceiling and the call cap
            return float(price.get("input", 0)) > 0 or float(price.get("output", 0)) > 0
        except (TypeError, ValueError, AttributeError):
            return False

    def ceiling(self) -> float:
        return float(self.config.get("budgets", {}).get("per_run_usd", 0) or 0)

    def call(self, persona: Persona, user_content: str, max_tokens: int = 4000, force: bool = False) -> CallResult:
        """Call a role; on failure escalate one tier (or retry at `top`) once (S4.4).

        `force` bypasses the run ceiling so the minimum number of Inspectors can always run (S4.5).
        """
        tier = self.tier_for(persona)
        attempts = 0
        last_error: Exception | None = None
        for attempt_tier in [tier, self._escalate(tier) or tier]:
            if attempt_tier is None:
                break
            attempts += 1
            ceiling = self.ceiling()
            estimate = self.spent_usd / self.calls if self.calls else 0.0
            if ceiling and not force and (self.spent_usd >= ceiling or self.spent_usd + estimate > ceiling):
                raise BudgetExceeded(f"run cost ceiling ${ceiling:.2f} would be exceeded")
            if not force and not self._priced(attempt_tier) and self.calls >= self.max_calls():
                # D007: without prices the dollar ceiling cannot work, so the run is capped by number of calls
                raise BudgetExceeded(f"no price configured for tier '{attempt_tier}'; stopped at the "
                                     f"{self.max_calls()}-call limit (budgets.max_calls_per_run)")
            try:
                provider, model, spec = self._provider(attempt_tier)
            except providers.ProviderError as exc:
                if isinstance(exc, ConfigError):
                    raise
                last_error = exc
                continue
            msgs = [Message("system", persona.system_prompt()), Message("user", user_content)]
            start = time.monotonic()
            try:
                text, usage = provider.complete(msgs, model, max_tokens)
            except ProviderError as exc:
                last_error = exc
                continue
            cost = self._cost(spec, usage)
            self.spent_usd += cost
            self.calls += 1
            return CallResult(text, attempt_tier, model, usage.input_tokens, usage.output_tokens, cost,
                              round(time.monotonic() - start, 3), attempts)
        raise RoleFailed(f"{persona.name} failed after {attempts} attempt(s): {last_error}")

    @staticmethod
    def _escalate(tier: str) -> str | None:
        i = TIERS.index(tier) if tier in TIERS else 1
        return TIERS[i + 1] if i + 1 < len(TIERS) else None
