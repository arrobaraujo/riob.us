import sys

from src.core import app_runtime as _runtime


if __name__ == "__main__":
    _runtime.main()
else:
    sys.modules[__name__] = _runtime
