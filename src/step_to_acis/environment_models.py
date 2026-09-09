from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from .spaceclaim_installations import SpaceClaimCandidate


CheckSeverity = Literal["required", "warning"]
CheckStatus = Literal["pass", "warning", "failure", "pending"]

REQUIRED_CHECK_IDS = (
    "windows_x64",
    "resources",
    "temp_writable",
    "state_writable",
    "spaceclaim_selected",
    "spaceclaim_version",
    "headless_capability",
)


@dataclass(frozen=True)
class CheckResult:
    check_id: str
    severity: CheckSeverity
    status: CheckStatus
    summary_zh: str
    reason_zh: str
    remediation_zh: str

    def __post_init__(self) -> None:
        if self.status == "failure" and (
            not self.reason_zh.strip() or not self.remediation_zh.strip()
        ):
            raise ValueError("failure checks require a reason and remediation")


@dataclass(frozen=True)
class EnvironmentState:
    candidates: tuple[SpaceClaimCandidate, ...] = ()
    selected: SpaceClaimCandidate | None = None
    checks: tuple[CheckResult, ...] = ()
    profile_path: Path | None = None
    report_path: Path | None = None
    busy: bool = False

    @property
    def can_enter_converter(self) -> bool:
        if self.busy or self.profile_path is None:
            return False
        by_id = {
            check.check_id: check
            for check in self.checks
            if check.severity == "required"
        }
        return all(
            check_id in by_id and by_id[check_id].status == "pass"
            for check_id in REQUIRED_CHECK_IDS
        )
