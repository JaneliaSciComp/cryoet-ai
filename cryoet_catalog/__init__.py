"""CryoET catalog scanner.

Walks sample directories, parses every authoritative source (TOML, MDOC, MRC
header, OME-Zarr ``.zattrs``, frame extension, directory names), and persists
the result to a SQL database. Backend-portable across SQLite and PostgreSQL.
"""
