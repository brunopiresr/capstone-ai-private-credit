"""Include shared application modules in Streamlit's native source reload scope."""

import os
from pathlib import Path


def watch_application_sources() -> None:
    """Streamlit checks PYTHONPATH rather than editable-install entries in sys.path.

    Both entry points live in web/, so their default watch scope misses sibling
    domain, application and persistence modules. Register src before Streamlit
    discovers imported modules after a script run, keeping native cache eviction
    responsible for reloading dependent modules together.
    """
    source_root = str(Path(__file__).resolve().parents[2])
    previous = os.environ.get("PYTHONPATH", "")
    if source_root not in previous.split(os.pathsep):
        os.environ["PYTHONPATH"] = source_root + (os.pathsep + previous if previous else "")
