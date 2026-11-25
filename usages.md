# How to run

Run every command from the repo root, with the `zehitomo` conda env active.

```bash
conda activate zehitomo
```

`.env` in the repo root must contain:

```text
GOOGLE_API_KEY=...
GOOGLE_MODEL=gemini-3.6-flash

# Google Drive sync (optional, separate from Gemini key)
GOOGLE_DRIVE_SYNC=1
GOOGLE_DRIVE_FOLDER_ID=1DAMVhfiyQj8AK890CO87v0Z1omunyrPY
GOOGLE_DRIVE_CREDENTIALS=credentials/google-drive-service-account.json
```

`GOOGLE_MODEL` is optional. Quit Chrome completely (Cmd+Q) before a scrape that uses the same profile folder.

## Docker (fresh setup)

Runtime image: **Python 3.12 + Google Chrome + Xvfb**. Compose mounts **this whole project** into the container — files stay on the host (Mac or Hostinger).

```bash
# Terminal 1 — start container (Xvfb + sleep; stays running)
docker compose up --build

# Terminal 2 — open a shell inside, then run like local
docker compose exec scrape bash
docker exec -it <container_id> bash
docker exec -it 3b19b73f51f0 bash
./scripts/run_rotate.sh
# or one combo:
# python -m app.main alamin --service 民泊清掃 --limit 1 \
#   --options combination_creation/Output/options_type_5_tokyo.json \
#   --output output.json --rerun
```

Stop with `Ctrl+C` in terminal 1, or `docker compose down`.

You should see `[entrypoint] starting Xvfb...` in terminal 1.

**One-shot (no exec):** `docker compose run --rm scrape ./scripts/run_rotate.sh`

**Mac (Apple Silicon):** `platform: linux/amd64` runs via Rosetta — often slow. Prefer **conda** for day-to-day local runs; use Docker on **Hostinger (amd64)** for deploy.

**Profiles:** Mac Chrome profiles do **not** work in Linux Chrome (cookies are encrypted with the macOS Keychain). Log in once on each machine / container that scrapes — see **1. Log in once** below.

### Move to Hostinger KVM

1. Copy the whole repo (`rsync` / `scp` / `git`), including `.env`, `profiles/`, `credentials/`.
2. Install Docker + Compose on the VPS.
3. `docker compose build` then the same `docker compose run ...` commands as above.

### Google Drive setup (Option 2)

1. Google Cloud Console → create/select a project → enable **Google Drive API**
2. Create a **service account** → Keys → Add key → JSON  
   Save it as `credentials/google-drive-service-account.json` (gitignored)
3. Open the service account JSON and copy `client_email`
4. Share your Drive folder with that email as **Editor**:  
   https://drive.google.com/drive/folders/1DAMVhfiyQj8AK890CO87v0Z1omunyrPY
5. Install packages: `pip install google-api-python-client google-auth`
6. Test upload:

```bash
python scripts/sync_drive.py
```

While scraping, after each saved combination the code updates local files **and** overwrites `output.json`, `zehitomo_main.csv`, and `options.json` in that Drive folder.

## 1. Log in once

Every scraping account needs a saved Chrome profile under `profiles/<name>/`. `login_profile.py` opens **normal Google Chrome** (not automation — Google blocks sign-in there), you sign in to Zehitomo by hand, and the session is saved for later scrapes.

**Do this once per machine.** A profile made on a Mac does not work on Linux / Docker (cookies are encrypted with the OS keychain), so log in again on each machine or container that scrapes.

### Mac / Linux desktop

```bash
python login_profile.py alamin
```

1. Chrome opens on zehitomo.com
2. Click 「ログイン」 and sign in (Google / email)
3. Check the round profile icon is in the top-right corner → logged in
4. **Quit Chrome completely** (Mac: Cmd+Q, Linux: close all its windows)
5. Back in the terminal, press **ENTER**

The session is saved under `profiles/alamin/`. Use the same name later:

```bash
python -m app.main alamin --service 民泊清掃 --limit 1
```

Repeat with another name (`python login_profile.py tasnia`, …) for each account used in rotation.

