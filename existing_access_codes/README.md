# existing_access_codes/

Put the access-code exports (`.xlsx` / `.csv`) here. Booty checks codes against **every** file in this folder.

Required columns (same as the original export):

```
id, code, generated_by, created_at, used, status, batch_id, printed_at
```

The exports and Booty's backups (`.booty_backups/`) contain real access codes, so they are **excluded from git**
(see `.gitignore`). Only this README is committed.
