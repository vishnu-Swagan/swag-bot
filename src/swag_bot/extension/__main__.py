"""``python -m swag_bot.extension`` speaks native messaging on stdio.

Chrome launches the installed host with ``-m swag_bot.extension.host``.
This module is the same entry point, for a manual run.
"""

from swag_bot.extension.host import main

if __name__ == "__main__":
    main()
