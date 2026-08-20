from __future__ import annotations

from bisect import bisect_left, bisect_right
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from enum import StrEnum
from typing import Protocol

from app.backtesting.models import Bar
from app.core.clock import ensure_utc
from app.core.decimal import ONE, ZERO, as_decimal


class ConversionUnavailableError(RuntimeError):
    """Raised when a required causal quote-to-GBP observation is unavailable."""


class ConversionMode(StrEnum):
    CAUSAL_COMPLETED_BARS = "CAUSAL_COMPLETED_BARS"
    STATIC_EXPLICIT = "STATIC_EXPLICIT"


class ConversionBoundary(StrEnum):
    AT_OR_BEFORE = "AT_OR_BEFORE"
    STRICTLY_BEFORE = "STRICTLY_BEFORE"


@dataclass(frozen=True, slots=True)
class ConversionStalenessPolicy:
    """Maximum age of conversion observations used by research simulation.

    Intraday observations get a short normal tolerance.  A separate weekend
    tolerance permits the normal Friday-to-Sunday/Monday market closure but
    does not make an old weekday observation valid indefinitely.
    """

    policy_id: str = "conversion-staleness-v1"
    # Seven days bridges documented weekend/exchange-holiday gaps in the
    # cached daily conversion series (including the five-day Easter 2025 gap)
    # while still rejecting an indefinitely carried close.
    daily_max_age: timedelta = timedelta(days=7)
    hourly_max_age: timedelta = timedelta(hours=3)
    thirty_minute_max_age: timedelta = timedelta(minutes=90)
    fifteen_minute_max_age: timedelta = timedelta(minutes=45)
    weekend_max_age: timedelta = timedelta(hours=72)

    def maximum_age(
        self,
        interval: str,
        *,
        observed_at: datetime,
        requested_at: datetime,
    ) -> timedelta:
        observed = ensure_utc(observed_at)
        requested = ensure_utc(requested_at)
        base = {
            "1d": self.daily_max_age,
            "1h": self.hourly_max_age,
            "30m": self.thirty_minute_max_age,
            "15m": self.fifteen_minute_max_age,
        }.get(interval, self.hourly_max_age)
        if interval != "1d" and observed.weekday() == 4 and requested.weekday() in {5, 6, 0}:
            return max(base, self.weekend_max_age)
        return base


@dataclass(frozen=True, slots=True)
class ConversionLeg:
    instrument_id: str
    observed_at: datetime
    close: Decimal
    maximum_age: timedelta | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "observed_at", ensure_utc(self.observed_at))
        object.__setattr__(self, "close", as_decimal(self.close))
        if self.close <= ZERO:
            raise ValueError("conversion leg close must be positive")


@dataclass(frozen=True, slots=True)
class ConversionQuote:
    source_currency: str
    rate_to_gbp: Decimal
    requested_at: datetime
    boundary: ConversionBoundary
    mode: ConversionMode
    formula: str
    legs: tuple[ConversionLeg, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "source_currency", self.source_currency.upper())
        object.__setattr__(self, "rate_to_gbp", as_decimal(self.rate_to_gbp))
        object.__setattr__(self, "requested_at", ensure_utc(self.requested_at))
        object.__setattr__(self, "boundary", ConversionBoundary(self.boundary))
        object.__setattr__(self, "mode", ConversionMode(self.mode))
        if self.rate_to_gbp <= ZERO:
            raise ValueError("conversion rate must be positive")

    def audit_details(self) -> dict[str, object]:
        return {
            "source_currency": self.source_currency,
            "target_currency": "GBP",
            "rate_to_gbp": str(self.rate_to_gbp),
            "requested_at": self.requested_at.isoformat(),
            "boundary": self.boundary.value,
            "mode": self.mode.value,
            "formula": self.formula,
            "legs": [
                {
                    "instrument_id": leg.instrument_id,
                    "observed_at": leg.observed_at.isoformat(),
                    "close": str(leg.close),
                    "age_seconds": int((self.requested_at - leg.observed_at).total_seconds()),
                    "maximum_age_seconds": (
                        None if leg.maximum_age is None else int(leg.maximum_age.total_seconds())
                    ),
                }
                for leg in self.legs
            ],
        }


class QuoteToGbpResolver(Protocol):
    def resolve(
        self,
        source_currency: str,
        *,
        as_of: datetime,
        boundary: ConversionBoundary = ConversionBoundary.AT_OR_BEFORE,
    ) -> ConversionQuote: ...


def modeled_bar_open(completed_at: datetime, interval: str) -> datetime:
    """Return the modeled opening instant for a completion-labelled bar."""

    try:
        duration = {
            "15m": timedelta(minutes=15),
            "30m": timedelta(minutes=30),
            "1h": timedelta(hours=1),
            "1d": timedelta(days=1),
        }[interval]
    except KeyError as exc:
        raise ValueError(f"unsupported bar interval for modeled open: {interval}") from exc
    return ensure_utc(completed_at) - duration


