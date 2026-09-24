# Deploy runbook: the pilot instance on Fly (A12)

Written 2026-09-24 for Windows PowerShell. Every command is meant to be run
from the repository root, in the order given. `jobscout-yash` is the app name
in `fly.toml`. App names are a global namespace, so if it is taken, change
`app` in `fly.toml` first and use your name everywhere below.

Nothing here deploys by itself. It is the list you run.

---

## 0. Before you start

- `flyctl` installed (`iwr https://fly.io/install.ps1 -useb | iex`), and a
  Sentry project whose DSN you can copy.
- The commit you are deploying passes both gates on your machine:
  ```powershell
  python -m unittest discover -s tests -q
  python scripts/baseline.py verify --all
  ```
- A Gemini key of your own, for the keyed acceptance run only. It is
  pasted into the browser, never set on Fly.

## 1. Log in

```powershell
fly auth login
fly auth whoami
```

## 2. Create the app, if it does not exist

```powershell
fly apps list
# Only if jobscout-yash is not in that list:
fly apps create jobscout-yash
```

Do not run `fly launch`: it rewrites `fly.toml`, which is already correct.
It pins `shared-cpu-1x` with 1 GB, auto-stop off with one machine always
running, the volume at `/data`, the `/healthz` check, hosted mode and port
8080.

## 3. Create the volume

```powershell
fly volumes list --app jobscout-yash
# Only if there is no jobscout_data volume:
fly volumes create jobscout_data --app jobscout-yash --region ord --size 3 --yes
```

- **3 GB, `ord`:** the size `fly.toml` states and its `primary_region`.
- **Exactly one volume.** The app runs one machine by design (in-process
  runs, SQLite). A second volume invites a second machine that cannot see
  the first one's runs.
- `--yes` accepts Fly's warning that a single volume has no replica. That
  is true, and accepted for the pilot. Snapshots are taken daily by default.

## 4. Set the secrets

```powershell
$session = python -c "import secrets; print(secrets.token_urlsafe(48))"
fly secrets set --app jobscout-yash --stage JOBSCOUT_SESSION_SECRET=$session SENTRY_DSN="<paste the DSN from Sentry>"
Remove-Variable session
```

- **`JOBSCOUT_SESSION_SECRET` is the one secret hosted mode requires.** It
  signs session cookies; the app refuses to start without it, or with fewer
  than 32 bytes. Rotating it later signs everyone out.
- **`SENTRY_DSN`** turns error reporting on. Without it the app runs, but
  errors go nowhere.
- **Not `JOBSCOUT_ACCESS_SECRET`.** That was the Basic-auth password before
  accounts (A5), and nothing reads it now. If an old app has it, remove it:
  `fly secrets unset --app jobscout-yash JOBSCOUT_ACCESS_SECRET`.
