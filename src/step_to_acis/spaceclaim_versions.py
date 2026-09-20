"""Supported host/API/output contracts; host API and ACIS versions are distinct."""
from dataclasses import dataclass


LEGACY_ACIS_VERSIONS = tuple(["V6", "V7"] + ["V{}".format(n) for n in range(15, 32)])


@dataclass(frozen=True)
class SpaceClaimRelease:
    label: str
    layout: str
    version_prefix: str
    api_version: str
    acis_versions: tuple[str, ...]
    default_acis_version: str

    @property
    def probe_resource(self) -> str:
        return "probe_{}.py".format(self.api_version.lower())

    @property
    def worker_resource(self) -> str:
        return "worker_{}.py".format(self.api_version.lower())

    @property
    def output_note(self) -> str:
        if self.api_version == "V261":
            return "SpaceClaim 2026 R1：ACIS 5.0（V5，固定）；装配导出会扁平化。"
        return "SpaceClaim 2022 R2：默认 ACIS V22，可在高级设置中选择版本。"


RELEASES = (
    SpaceClaimRelease("SpaceClaim 2022 R2", "v222", "2022.2.", "V22", LEGACY_ACIS_VERSIONS, "V22"),
    SpaceClaimRelease("SpaceClaim 2026 R1", "v261", "2026.1.", "V261", ("V5",), "V5"),
)


def release_for_versions(product_version: str, file_version: str) -> SpaceClaimRelease:
    for release in RELEASES:
        if product_version.startswith(release.version_prefix) and file_version.startswith(release.version_prefix):
            return release
    raise ValueError("only SpaceClaim 2022 R2 / 2026 R1 version metadata is supported")


def release_for_api(api_version: str) -> SpaceClaimRelease:
    for release in RELEASES:
        if release.api_version == api_version:
            return release
    raise ValueError("unsupported SpaceClaim script API: {}".format(api_version))


def validate_acis_version(api_version: str, acis_version: str) -> None:
    release = release_for_api(api_version)
    if acis_version not in release.acis_versions:
        raise ValueError("{} 不支持 ACIS {}；请选择 {}。不会自动替换输出版本。".format(
            release.label, acis_version, ", ".join(release.acis_versions)))