### Docker on a server (Hostinger, no screen) — via VNC

The container has no real screen, so you watch Chrome through VNC.

```bash
# 1) on the VPS — start the container with VNC enabled
VNC=1 docker compose up --build          # optional: VNC_PASSWORD=... in .env

# 2) on your Mac — tunnel the VNC port (only exposed on the VPS's localhost)
ssh -L 5900:localhost:5900 user@your-vps
#    then Finder → Go → Connect to Server → vnc://localhost:5900

# 3) on the VPS, second terminal
docker compose exec scrape python login_profile.py alamin
#    Chrome appears in the VNC window → log in → close Chrome → press ENTER
```

### Docker on a Linux PC with a desktop — no VNC needed

```bash
xhost +local:docker
docker compose run --rm -e DISPLAY=$DISPLAY -v /tmp/.X11-unix:/tmp/.X11-unix \
  scrape python login_profile.py alamin
```

In Docker the profile is still written to `profiles/<name>/` on the host (the project folder is mounted), so later scrapes in the container reuse it.

### Troubleshooting

- **Scraper says not logged in / calls `wait_for_manual_login`:** run `login_profile.py <name>` again on that machine. On Linux, profiles made before the `--password-store=basic` change need this once.
- **"Chrome exited immediately":** no display available. In Docker start with `VNC=1` (or the X11 command above). The Chrome log is at `profiles/<name>.chrome.log`.
- **Profile is locked / Chrome won't open:** a Chrome window still uses that profile — quit it fully and retry.
- On Linux, both login and scraper start Chrome with `--password-store=basic` (plus `--no-sandbox` as root in Docker) so they can read the same cookies. Don't remove it from only one side.

### Trim profile caches

Chrome cache junk is trimmed automatically after login and before each scrape (login cookies are kept). One-shot trim of all profiles:

```bash
# Chrome must be fully quit for those profiles
python scripts/trim_profiles.py
python scripts/trim_profiles.py alamin azimon
```

## 2. Build questionnaire combinations

Reads `sections.json` and writes `combination_creation/options.json`.

```bash
# one service
python combination_creation/zehitomo_combination.py --service 電気屋・電気工事
python combination_creation/zehitomo_combination.py --service ハウスクリーニング

# continue from the next combination if some are already saved
python combination_creation/zehitomo_combination.py --service 電気屋・電気工事

# wipe that service and start again from combination1
python combination_creation/zehitomo_combination.py --service 電気屋・電気工事 --force
```

When a questionnaire path reaches the address step, the same combination is saved for every code in `POSTAL_CODES`.

### Catalog question-type patterns (boss XLSX)

Walks each service’s question chain **once** (first option at each step), records every question + its option list, and groups services that share the same chain into a `type_id`. Uses one postal code (`182-0004` by default).

If the service page has the banner entry buttons (e.g. 戸建 / 集合住宅 / その他 on ハウスクリーニング), those are recorded as **question 1**, then the modal questions follow. Pages without that banner fall back to the CTA → modal path. Writes:

- `combination_creation/question_types.json` (resume-safe intermediate)
- `combination_creation/question_types.xlsx`
  - sheet `question_types`: columns A–I only (`service_name`, `category`, `URL link`, `service_url`, `type_id`, `question_count`, `postal_code`, `error`, `all_info` JSON) — no question_N columns
  - separate sheet per type (`type_1`, `type_2`, …) with Q / A Selection layout
- `combination_creation/question_types_summary.xlsx` — separate summary (counts + type overview)

```bash
# all services in sections.json (skips ones already in the JSON)
python combination_creation/catalog_question_types.py

# one / few services
python combination_creation/catalog_question_types.py --service ハウスクリーニング
python combination_creation/catalog_question_types.py --limit 5

# re-scan and overwrite saved rows
python combination_creation/catalog_question_types.py --force --service ハウスクリーニング

# rebuild XLSX only from existing JSON (no browser)
python combination_creation/catalog_question_types.py --xlsx-only
```

Needs `openpyxl` (`pip install openpyxl`). Same Chrome profile as combinations (`zehitomo-profile`).

## 3. Scrape contractors

