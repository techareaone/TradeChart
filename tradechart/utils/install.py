"""Runtime auto-installer for optional and required package dependencies.

When a package is missing, ``ensure_package`` installs it via pip in the same
Python environment and then verifies the import succeeds before returning.
"""

from __future__ import annotations

import importlib
import subprocess
import sys


def ensure_package(pip_name: str, import_name: str | None = None) -> None:
    """Ensure *pip_name* is importable, installing it silently if not.

    Parameters
    ----------
    pip_name : str
        The name used with ``pip install`` (e.g. ``"mplfinance"``).
    import_name : str | None
        The module name used with ``import`` when it differs from *pip_name*
        (e.g. ``"cv2"`` for ``pip_name="opencv-python"``).  Defaults to
        *pip_name*.

    Raises
    ------
    RuntimeError
        If pip installation fails or the package still cannot be imported
        after installation (e.g. wrong Python environment).
    """
    module_name = import_name or pip_name

    try:
        importlib.import_module(module_name)
        return  # already available
    except ImportError:
        pass

    # Lazy import to avoid circular dependency at module load time
    from tradechart.config.logger import get_logger
    get_logger().detail("Auto-installing '%s' …", pip_name)

    result = subprocess.run(
        [sys.executable, "-m", "pip", "install", pip_name, "--quiet"],
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        raise RuntimeError(
            f"Auto-install of '{pip_name}' failed.\n"
            f"Run manually: pip install {pip_name}\n"
            f"pip stderr: {result.stderr.strip()}"
        )

    # Invalidate importlib caches so the newly installed package is visible
    importlib.invalidate_caches()

    try:
        importlib.import_module(module_name)
    except ImportError:
        raise RuntimeError(
            f"'{pip_name}' was installed but '{module_name}' still cannot be "
            f"imported.  Try restarting your Python session."
        )
