from dataclasses import dataclass
from enum import Enum
from pathlib import Path


class OutputFormat(str, Enum):
    SAB = "SAB"
    SAT = "SAT"

    @property
    def extension(self) -> str:
        return "." + self.value.lower()


class OverwritePolicy(str, Enum):
    SKIP = "Skip"
    OVERWRITE = "Overwrite"


class Status(str, Enum):
    SUCCESS = "Success"
    FAILED = "Failed"
    SKIPPED = "Skipped"


@dataclass(frozen=True)
class AcisSettings:
    output_formats: tuple[OutputFormat, ...]
    version: str
    units: str


@dataclass(frozen=True)
class ConverterConfig:
    spaceclaim_exe: Path
    input_dir: Path
    output_dir: Path
    recursive: bool
    acis: AcisSettings
    overwrite_policy: OverwritePolicy
    chunk_size: int
    heartbeat_timeout_seconds: float
    retry_count: int
    preserve_relative_directories: bool
    long_path_warning_threshold: int

    @property
    def resolved_acis_version(self) -> str:
        if self.acis.version == "current_spaceclaim_default":
            return "V22"
        return self.acis.version


@dataclass(frozen=True)
class ConversionTask:
    sequence: int
    task_id: str
    source_path: Path
    output_path: Path
    staging_output_path: Path
    output_format: OutputFormat
    source_size_bytes: int
    attempt: int = 0
    requires_spaceclaim_path_probe: bool = False


@dataclass(frozen=True)
class ConversionResult:
    sequence: int
    task_id: str
    source_name: str
    source_path: str
    output_name: str
    output_path: str
    output_format: str
    source_size_bytes: int
    output_size_bytes: int
    start_time: str
    duration_seconds: float
    status: Status
    error_message: str
    finish_time: str = ""