```bash
# first combination of one service
python -m app.main alamin --service 電気屋・電気工事 --limit 1

# only combination1 and combination2
python -m app.main alamin --service 電気屋・電気工事 \
  --combination combination1 --combination combination2

# every combination saved for that service
python -m app.main alamin --service 電気屋・電気工事
```

Results are written to `output.json` after each combination. The file keeps **all services** under `services.<service_name>.combinations_done` (switching service in rotate config does not wipe earlier services). Each combination stores steps, `extracted_contractors`, the `profile` that ran it, and measured `llm_cost` (tokens + `$` for that run). Already-finished combinations are skipped unless you pass `--rerun`. Captcha exits with code `2` and does **not** mark that combination done — rotation scripts retry the same combination on the next profile.

After a combo finishes, the terminal also prints a line like `LLM cost: $0.42 (37 steps, …)`. Optional rate overrides in `.env`: `GEMINI_INPUT_USD_PER_1M`, `GEMINI_OUTPUT_USD_PER_1M` (defaults 0.75 / 3.75).

Optional flags:

```bash
python -m app.main alamin --service 電気屋・電気工事 --limit 1 \
  --options combination_creation/options.json \
  --output output.json
```

Finished contractors are also appended to `zehitomo_main.csv`.

### Type_5 boss block-test (same location, one account)

Sheet `test_combination_type_5` has **12 rows**, all location `10010` → postal `001-0010`, with different Q1–Q4 answers. Purpose: keep location fixed and watch when Zehitomo blocks the account.

```bash
# 1) build options from the test sheet
python combination_creation/build_options_from_type5.py --test
# → combination_creation/options_test_type_5.json  (12 combinations)

# 2) scrape with ONE account only (use a profile not on captcha cooldown)
#    separate output so it does not mix with earlier 民泊清掃 runs
python -m app.main alamin --service 民泊清掃 \
  --options combination_creation/options_test_type_5.json \
  --output output_test_type_5.json

# or via rotate config (single profile, until captcha / all 12)
./scripts/run_rotate.sh scripts/rotate_config_test_type5.json
```

Notes:
- `azimon` / `tasnia` / `mustakim` may still be on captcha cooldown — `alamin` is usually the free one for this test.
- Exit code `2` = captcha; that combination is **not** marked done.

## 4. Experiment: profile switching

Edit [`scripts/rotate_config.json`](scripts/rotate_config.json), then run one command. Already-done combinations in `output.json` are skipped.

Path keys (`options`, `output`, `sheet`, `profile_status`) override [`app/config.py`](app/config.py) for that run. Omit a key to keep the default.

```json
{
  "mode": "round_robin",
  "profiles": ["azimon", "tasnia", "mustakim"],
  "service": "民泊清掃",
  "options": "combination_creation/options_type_5.json",
  "output": "output.json",
  "sheet": "zehitomo_main.csv",
  "profile_status": "scripts/profile_status.json",
  "batch_max": 6,
  "batch_size": 3
}
```

`mode` values:

| mode | meaning |
|---|---|
| `round_robin` | Way-1: each combination uses the next profile |
| `until_captcha` | Way-2: stay on a profile until captcha or `batch_max` |
| `batch` | Way-3: each profile does `batch_size` combos, then rotate |

Captcha cooldowns are tracked in `profile_status` (default [`scripts/profile_status.json`](scripts/profile_status.json)). When a profile hits captcha, it is marked `cooldown` for **3 days** (`cooldown_days`). Rotation only uses eligible profiles; cooled-down ones are skipped until `eligible_after`. After that time they become active again automatically. A successful scrape also marks the profile `active`.

```bash
# uses mode + settings from rotate_config.json
./scripts/run_rotate.sh

# override mode for one run
MODE=round_robin ./scripts/run_rotate.sh

# optional: another config file
./scripts/run_rotate.sh scripts/rotate_config.json
```

The individual scripts still work and also read the same JSON (CLI profile args override `profiles` if given):

```bash
./scripts/rotate_round_robin.sh
./scripts/rotate_until_captcha.sh
./scripts/rotate_batch.sh
```

