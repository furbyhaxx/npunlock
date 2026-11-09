"""Developer oracle using npunlock's existing isolated Wine worker transport."""

from __future__ import annotations

import ctypes
from pathlib import Path


class OracleError(RuntimeError):
    """A vendor stage failed or could not be invoked."""


class _View(ctypes.Structure):
    _fields_ = [("data", ctypes.c_void_p), ("size", ctypes.c_size_t)]


class _Buffer(ctypes.Structure):
    _fields_ = [
        ("data", ctypes.c_void_p),
        ("size", ctypes.c_size_t),
        ("release", ctypes.c_void_p),
        ("context", ctypes.c_void_p),
    ]


class _Result(ctypes.Structure):
    _fields_ = [
        ("output", _Buffer),
        ("diagnostic", _Buffer),
        ("stdout_log", _Buffer),
        ("stderr_log", _Buffer),
        ("tool_return", ctypes.c_int32),
        ("worker_status", ctypes.c_uint32),
        ("process_exit_code", ctypes.c_uint32),
    ]


def _bytes(buffer: _Buffer) -> bytes:
    return ctypes.string_at(buffer.data, buffer.size) if buffer.size else b""


class Oracle:
    """Invoke proprietary stages without redistributing or loading their DLLs natively."""

    def __init__(self, native_directory: Path, movitools_directory: Path, timeout_ms: int = 60_000) -> None:
        self.native_directory = native_directory.resolve(strict=True)
        self.movitools_directory = movitools_directory.resolve(strict=True)
        self.timeout_ms = timeout_ms
        self.library = ctypes.CDLL(str(self.native_directory / "libnpunlock.so"))
        self.run = self.library.npunlock_run_movi_stage
        self.run.argtypes = [
            _View,
            _View,
            ctypes.c_int,
            ctypes.POINTER(_View),
            ctypes.c_size_t,
            ctypes.POINTER(_View),
            ctypes.c_size_t,
            ctypes.c_uint32,
            ctypes.POINTER(_Result),
        ]
        self.run.restype = ctypes.c_uint32
        self.release = self.library.npunlock_movi_result_release
        self.release.argtypes = [ctypes.POINTER(_Result)]
        self.release.restype = None

    def stage(self, stage: int, dll: str, arguments: list[str], inputs: list[bytes]) -> bytes:
        """Run one bounded stage and release every owned response buffer."""
        owners = []

        def view(data: bytes) -> _View:
            owner = ctypes.create_string_buffer(data)
            owners.append(owner)
            return _View(ctypes.cast(owner, ctypes.c_void_p), len(data))

        path = self.movitools_directory / "bin" / dll
        path.resolve(strict=True)
        dll_path = ("Z:" + str(path).replace("/", "\\")).encode()
        argv = (_View * len(arguments))(*(view(arg.encode()) for arg in arguments))
        payloads = (_View * len(inputs))(*(view(data) for data in inputs))
        result = _Result()
        try:
            status = self.run(
                view(str(self.native_directory / "npunlock_movi_worker.exe").encode()),
                view(dll_path),
                stage,
                argv,
                len(argv),
                payloads,
                len(payloads),
                self.timeout_ms,
                ctypes.byref(result),
            )
            if status:
                diagnostics = b"\n".join(
                    _bytes(getattr(result, name)) for name in ("diagnostic", "stdout_log", "stderr_log")
                )
                raise OracleError(
                    f"{dll}: status={status}, tool={result.tool_return}, worker={result.worker_status}, "
                    f"exit={result.process_exit_code}: {diagnostics.decode(errors='replace')}"
                )
            return _bytes(result.output)
        finally:
            self.release(ctypes.byref(result))

    def assemble(self, source: str) -> bytes:
        """Assemble vendor-dialect source using moviAsm --cv 3720xx --noSPrefixing."""
        return self.stage(2, "moviAsm64.dll", ["moviAsm.dll", "--cv", "3720xx", "--noSPrefixing"], [source.encode()])

    def compile(self, source: bytes, definitions: tuple[str, ...] = ()) -> str:
        """Compile source with the same target and optimization flags as shavecc."""
        arguments = [
            "moviCompile.dll",
            "-cc1",
            "-triple",
            "shave",
            "-target-cpu",
            "3720xx",
            "-S",
            "-O2",
            "-x",
            "c",
            "entry.c",
            "-ffunction-sections",
            "-fdata-sections",
            *("-D" + definition for definition in definitions),
            "-o",
            "-",
        ]
        return self.stage(1, "moviCompile64.dll", arguments, [source]).decode()
