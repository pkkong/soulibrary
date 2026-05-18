# Local Data Directory

This directory is for local/generated data only.

Do not commit crawler outputs, CSV dumps, SQLite/PostgreSQL exports, caches, or temporary reports here. The production app uses live search by default and does not require checked-in CSV data.

If a crawler or migration script needs data files, generate or download them locally into this directory. Keep code, configuration, and documentation in GitHub; keep bulky data artifacts outside the repository.