@dataclass(frozen=True, slots=True)
class ConversionTimingPolicy:
    """Versioned timing contract for conversion observations in simulation.

    Entries and every simulated exit freeze conversion at the modeled bar open.
    This is conservative for intrabar and close-labelled exits and prevents an
    FX bar that completes during the execution bar from leaking into its open.
    Completion-time marks may use observations completed by the mark instant.
    """

    policy_id: str = "modeled-bar-open-conversion-v1"

    def execution_as_of(self, bar: Bar, *, interval: str) -> datetime:
        return modeled_bar_open(bar.timestamp, interval)

    def resolve_execution(
        self,
        resolver: QuoteToGbpResolver,
        source_currency: str,
        bar: Bar,
        *,
        interval: str,
    ) -> ConversionQuote:
        return resolver.resolve(
            source_currency,
            as_of=self.execution_as_of(bar, interval=interval),
            boundary=ConversionBoundary.AT_OR_BEFORE,
        )

    def audit_details(self, *, interval: str | None = None) -> dict[str, object]:
        return {
            "policy_id": self.policy_id,
            "bar_interval": interval,
            "entry_conversion_anchor": "modeled bar open (completion minus interval)",
            "intrabar_exit_conversion_anchor": "modeled bar open (conservative freeze)",
            "bar_close_exit_conversion_anchor": "modeled bar open (conservative freeze)",
            "mark_conversion_anchor": "bar completion",
            "execution_boundary": ConversionBoundary.AT_OR_BEFORE.value,
        }


@dataclass(frozen=True, slots=True)
class QuoteToGbpConversionPolicy:
    mode: ConversionMode = ConversionMode.CAUSAL_COMPLETED_BARS
    static_rates_to_gbp: tuple[tuple[str, Decimal], ...] = ()
    staleness: ConversionStalenessPolicy = ConversionStalenessPolicy()
    policy_id: str = "quote-to-gbp-v1"

    def __post_init__(self) -> None:
        object.__setattr__(self, "mode", ConversionMode(self.mode))
        normalized = tuple(
            sorted(
                (currency.upper(), as_decimal(rate)) for currency, rate in self.static_rates_to_gbp
            )
        )
        if any(rate <= ZERO for _, rate in normalized):
            raise ValueError("static conversion rates must be positive")
        if len({currency for currency, _ in normalized}) != len(normalized):
            raise ValueError("static conversion currencies must be unique")
        if self.mode is ConversionMode.CAUSAL_COMPLETED_BARS and normalized:
            raise ValueError("causal conversion policy cannot contain static fallback rates")
        if self.mode is ConversionMode.STATIC_EXPLICIT and not normalized:
            raise ValueError("explicit static conversion policy requires rates")
        object.__setattr__(self, "static_rates_to_gbp", normalized)

    @classmethod
    def causal(
        cls,
        *,
        staleness: ConversionStalenessPolicy | None = None,
    ) -> QuoteToGbpConversionPolicy:
        return cls(staleness=staleness or ConversionStalenessPolicy())

    @classmethod
    def explicit_static(
        cls,
        rates_to_gbp: Mapping[str, Decimal | str | int],
    ) -> QuoteToGbpConversionPolicy:
        return cls(
            mode=ConversionMode.STATIC_EXPLICIT,
            static_rates_to_gbp=tuple(
                (currency, as_decimal(rate)) for currency, rate in rates_to_gbp.items()
            ),
        )

    def required_instruments(self, quote_currencies: Sequence[str]) -> tuple[str, ...]:
        if self.mode is ConversionMode.STATIC_EXPLICIT:
            return ()
        currencies = {currency.upper() for currency in quote_currencies}
        required: set[str] = set()
        if currencies & {"USD", "JPY"}:
            required.add("GBPUSD")
        if "EUR" in currencies:
            required.add("EURGBP")
        if "JPY" in currencies:
            required.add("USDJPY")
        unsupported = currencies - {"GBP", "USD", "EUR", "JPY"}
        if unsupported:
            raise ConversionUnavailableError(
                f"no causal quote-to-GBP path for currencies: {sorted(unsupported)}"
            )
        return tuple(sorted(required))

    def build(
        self,
        completed_bars: Mapping[str, Sequence[Bar]],
        *,
        interval: str,
    ) -> QuoteToGbpResolver:
        if self.mode is ConversionMode.STATIC_EXPLICIT:
            return ExplicitStaticQuoteToGbpResolver(self)
        return CausalQuoteToGbpResolver(completed_bars, interval=interval, policy=self)

    def audit_details(self) -> dict[str, object]:
        return {
            "policy_id": self.policy_id,
            "mode": self.mode.value,
            "static_rates_to_gbp": {
                currency: str(rate) for currency, rate in self.static_rates_to_gbp
            },
            "staleness": {
                "policy_id": self.staleness.policy_id,
                "daily_max_age_seconds": int(self.staleness.daily_max_age.total_seconds()),
                "hourly_max_age_seconds": int(self.staleness.hourly_max_age.total_seconds()),
                "thirty_minute_max_age_seconds": int(
                    self.staleness.thirty_minute_max_age.total_seconds()
                ),
                "fifteen_minute_max_age_seconds": int(
                    self.staleness.fifteen_minute_max_age.total_seconds()
                ),
                "weekend_max_age_seconds": int(self.staleness.weekend_max_age.total_seconds()),
            },
        }