- **No LLM keys** (A12's checklist, R113, Q67).
- `--stage` stores them without restarting anything; the deploy below
  picks them up.

## 5. Check the secrets against the LLM key names

```powershell
fly secrets list --app jobscout-yash
```

**Expected: exactly two rows, `JOBSCOUT_SESSION_SECRET` and `SENTRY_DSN`.**
Then:

```powershell
fly secrets list --app jobscout-yash | Select-String -Pattern 'GOOGLE_API_KEY|GEMINI_API_KEY|OPENAI_API_KEY|GROQ_API_KEY|OPENROUTER_API_KEY|TOGETHER_API_KEY|DEEPSEEK_API_KEY'
```

**Expected: no output.** Any line printed is a key to remove with
`fly secrets unset` before going further. Hosted mode would ignore it
(R113), but the pilot holds none (Q67).

## 6. Deploy

```powershell
fly deploy --app jobscout-yash
```

`fly.toml` sets `build-target = "runtime"`, so the test stage is not
shipped. The first deploy builds on Fly's remote builder and takes several
minutes: TeX Live is most of the image.

## 7. Read the logs, and check it is up

```powershell
fly logs --app jobscout-yash --no-tail
fly status --app jobscout-yash
fly checks list --app jobscout-yash
fly scale show --app jobscout-yash
Invoke-RestMethod https://jobscout-yash.fly.dev/healthz
fly ssh console --app jobscout-yash -C "printenv JOBSCOUT_MODE JOBSCOUT_HOME"
```

| Command | Expected |
|---|---|
| logs | `Uvicorn running on http://0.0.0.0:8080`, and no `HostingMisconfigured` |
| status | one machine, `started` |
| checks | the `/healthz` check `passing` |
| scale | one machine, `shared-cpu-1x`, 1024 MB |
| healthz | `ok : True` |
| printenv | `hosted` and `/data` |

If the logs show `HostingMisconfigured`, the message names what is missing.
It is almost always step 4.

## 8. Create invite accounts

One per person. The first two are yours, for acceptance (section A):

```powershell
fly ssh console --app jobscout-yash -C "python /app/scripts/admin.py invite"
fly ssh console --app jobscout-yash -C "python /app/scripts/admin.py list-users"
```

- Each `invite` prints a code **once**; only its digest is stored. Send it
  to the friend privately. They redeem it on the sign-in page with their
  email and a passphrase they choose.
- A lost code cannot be recovered: run `invite` again.
- The path is absolute (`/app/scripts/...`) because an SSH session does not
  start in `/app`.
- Also useful: `reset-passphrase <email>`, `delete-user <email> --yes`, and
  `events` (who got how far, A8).

---

## A. Acceptance

Run these on the deployed instance before sending any invite to a friend.

### A1. Log in

Open `https://jobscout-yash.fly.dev`. Redeem your first invite code with an
email and a passphrase. **Pass:** you land in the wizard, signed in. Sign out,
sign back in with the passphrase: **pass** if it works, and if a wrong
passphrase is refused.

### A2. Keyless run, end to end, one PDF

As the first account, **with no key**:
1. Upload `data/master_resumes/priya_raghunathan.pdf` from your checkout,
   check the fields, and continue through About you and Preferences.
2. On the key step, press **Continue without a key**.
3. Run with **Jobs to look at: 5**, **Resumes to write: 1**.

**Pass:**
- the run screen reaches *finished* with 1 written;
- there is no "Some resumes have no PDF" line (R116);
- the board shows that job with a PDF that opens as one page.

A "used your own bullets unchanged" line is expected here: no key means the
`none` rung.

### A3. Keyed run

Sign out and redeem your **second** invite as a second account. Use a second
account, not a second run on the first. A second run on the first scores only
jobs it has not seen (Q63), so it could find nothing new to write.
1. Upload the same PDF, walk the wizard, and on the key step paste your own
   Gemini key.
2. Run with 5 and 1 again.

**Pass:**
- before the run, the run screen says **Bullets will be rewritten by gemini**;
- the run finishes with 1 written;
- there is **no** "used your own bullets unchanged" line, which means the
  bullets were rewritten;
- the PDF opens.

The key is sent with the request and never stored (R113). It is 20 Flash
requests a day on the free tier (Q61), and this run uses a few.

### A4. A test error to Sentry, with no debug route

The app sends any `ERROR` log record to Sentry. So log one from inside the
machine, with a key held so the scrub is exercised:

```powershell
fly ssh console --app jobscout-yash
```

Then, in that shell:

```sh
cd /app && python
```

And paste into Python:

```python
import logging, sentry_sdk
from tools.error_reporting import start_error_reporting
from config import key_in_use
assert start_error_reporting(), "SENTRY_DSN is not set on this machine"
key = "AQ.deploycheck-not-a-real-key-0000000000"
with key_in_use(key):
    logging.getLogger("jobscout.deploycheck").error(
        "Deploy check: Sentry is reachable. A held key follows and must arrive redacted: " + key)

sentry_sdk.flush(10)
exit()
```

Then `exit` the SSH session.

**Pass, in Sentry:**
- an issue arrives whose message ends `...must arrive redacted: [your key]`;
- searching the project for `deploycheck-not-a-real-key` finds nothing.

The fake key is held while the error is logged, which is how the run worker
and import hold a real one (R119).

This snippet was checked here before it was written down: with a fake DSN
and a capturing transport, it sends exactly one event, the event contains
`[your key]`, and the key string is absent.

### A5. Clean up

Delete the second acceptance account (and the first, if you will not use it
yourself):

```powershell
fly ssh console --app jobscout-yash -C "python /app/scripts/admin.py delete-user <second email> --yes"
```

---

## Roll back to the previous release

```powershell
fly releases --app jobscout-yash --image
```

This lists releases newest first, each with its image. Take the image of the
last good one, then:

```powershell
fly deploy --app jobscout-yash --image registry.fly.io/jobscout-yash:<tag from that list>
```

- This redeploys that exact image. It builds nothing, so it is quick.
- **It does not roll back secrets or the volume.** Secrets are reverted by
  hand with `fly secrets set` or `unset`.
- The data on `/data` stays as the newer release left it. The stores have
  only ever migrated by adding columns, which older code ignores. Before
  rolling back over a release, check its `known_questions.md` entries for a
  change to what is stored.
- If the machine will not start at all: `fly machine list --app
  jobscout-yash`, then `fly machine restart <id> --app jobscout-yash`, and
  read `fly logs`.

---

## Environment variables, hosted mode

Every variable the application code reads, found by searching the code for
environment reads, including names read through constants and loops.

| Variable | Set where | Required hosted? | What it does |
|---|---|---|---|
| `JOBSCOUT_MODE` | `fly.toml` `[env]` | **Yes**, must be `hosted` | Accounts and per-user partitions. Unset or `local` on Fly refuses to start (`FLY_APP_NAME` is present). |
| `JOBSCOUT_SESSION_SECRET` | secret | **Yes**, 32 bytes or more | Signs session cookies. Hosted refuses to start without it. |
| `JOBSCOUT_HOME` | `fly.toml` `[env]` and the Dockerfile | **Yes** in practice (`/data`) | Where all user data lives: the volume. |
| `SENTRY_DSN` | secret | No; required by this plan | Error reporting; off when unset. |
| `JOBSCOUT_WEB_DIST` | `fly.toml` `[env]` | No | Where the built React is. Defaults to `web/dist` beside the code, which is the same path in the image. |
| `FLY_APP_NAME`, `FLY_MACHINE_ID` | set by Fly | n/a | Read only to refuse local mode on a platform. |
| `JOBSCOUT_LLM_BACKEND` | not set | No | Pins the rewriting rung for every run. Leave unset: each request's key decides. |
| `SERPER_API_KEY`, `ADZUNA_APP_ID`, `ADZUNA_APP_KEY` | not set | No | Optional keyed job sources. Not LLM keys; the plan enables Adzuna only after the invite is proven (A12). |
| `GOOGLE_API_KEY` and the OpenAI-compatible key names in step 5 | **must not be set** | No | Ignored in hosted mode (R113); must not be present (Q67). |
| `JOBSCOUT_OLLAMA_URL`, `JOBSCOUT_OLLAMA_MODEL` | not set | No | Local Ollama; there is none on Fly. |
| `UVICORN_HOST` | not set | No | Read only by local mode's warning about listening widely. |
| `XDG_DATA_HOME`, `LOCALAPPDATA` | not set | No | The data home's fallback when `JOBSCOUT_HOME` is unset; never used here. |

`.env` is not in the image (`.dockerignore`), so nothing reaches the
instance from a developer's file.
