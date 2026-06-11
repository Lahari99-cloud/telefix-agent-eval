"""Deterministic mock tools used by the troubleshooting graph."""

import hashlib
from dataclasses import dataclass

from src.schemas import ServiceStatus, TelemetrySnapshot


def _stable_modem_id(account_id: str) -> str:
    digest = hashlib.sha256(account_id.encode("utf-8")).hexdigest()[:8].upper()
    return f"MODEM-{digest}"


@dataclass(frozen=True)
class MockTelemetryTool:
    """Produce realistic synthetic modem telemetry from reported symptoms."""

    name: str = "get_modem_telemetry"

    def invoke(
        self,
        account_id: str,
        symptoms: str,
        *,
        reset_applied: bool = False,
    ) -> TelemetrySnapshot:
        normalized = symptoms.lower()
        modem_id = _stable_modem_id(account_id)

        if reset_applied:
            return TelemetrySnapshot(
                modem_id=modem_id,
                status=ServiceStatus.ONLINE,
                downstream_power_dbmv=0.8,
                upstream_power_dbmv=43.0,
                snr_db=38.5,
                corrected_codewords=12,
                uncorrectable_codewords=0,
                last_seen_seconds_ago=4,
            )

        if any(term in normalized for term in ("offline", "no internet", "no connection")):
            return TelemetrySnapshot(
                modem_id=modem_id,
                status=ServiceStatus.OFFLINE,
                downstream_power_dbmv=-15.2,
                upstream_power_dbmv=54.1,
                snr_db=22.0,
                corrected_codewords=18500,
                uncorrectable_codewords=4200,
                last_seen_seconds_ago=900,
            )

        if any(
            term in normalized
            for term in ("slow", "drop", "intermittent", "latency", "buffer")
        ):
            return TelemetrySnapshot(
                modem_id=modem_id,
                status=ServiceStatus.DEGRADED,
                downstream_power_dbmv=-10.8,
                upstream_power_dbmv=51.5,
                snr_db=28.4,
                corrected_codewords=9200,
                uncorrectable_codewords=740,
                last_seen_seconds_ago=8,
            )

        return TelemetrySnapshot(
            modem_id=modem_id,
            status=ServiceStatus.ONLINE,
            downstream_power_dbmv=1.2,
            upstream_power_dbmv=42.5,
            snr_db=39.2,
            corrected_codewords=25,
            uncorrectable_codewords=0,
            last_seen_seconds_ago=5,
        )


@dataclass(frozen=True)
class MockRFResetTool:
    """Simulate a reset command without touching real network equipment."""

    name: str = "perform_rf_reset"

    def invoke(self, modem_id: str, *, consent: bool) -> str:
        if not consent:
            raise PermissionError("Reset requires explicit customer consent.")
        return f"Synthetic RF reset accepted for {modem_id}."

