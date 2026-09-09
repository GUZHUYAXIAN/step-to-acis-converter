import ctypes
from dataclasses import dataclass
from pathlib import Path
import re


_VERSION_PATTERN = re.compile(r"^\d+\.\d+\.\d+\.\d+$")


class FileVersionError(ValueError):
    pass


@dataclass(frozen=True)
class FileVersionInfo:
    product_version: str
    file_version: str


class _FixedFileInfo(ctypes.Structure):
    _fields_ = [
        ("dwSignature", ctypes.c_uint32),
        ("dwStrucVersion", ctypes.c_uint32),
        ("dwFileVersionMS", ctypes.c_uint32),
        ("dwFileVersionLS", ctypes.c_uint32),
        ("dwProductVersionMS", ctypes.c_uint32),
        ("dwProductVersionLS", ctypes.c_uint32),
        ("dwFileFlagsMask", ctypes.c_uint32),
        ("dwFileFlags", ctypes.c_uint32),
        ("dwFileOS", ctypes.c_uint32),
        ("dwFileType", ctypes.c_uint32),
        ("dwFileSubtype", ctypes.c_uint32),
        ("dwFileDateMS", ctypes.c_uint32),
        ("dwFileDateLS", ctypes.c_uint32),
    ]


def read_file_version(path: Path) -> FileVersionInfo:
    if not path.is_file():
        raise FileVersionError("executable does not exist: {}".format(path))
    try:
        product_version, file_version = _read_version_strings(path)
    except (OSError, AttributeError) as error:
        raise FileVersionError("cannot read version metadata: {}".format(error)) from error
    product_version = product_version.strip().strip("\x00")
    file_version = file_version.strip().strip("\x00")
    if not _VERSION_PATTERN.fullmatch(product_version):
        raise FileVersionError("product version metadata is missing or malformed")
    if not _VERSION_PATTERN.fullmatch(file_version):
        raise FileVersionError("file version metadata is missing or malformed")
    return FileVersionInfo(product_version, file_version)


def _read_version_strings(path: Path) -> tuple[str, str]:
    version = ctypes.windll.version
    size = version.GetFileVersionInfoSizeW(str(path), None)
    if size <= 0:
        raise OSError(ctypes.get_last_error(), "version resource is unavailable")
    buffer = ctypes.create_string_buffer(size)
    if not version.GetFileVersionInfoW(str(path), 0, size, buffer):
        raise OSError(ctypes.get_last_error(), "cannot read version resource")
    pointer = ctypes.c_void_p()
    value_length = ctypes.c_uint()
    if not version.VerQueryValueW(buffer, "\\", ctypes.byref(pointer), ctypes.byref(value_length)):
        raise OSError(ctypes.get_last_error(), "fixed version metadata is unavailable")
    fixed = ctypes.cast(pointer, ctypes.POINTER(_FixedFileInfo)).contents
    if fixed.dwSignature != 0xFEEF04BD:
        raise OSError("fixed version metadata signature is invalid")
    return (
        _format_version(fixed.dwProductVersionMS, fixed.dwProductVersionLS),
        _format_version(fixed.dwFileVersionMS, fixed.dwFileVersionLS),
    )


def _format_version(most_significant: int, least_significant: int) -> str:
    return "{}.{}.{}.{}".format(
        most_significant >> 16,
        most_significant & 0xFFFF,
        least_significant >> 16,
        least_significant & 0xFFFF,
    )
