from __future__ import annotations

import os
import re
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Literal

from ._native import NativeLibraries


@dataclass(frozen=True, slots=True)
class ShaveToolchain:
    mode: Literal["vendor", "hybrid", "auto"]
    linker: Path


@dataclass(frozen=True, slots=True)
class ShaveCompilation:
    elf: bytes
    path: Literal["vendor", "hybrid"]
    rejection: str | None = None


def resolve_toolchain(mode: str | None, linker: str | os.PathLike[str] | None) -> ShaveToolchain:
    selected_mode = mode if mode is not None else os.environ.get("NPUNLOCK_SHAVE_TOOLCHAIN", "vendor")
    modes: dict[str, Literal["vendor", "hybrid", "auto"]] = {
        "vendor": "vendor",
        "hybrid": "hybrid",
        "auto": "auto",
    }
    if selected_mode not in modes:
        raise ValueError("SHAVE toolchain must be vendor, hybrid, or auto")
    selected_linker = (
        linker if linker is not None else os.environ.get("NPUNLOCK_SHAVE_LINKER", "/opt/shave-lld/bin/ld.lld")
    )
    if not os.fspath(selected_linker):
        raise ValueError("SHAVE linker path must not be empty")
    return ShaveToolchain(modes[selected_mode], Path(selected_linker).expanduser())


def _rejection_detail(error: Exception, source: str) -> str:
    detail = str(error)
    match = re.search(r"\bline (\d+)\b", detail)
    if match:
        line = int(match.group(1))
        lines = source.splitlines()
        if 1 <= line <= len(lines):
            detail += f": {lines[line - 1].strip()}"
    return detail


def _link_native(
    obj: bytes,
    *,
    native: NativeLibraries,
    movi_dll_dir: str | os.PathLike[str],
    linker_script: bytes | None,
    linker: Path,
    timeout_ms: int,
) -> bytes:
    with tempfile.TemporaryDirectory(prefix="npunlock-shave-") as directory:
        root = Path(directory)
        obj_path = root / "kernel.o"
        script_path = root / "kernel.ld"
        elf_path = root / "kernel.elf"
        obj_path.write_bytes(obj)
        script_path.write_bytes(linker_script if linker_script is not None else native.default_shave_linker_script())
        arguments = [
            str(linker),
            "-flavor",
            "gnu",
            "-EL",
            "-e",
            "controlled_act",
            "-z",
            "max-page-size=0x10",
            "--gc-sections",
            "-T",
            str(script_path),
            str(obj_path),
            str(Path(movi_dll_dir) / "lib" / "mlibm.a"),
            "-o",
            str(elf_path),
        ]
        try:
            process = subprocess.run(arguments, capture_output=True, timeout=timeout_ms / 1000, check=False)
        except subprocess.TimeoutExpired as error:
            raise RuntimeError(f"native SHAVE linker exceeded {timeout_ms} ms") from error
        if process.returncode:
            detail = (process.stderr or process.stdout).decode("utf-8", errors="replace").strip()
            raise RuntimeError(f"native SHAVE linker failed ({process.returncode}): {detail}")
        return elf_path.read_bytes()


def compile_shave(
    native: NativeLibraries,
    source: bytes,
    *,
    movi_dll_dir: str | os.PathLike[str],
    linker_script: bytes | None,
    definitions: Iterable[str],
    timeout_ms: int,
    worker: str | None,
    toolchain: ShaveToolchain,
) -> ShaveCompilation:
    definitions = tuple(definitions)

    def vendor(rejection: str | None = None) -> ShaveCompilation:
        elf = native.compile_shave(
            source,
            movi_dll_dir=movi_dll_dir,
            linker_script=linker_script,
            definitions=definitions,
            timeout_ms=timeout_ms,
            worker=worker,
        )
        return ShaveCompilation(elf, "vendor", rejection)

    if toolchain.mode == "vendor":
        return vendor()

    from tools.shaveasm.objwriter import assemble
    from tools.shaveasm.parser import AssemblyError

    assembly = native.compile_shave_assembly(
        source,
        movi_dll_dir=movi_dll_dir,
        definitions=definitions,
        timeout_ms=timeout_ms,
        worker=worker,
    ).decode("utf-8")
    try:
        obj = assemble(assembly)
    except AssemblyError as error:
        detail = _rejection_detail(error, assembly)
        if toolchain.mode == "auto":
            return vendor(detail)
        raise RuntimeError(f"native SHAVE assembler rejected {detail}") from error
    elf = _link_native(
        obj,
        native=native,
        movi_dll_dir=movi_dll_dir,
        linker_script=linker_script,
        linker=toolchain.linker,
        timeout_ms=timeout_ms,
    )
    return ShaveCompilation(elf, "hybrid")
