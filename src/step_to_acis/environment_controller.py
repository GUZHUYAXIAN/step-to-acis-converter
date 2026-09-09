from collections.abc import Callable, Sequence
import os
from pathlib import Path
import struct
import sys
import tempfile
import uuid

from .capability_cache import (
    CachedCapability,
    ExecutableIdentity,
    cache_path,
    executable_identity,
    load_cached_capability,
    load_selected_executable,
    save_selected_executable,
)
from .environment_models import CheckResult, EnvironmentState
from .probe_service import ProbeServiceOutcome, run_model_free_probe
from .runtime_paths import RuntimePaths
from .spaceclaim_installations import (
    SpaceClaimCandidate,
    discover_spaceclaim,
    validate_manual_selection,
)


def _default_discoverer(previous: Path | None) -> Sequence[SpaceClaimCandidate]:
    return discover_spaceclaim(previous=previous)


class EnvironmentController:
    def __init__(
        self,
        paths: RuntimePaths,
        *,
        windows_x64_probe: Callable[[], bool] | None = None,
        resource_probe: Callable[[RuntimePaths], bool] | None = None,
        temp_writable_probe: Callable[[Path], bool] | None = None,
        state_writable_probe: Callable[[Path], bool] | None = None,
        discoverer: Callable[[Path | None], Sequence[SpaceClaimCandidate]] = _default_discoverer,
        manual_classifier: Callable[[Path], SpaceClaimCandidate] = validate_manual_selection,
        identity_builder: Callable[[SpaceClaimCandidate], ExecutableIdentity] = executable_identity,
        cache_loader: Callable[[Path, ExecutableIdentity], CachedCapability | None] = load_cached_capability,
        probe_service: Callable[[SpaceClaimCandidate, RuntimePaths], ProbeServiceOutcome] = run_model_free_probe,
        previous_loader: Callable[[Path], Path | None] = load_selected_executable,
        selected_saver: Callable[[Path, ExecutableIdentity], None] = save_selected_executable,
    ) -> None:
        self.paths = paths
        self._windows_x64_probe = windows_x64_probe or _is_windows_x64
        self._resource_probe = resource_probe or _resources_exist
        self._temp_writable_probe = temp_writable_probe or _writable_directory
        self._state_writable_probe = state_writable_probe or _writable_directory
        self._discoverer = discoverer
        self._manual_classifier = manual_classifier
        self._identity_builder = identity_builder
        self._cache_loader = cache_loader
        self._probe_service = probe_service
        self._previous_loader = previous_loader
        self._selected_saver = selected_saver
        self._selected_path = paths.environment_root / "selected-spaceclaim.json"
        self._state = EnvironmentState()

    @property
    def state(self) -> EnvironmentState:
        return self._state

    def scan(self) -> EnvironmentState:
        previous = self._previous_loader(self._selected_path)
        candidates = tuple(self._discoverer(previous))
        selected = _preferred_eligible(candidates, previous)
        self._state = self._evaluate(candidates, selected, bypass_cache=False)
        return self._state

    def select_manual(self, executable: Path) -> EnvironmentState:
        candidate = self._manual_classifier(executable)
        candidates = _merge_candidate(self._state.candidates, candidate)
        self._state = self._evaluate(candidates, candidate, bypass_cache=False)
        return self._state

    def evaluate_selected(self) -> EnvironmentState:
        self._state = self._evaluate(
            self._state.candidates,
            self._state.selected,
            bypass_cache=False,
        )
        return self._state

    def reprobe(self) -> EnvironmentState:
        self._state = self._evaluate(
            self._state.candidates,
            self._state.selected,
            bypass_cache=True,
        )
        return self._state

    def fail_closed(self, error: Exception) -> EnvironmentState:
        checks = tuple(
            check for check in self._state.checks
            if check.check_id != "headless_capability"
        ) + (
            _failed(
                "headless_capability",
                "环境自检操作失败",
                str(error) or "环境自检发生未知错误。",
                "请查看错误信息，修复后重新扫描或重新探测。",
            ),
        )
        self._state = EnvironmentState(
            candidates=self._state.candidates,
            selected=self._state.selected,
            checks=checks,
            report_path=self._state.report_path,
        )
        return self._state

    def _evaluate(
        self,
        candidates: tuple[SpaceClaimCandidate, ...],
        selected: SpaceClaimCandidate | None,
        *,
        bypass_cache: bool,
    ) -> EnvironmentState:
        checks = self._base_checks()
        checks.extend(_candidate_warnings(candidates))
        profile_path = None
        report_path = None

        if selected is None:
            checks.extend(_missing_selection_checks())
            return EnvironmentState(candidates=candidates, checks=tuple(checks))

        checks.append(_passed("spaceclaim_selected", "已选择 SpaceClaim"))
        if selected.eligibility != "eligible":
            checks.extend(_unsupported_selection_checks(selected))
            return EnvironmentState(
                candidates=candidates,
                selected=selected,
                checks=tuple(checks),
            )

        checks.append(_passed("spaceclaim_version", "版本为已验证的 2022 R2/v222"))
        if any(check.status == "failure" for check in checks if check.severity == "required"):
            checks.append(
                _failed(
                    "headless_capability",
                    "尚未执行 Headless 能力探测",
                    "基础环境检查未通过。",
                    "请先按失败项的修复建议处理，再重新扫描。",
                )
            )
            return EnvironmentState(candidates, selected, tuple(checks))

        try:
            identity = self._identity_builder(selected)
            self._selected_saver(self._selected_path, identity)
            cached = None
            cached_path = cache_path(self.paths.capability_profiles_root, identity)
            if not bypass_cache:
                cached = self._cache_loader(cached_path, identity)
            if cached is not None:
                profile_path = cached_path
                report_path = Path(cached.probe_report)
                checks.append(_passed("headless_capability", "Headless 能力缓存有效"))
            else:
                outcome = self._probe_service(selected, self.paths)
                report_path = outcome.report_path
                if outcome.passed and outcome.profile_path is not None:
                    profile_path = outcome.profile_path
                    checks.append(_passed("headless_capability", "无模型 Headless 探测通过"))
                else:
                    reason = "探测超时。" if outcome.timed_out else outcome.reason
                    checks.append(
                        _failed(
                            "headless_capability",
                            "无模型 Headless 探测未通过",
                            reason,
                            "请关闭残留的 SpaceClaim 进程后重新探测，并查看本地自检报告。",
                        )
                    )
        except (OSError, ValueError) as error:
            checks.append(
                _failed(
                    "headless_capability",
                    "SpaceClaim 身份或能力缓存已失效",
                    str(error) or "SpaceClaim.exe 不可访问。",
                    "请重新扫描或手动选择当前有效的 SpaceClaim.exe。",
                )
            )

        return EnvironmentState(
            candidates=candidates,
            selected=selected,
            checks=tuple(checks),
            profile_path=profile_path,
            report_path=report_path,
        )

    def _base_checks(self) -> list[CheckResult]:
        return [
            _probe_check(
                "windows_x64",
                "Windows x64 环境",
                self._windows_x64_probe,
                "当前系统不是受支持的 64 位 Windows。",
                "请在 Windows x64 计算机上运行此便携版。",
            ),
            _probe_check(
                "resources",
                "运行资源完整",
                lambda: self._resource_probe(self.paths),
                "探测脚本或转换 worker 资源缺失。",
                "请重新解压完整的发行 ZIP，不要单独复制 EXE。",
            ),
            _probe_check(
                "temp_writable",
                "临时目录可写",
                lambda: self._temp_writable_probe(Path(tempfile.gettempdir())),
                "系统临时目录不可写。",
                "请检查临时目录权限和可用空间。",
            ),
            _probe_check(
                "state_writable",
                "本地状态目录可写",
                lambda: self._state_writable_probe(self.paths.state_root),
                "本地自检状态目录不可写。",
                "请检查 LOCALAPPDATA 权限和可用空间。",
            ),
        ]


