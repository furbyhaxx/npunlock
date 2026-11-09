from __future__ import annotations

import os
import platform
from pathlib import Path
import shutil
import struct
import subprocess
import sys

from setuptools import find_packages, setup
from setuptools.command.build_py import build_py
from wheel.bdist_wheel import bdist_wheel

ROOT = Path(__file__).resolve().parent


def run_cmake(*arguments: str) -> None:
    command = ["cmake", *arguments]
    if sys.platform == "win32":
        command = [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(ROOT / "tools/msvc-run.ps1"),
            "cmake",
            *arguments,
        ]
    subprocess.check_call(command, cwd=ROOT)


class BuildPy(build_py):
    def run(self) -> None:
        if sys.platform not in ("win32", "linux") or platform.machine().lower() not in ("x86_64", "amd64"):
            raise RuntimeError("npunlock native wheels require Windows or Linux x64")
        if struct.calcsize("P") != 8:
            raise RuntimeError("npunlock native wheels require 64-bit Python")
        super().run()
        configuration = os.environ.get("NPUNLOCK_CMAKE_CONFIG", "Release")
        native_build = Path(self.build_lib).resolve().parent / "npunlock-native"
        native_stage = Path(self.build_lib).resolve().parent / "npunlock-runtime"
        if native_stage.exists():
            shutil.rmtree(native_stage)
        run_cmake(
            "-S",
            str(ROOT),
            "-B",
            str(native_build),
            "-DNPUNLOCK_BUILD_TESTS=OFF",
            "-DCMAKE_INSTALL_LIBDIR=lib",
        )
        run_cmake(
            "--build",
            str(native_build),
            "--config",
            configuration,
            "--target",
            "npunlock_native",
            "npunlock_worker",
            *(("npunlock_ir_worker_posix",) if sys.platform == "linux" else ()),
        )
        run_cmake(
            "--install",
            str(native_build),
            "--config",
            configuration,
            "--prefix",
            str(native_stage),
            "--component",
            "PythonRuntime",
        )
        package_bin = Path(self.build_lib) / "npunlock/_bin"
        package_bin.mkdir(parents=True, exist_ok=True)
        runtime_files = (
            ("bin/npunlock.dll", "bin/npunlock_worker.exe")
            if sys.platform == "win32"
            else ("lib/libnpunlock.so", "bin/npunlock-ir-worker", "bin/npunlock_movi_worker.exe")
        )
        for filename in runtime_files:
            shutil.copy2(native_stage / filename, package_bin / Path(filename).name)
        package_include = Path(self.build_lib) / "npunlock/include/npunlock"
        package_include.mkdir(parents=True, exist_ok=True)
        shutil.copy2(
            ROOT / "include/npunlock/npu3720_kernel.h",
            package_include / "npu3720_kernel.h",
        )


class BdistWheel(bdist_wheel):
    def finalize_options(self) -> None:
        super().finalize_options()
        self.root_is_pure = False

    def get_tag(self) -> tuple[str, str, str]:
        _, _, platform = super().get_tag()
        return "py3", "none", platform


setup(
    version=os.environ.get("NPUNLOCK_PACKAGE_VERSION", "0.1.0"),
    packages=[*find_packages(where="python"), "tools.shaveasm"],
    package_dir={"": "python", "tools.shaveasm": "tools/shaveasm"},
    cmdclass={"build_py": BuildPy, "bdist_wheel": BdistWheel},
)
