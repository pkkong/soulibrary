# Data Directory

This directory is intentionally empty in Git.

Soulib production uses live search by default and does not require checked-in CSV, SQLite, or crawler data.

Do not commit:

- crawler outputs
- CSV dumps
- SQLite or PostgreSQL exports
- local caches
- temporary reports
- credential or token files

If a data/admin script needs local files, generate or download them into this directory in your own environment. Keep code, configuration, and documentation in GitHub; keep bulky or private data artifacts outside the repository.
