# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for VoxLinux (Linux daemon + control CLI + transcribe probe).

Modelled on upstream/vox.spec: collect sherpa-onnx native libs + data files,
and hide-import the voxapp.* submodules so the frozen bundle is self-contained.
"""

import os
import platform
import sys

ROOT = os.path.abspath(os.path.dirname(SPECPATH) if "SPECPATH" in globals() else ".")
# SPECPATH is provided by PyInstaller; fall back to cwd.
try:
    ROOT = os.path.abspath(SPECPATH)
except NameError:
    ROOT = os.path.abspath(".")

if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

# Version + arch for the output directory name.
try:
    with open(os.path.join(ROOT, "VERSION"), encoding="utf-8") as _f:
        _VERSION = _f.read().strip()
except OSError:
    _VERSION = "0.0.0"
_ARCH = platform.machine()
_BUNDLE_NAME = f"voxlinux-{_VERSION}-linux-{_ARCH}"

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs

_sherpa_binaries = collect_dynamic_libs("sherpa_onnx")
_sherpa_datas = collect_data_files("sherpa_onnx")

# voxapp submodules.
try:
    import voxapp
    import pkgutil

    _voxapp_hidden = ["voxapp"] + [
        m.name for m in pkgutil.walk_packages(voxapp.__path__, prefix="voxapp.")
    ]
except Exception:
    _voxapp_hidden = [
        "voxapp",
        "voxapp.audio",
        "voxapp.capitalization",
        "voxapp.config",
        "voxapp.daemon",
        "voxapp.downloader",
        "voxapp.engines",
        "voxapp.fillers",
        "voxapp.itn",
        "voxapp.platform_linux",
        "voxapp.post_processor",
        "voxapp.punctuation",
        "voxapp.registry",
        "voxapp.sentence_spacing",
        "voxapp.spacing",
        "voxapp.storage",
        "voxapp.terms",
        "voxapp.vad",
    ]

_hiddenimports = ["sherpa_onnx", "sherpa_onnx.lib._sherpa_onnx", "numpy", "sounddevice", "cffi", "_cffi_backend"] + _voxapp_hidden

_EXCLUDES = [
    "torch", "pandas", "scipy", "matplotlib", "cv2", "tensorflow",
    "sklearn", "pytest", "IPython", "jupyter", "pygments", "boto3",
    "pyarrow", "cryptography", "sqlalchemy", "django", "flask",
    "fastapi", "pydantic", "yt_dlp", "mutagen", "curl_cffi",
    "websockets", "psutil", "playwright", "tkinter",
]

# --- Analysis for the daemon (voxapp/daemon.py via scripts/voxlinux) -------
a_daemon = Analysis(
    [os.path.join(ROOT, "scripts", "voxlinux")],
    pathex=[ROOT],
    binaries=list(_sherpa_binaries),
    datas=list(_sherpa_datas),
    hiddenimports=list(_hiddenimports),
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=list(_EXCLUDES),
    noarchive=False,
    optimize=0,
)
pyz_daemon = PYZ(a_daemon.pure)
exe_daemon = EXE(
    pyz_daemon,
    a_daemon.scripts,
    [],
    exclude_binaries=True,
    name="voxlinux",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

# --- Analysis for the control CLI (scripts/vox-ptt) -----------------------
a_ptt = Analysis(
    [os.path.join(ROOT, "scripts", "vox-ptt")],
    pathex=[ROOT],
    binaries=list(_sherpa_binaries),
    datas=list(_sherpa_datas),
    hiddenimports=list(_hiddenimports),
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=list(_EXCLUDES),
    noarchive=False,
    optimize=0,
)
pyz_ptt = PYZ(a_ptt.pure)
exe_ptt = EXE(
    pyz_ptt,
    a_ptt.scripts,
    [],
    exclude_binaries=True,
    name="vox-ptt",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

# --- Analysis for the transcribe probe (scripts/test_transcribe.py) -------
a_transcribe = Analysis(
    [os.path.join(ROOT, "scripts", "test_transcribe.py")],
    pathex=[ROOT],
    binaries=list(_sherpa_binaries),
    datas=list(_sherpa_datas),
    hiddenimports=list(_hiddenimports),
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=list(_EXCLUDES),
    noarchive=False,
    optimize=0,
)
pyz_transcribe = PYZ(a_transcribe.pure)
exe_transcribe = EXE(
    pyz_transcribe,
    a_transcribe.scripts,
    [],
    exclude_binaries=True,
    name="vox-transcribe",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe_daemon,
    a_daemon.binaries,
    a_daemon.datas,
    exe_ptt,
    a_ptt.binaries,
    a_ptt.datas,
    exe_transcribe,
    a_transcribe.binaries,
    a_transcribe.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name=_BUNDLE_NAME,
)