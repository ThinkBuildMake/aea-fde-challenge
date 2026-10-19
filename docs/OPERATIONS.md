# Operations

Two operator jobs run inside the deployed service: putting the bookings back to the
supplied seed, and rebuilding the knowledge-base index. Each is one command over the
host's shell (`railway ssh`, preferred) or one admin route (the fallback, ARCHITECTURE
open question 6). The routes need the admin token from the service's `ADMIN_TOKEN`
variable; keep it in your shell as `$ADMIN_TOKEN` and never paste its value into a file.

```sh
export PUBLIC_URL=https://<the service's domain>
```

## Reset the bookings (DP-4)

Over the shell:

```sh
railway ssh --service meridian --environment production -- python -m app.scheduling.reset
```

By route, if shell access is not set up:

```sh
curl -sS -X POST -H "Authorization: Bearer $ADMIN_TOKEN" -H 'Accept: application/json' \
  "$PUBLIC_URL/admin/reset-scheduling"
```

Both print the same result:

```json
{"restored": true, "snapshotId": "20261019T201500Z-1a2b3c", "slotCounts": {"open": 323, "booked": 159, "reservedMembers": 42, "blocked": 4}}
```

- The five supplied tables go back to the seed exactly; the supplied schema is not changed.
- Left alone: conversations, turns, handoffs, waitlist entries and flags. The chat's
  earlier visit changes are only marked retired, so the booking-agreement check stops
  counting them.
- A booking in progress answers `409 busy`; run the reset again a moment later.
- `500 reset_failed` saying "The seed was restored" means only the retired marks failed;
  running the reset again finishes it. Any other `500 reset_failed` left the bookings as
  they were.
- Before every reset both database files are copied to
  `<folder of SCHEDULING_DB_PATH>/backups/<snapshotId>/`. Backups are never pruned;
  delete old folders by hand if the volume fills up.

## Add or replace a knowledge-base document (CH-1)

No code changes. The knowledge base ships in the image, so a new document needs a deploy
and then one rebuild.

1. Put the file under `data/meridian_dataset/knowledge_base/` (for example
   `faq/new_topic.md`).
2. List it in `data/meridian_dataset/kb_manifest.json` with a status and a reason:
   `"faq/new_topic.md": {"status": "current", "reason": "Why it is searchable."}`.
   Statuses: `current` (searchable), `superseded`, `agent-only`, `placeholder` (not
   searchable). An image or a PDF also needs its checked text under
   `data/meridian_dataset/kb_extracted/` and `"text"` and `"checkedOn"` in its entry.
3. Commit, then deploy with `scripts/deploy.sh` (it runs `make gate` first).
4. Rebuild the index, over the shell:

   ```sh
   railway ssh --service meridian --environment production -- python -m app.knowledge.rebuild
   ```

   or by route:

   ```sh
   curl -sS -X POST -H "Authorization: Bearer $ADMIN_TOKEN" -H 'Accept: application/json' \
     "$PUBLIC_URL/admin/rebuild-index"
   ```

   Both print `{"indexVersion": "idx-…", "passages": 54, "sources": 10}` (the counts of
   the new index).

The next answer uses the new index with no restart: the running server reloads the index
file when it changes, so a rebuild run over the shell reaches it too.

A file in the folder with no manifest entry stops the rebuild with
`422 manifest_invalid` (the command exits 1 and prints the same error), and the message
names the file. The old index stays in use, so answers do not change. `make gate` refuses
such a file too.

## Shell access

`railway ssh` needs a person's Railway login and a registered SSH key; a project token
(`RAILWAY_TOKEN`) cannot manage keys:

```sh
railway login
railway ssh keys add
```

Until that is done, use the admin routes above.