def _is_windows_x64() -> bool:
    return sys.platform == "win32" and struct.calcsize("P") * 8 == 64


def _resources_exist(paths: RuntimePaths) -> bool:
    required_markers = {
        "probe_v22.py": "SENTINEL_PATH = None",
        "worker_v22.py": "MANIFEST_PATH = None",
    }
    try:
        for name, marker in required_markers.items():
            source = (paths.resource_root / name).read_text(encoding="utf-8")
            if source.count(marker) != 1:
                return False
    except (OSError, UnicodeError):
        return False
    return True


def _writable_directory(root: Path) -> bool:
    unique_path = root / (".environment-check-{}.tmp".format(uuid.uuid4().hex))
    try:
        root.mkdir(parents=True, exist_ok=True)
        with unique_path.open("xb") as output:
            output.write(b"writable")
            output.flush()
            os.fsync(output.fileno())
        return True
    except OSError:
        return False
    finally:
        try:
            unique_path.unlink()
        except FileNotFoundError:
            pass


def _preferred_eligible(
    candidates: tuple[SpaceClaimCandidate, ...],
    previous: Path | None,
) -> SpaceClaimCandidate | None:
    eligible = [candidate for candidate in candidates if candidate.eligibility == "eligible"]
    if previous is not None:
        previous_key = os.path.normcase(str(previous.resolve(strict=False))).casefold()
        for candidate in eligible:
            candidate_key = os.path.normcase(str(candidate.executable.resolve(strict=False))).casefold()
            if candidate_key == previous_key:
                return candidate
    return eligible[0] if eligible else None