class CausalQuoteToGbpResolver:
    def __init__(
        self,
        completed_bars: Mapping[str, Sequence[Bar]],
        *,
        interval: str,
        policy: QuoteToGbpConversionPolicy | None = None,
    ) -> None:
        self.policy = policy or QuoteToGbpConversionPolicy.causal()
        if self.policy.mode is not ConversionMode.CAUSAL_COMPLETED_BARS:
            raise ValueError("causal resolver requires a causal conversion policy")
        self.interval = interval
        self.completed_bars = {
            instrument_id: tuple(sorted(bars, key=lambda bar: bar.timestamp))
            for instrument_id, bars in completed_bars.items()
        }
        self._timestamps = {
            instrument_id: tuple(bar.timestamp for bar in bars)
            for instrument_id, bars in self.completed_bars.items()
        }

    def resolve(
        self,
        source_currency: str,
        *,
        as_of: datetime,
        boundary: ConversionBoundary = ConversionBoundary.AT_OR_BEFORE,
    ) -> ConversionQuote:
        currency = source_currency.upper()
        requested = ensure_utc(as_of)
        boundary = ConversionBoundary(boundary)
        if currency == "GBP":
            return ConversionQuote(
                currency,
                ONE,
                requested,
                boundary,
                ConversionMode.CAUSAL_COMPLETED_BARS,
                "GBP identity",
            )
        if currency == "USD":
            gbpusd = self._leg("GBPUSD", requested, boundary)
            return ConversionQuote(
                currency,
                ONE / gbpusd.close,
                requested,
                boundary,
                ConversionMode.CAUSAL_COMPLETED_BARS,
                "1 / GBPUSD",
                (gbpusd,),
            )
        if currency == "EUR":
            eurgbp = self._leg("EURGBP", requested, boundary)
            return ConversionQuote(
                currency,
                eurgbp.close,
                requested,
                boundary,
                ConversionMode.CAUSAL_COMPLETED_BARS,
                "EURGBP",
                (eurgbp,),
            )
        if currency == "JPY":
            gbpusd = self._leg("GBPUSD", requested, boundary)
            usdjpy = self._leg("USDJPY", requested, boundary)
            return ConversionQuote(
                currency,
                ONE / (gbpusd.close * usdjpy.close),
                requested,
                boundary,
                ConversionMode.CAUSAL_COMPLETED_BARS,
                "1 / (GBPUSD * USDJPY)",
                (gbpusd, usdjpy),
            )
        raise ConversionUnavailableError(f"no causal quote-to-GBP path for {currency}")

    def _leg(
        self,
        instrument_id: str,
        requested: datetime,
        boundary: ConversionBoundary,
    ) -> ConversionLeg:
        bars = self.completed_bars.get(instrument_id, ())
        timestamps = self._timestamps.get(instrument_id, ())
        index = (
            bisect_right(timestamps, requested)
            if boundary is ConversionBoundary.AT_OR_BEFORE
            else bisect_left(timestamps, requested)
        ) - 1
        if index < 0:
            comparator = "at or before" if boundary is ConversionBoundary.AT_OR_BEFORE else "before"
            raise ConversionUnavailableError(
                f"{instrument_id} has no completed conversion bar {comparator} "
                f"{requested.isoformat()}"
            )
        bar = bars[index]
        maximum_age = self.policy.staleness.maximum_age(
            self.interval,
            observed_at=bar.timestamp,
            requested_at=requested,
        )
        age = requested - bar.timestamp
        if age > maximum_age:
            raise ConversionUnavailableError(
                f"{instrument_id} conversion bar is stale: age={age}, maximum={maximum_age}"
            )
        return ConversionLeg(instrument_id, bar.timestamp, bar.close, maximum_age)


class ExplicitStaticQuoteToGbpResolver:
    def __init__(self, policy: QuoteToGbpConversionPolicy) -> None:
        if policy.mode is not ConversionMode.STATIC_EXPLICIT:
            raise ValueError("static resolver requires explicit static policy")
        self.policy = policy
        self.rates = dict(policy.static_rates_to_gbp)

    def resolve(
        self,
        source_currency: str,
        *,
        as_of: datetime,
        boundary: ConversionBoundary = ConversionBoundary.AT_OR_BEFORE,
    ) -> ConversionQuote:
        currency = source_currency.upper()
        requested = ensure_utc(as_of)
        boundary = ConversionBoundary(boundary)
        rate = ONE if currency == "GBP" else self.rates.get(currency)
        if rate is None:
            raise ConversionUnavailableError(
                f"explicit static quote-to-GBP rate is missing for {currency}"
            )
        return ConversionQuote(
            currency,
            rate,
            requested,
            boundary,
            ConversionMode.STATIC_EXPLICIT,
            "explicit configured static rate; no historical quote claim",
        )