def _merge_candidate(
    candidates: tuple[SpaceClaimCandidate, ...], candidate: SpaceClaimCandidate
) -> tuple[SpaceClaimCandidate, ...]:
    key = os.path.normcase(str(candidate.executable.resolve(strict=False))).casefold()
    retained = tuple(
        existing
        for existing in candidates
        if os.path.normcase(str(existing.executable.resolve(strict=False))).casefold() != key
    )
    return (candidate,) + retained


def _candidate_warnings(candidates: tuple[SpaceClaimCandidate, ...]) -> list[CheckResult]:
    return [
        CheckResult(
            "candidate_warning_{}".format(index),
            "warning",
            "warning",
            "检测到但未经验证：{}".format(candidate.executable),
            candidate.reason,
            "如需转换，请选择 SpaceClaim 2022 R2/v222。",
        )
        for index, candidate in enumerate(candidates)
        if candidate.eligibility != "eligible"
    ]


def _missing_selection_checks() -> list[CheckResult]:
    return [
        _failed(
            "spaceclaim_selected",
            "未选择可用的 SpaceClaim",
            "自动扫描没有找到已验证版本。",
            "请重新扫描，或手动选择 SpaceClaim 2022 R2/v222 的 SpaceClaim.exe。",
        ),
        _failed(
            "spaceclaim_version",
            "SpaceClaim 版本未获放行",
            "没有已验证的 2022 R2/v222 候选项。",
            "请安装或选择 SpaceClaim 2022 R2/v222。",
        ),
        _failed(
            "headless_capability",
            "尚未完成 Headless 能力探测",
            "必须先选择已验证版本。",
            "选择 SpaceClaim 2022 R2/v222 后重新探测。",
        ),
    ]


def _unsupported_selection_checks(candidate: SpaceClaimCandidate) -> list[CheckResult]:
    return [
        _failed(
            "spaceclaim_version",
            "检测到但未经验证",
            candidate.reason,
            "请改选 SpaceClaim 2022 R2/v222。",
        ),
        _failed(
            "headless_capability",
            "未对该版本执行能力探测",
            "未经验证的版本不能进入转换工具。",
            "请改选 SpaceClaim 2022 R2/v222。",
        ),
    ]


def _probe_check(
    check_id: str,
    summary: str,
    probe: Callable[[], bool],
    failure_reason: str,
    remediation: str,
) -> CheckResult:
    try:
        passed = probe()
    except OSError:
        passed = False
    return _passed(check_id, summary) if passed else _failed(
        check_id, summary, failure_reason, remediation
    )


def _passed(check_id: str, summary: str) -> CheckResult:
    return CheckResult(check_id, "required", "pass", summary, "检查通过。", "无需处理。")


def _failed(check_id: str, summary: str, reason: str, remediation: str) -> CheckResult:
    return CheckResult(check_id, "required", "failure", summary, reason, remediation)
