# VNC usage — see and control Chrome on the Hostinger VPS

## What VNC is and why we need it

VNC (Virtual Network Computing) lets you **see and control another computer's screen** from your own machine (similar idea to TeamViewer / AnyDesk).

The scraper uses a **visible (non-headless) Chrome**, and the Zehitomo login must be done **by hand**. The VPS has no monitor, and inside Docker Chrome draws on **Xvfb**, an invisible virtual screen. VNC lets you see that screen:

```
Chrome  →  Xvfb virtual screen :99  →  x11vnc (port 5900)  →  SSH tunnel  →  VNC viewer on your Mac / PC
```

- `x11vnc` is **already inside the Docker image** (see `Dockerfile` and `docker/entrypoint.sh`). Nothing to install on the VPS itself apart from Docker.
- `docker-compose.yml` publishes port 5900 on the VPS's `127.0.0.1` only, so it is **not open to the internet**. You reach it through an SSH tunnel.

---

## 1. One-time VPS setup

```bash
ssh root@<vps-ip>
git clone <repo-url> zehitomo_new        # skip if already cloned
cd ~/zehitomo_new

# Docker (skip if `docker --version` works)
curl -fsSL https://get.docker.com | sh
```

Create `.env` in `~/zehitomo_new` (it is **not** in git — copy it with `scp .env root@<vps-ip>:~/zehitomo_new/` or create it with `nano .env`):

```text
GOOGLE_API_KEY=...
GOOGLE_MODEL=gemini-3.6-flash

# VNC — keep VNC on every time the container starts
VNC=1
VNC_PASSWORD=zehi1234        # choose your own; VNC uses only the first 8 characters
```

> **macOS Screen Sharing needs a password.** Without `VNC_PASSWORD` it shows
> "Screen Sharing requires a password to sign in to localhost" and cannot connect.
> This is the VNC password from `.env` — **not** your Mac password.

Also copy `credentials/` if you use Google Drive sync.

---

## 2. Build and start the container (on the VPS)

```bash
cd ~/zehitomo_new
docker-compose up -d --build
docker logs zehitomo_new_scrape_1 | grep entrypoint
```

Expected:

```
[entrypoint] starting Xvfb on :99 ...
[entrypoint] starting x11vnc on :5900 (display :99) ...
```

Check inside the container:

```bash
docker exec -it zehitomo_new_scrape_1 bash
echo "VNC=$VNC"; pgrep -a x11vnc       # expect VNC=1 and an x11vnc line
```

### Restarting after changing `.env` (old `docker-compose` 1.29.2)

The VPS has the old `docker-compose` (with a hyphen). It **crashes on recreate** with
`KeyError: 'ContainerConfig'`. So:

```bash
# ✅ do this
docker-compose down
docker-compose up -d

# ❌ never this with the old tool
docker-compose up -d --force-recreate
```

`down` only removes this project's container — other apps on the VPS (n8n, ecommerce, …) are not touched. Code, `profiles/` and `.env` live on the VPS disk, so nothing is lost.

If a broken renamed container is left over (e.g. `68fe754964f6_zehitomo_new_scrape_1`):

```bash
docker ps -a | grep scrape
docker rm -f <container-id>
docker-compose up -d
```

**Permanent fix:** install Compose v2 and use `docker compose` (space, no hyphen):

```bash
apt-get update && apt-get install -y docker-compose-plugin   # or: docker-compose-v2
docker compose version
```

---

## 3. Connect from your Mac

**Terminal window 1 — SSH tunnel (keep it open the whole time):**

```bash
ssh -L 5901:localhost:5900 root@<vps-ip>
```

Local port **5901** is used on purpose: if the Mac's own Screen Sharing is enabled it already uses 5900.

**Terminal window 2 (Cmd+T) — open the viewer:**

```bash
open vnc://localhost:5901
```

(or Finder → Go → Connect to Server… → `vnc://localhost:5901`)

- Password = `VNC_PASSWORD` from `.env`. If it asks for a username, leave it empty / type anything.
- A **black screen** means it works — it's the container's empty screen.

## 3b. Connect from a Linux PC

```bash
sudo apt install tigervnc-viewer                 # once

ssh -L 5901:localhost:5900 root@<vps-ip>         # terminal A, keep open
vncviewer localhost:5901                         # terminal B
```

---

## 4. Log in a Zehitomo account (once per account)

In the SSH window (window 1):

```bash
docker exec -it zehitomo_new_scrape_1 bash
python login_profile.py tasnia
```

1. Chrome appears in the VNC window
2. Click 「ログイン」 and sign in
3. Check the round profile icon in the top-right corner → logged in
4. Close Chrome (X button in the VNC window)
5. Press **ENTER** in the SSH window

Repeat for every name in `scripts/rotate_config.json` → `"profiles"`:

```bash
python login_profile.py alamin
python login_profile.py mustakim
```

Profiles are saved to `~/zehitomo_new/profiles/<name>/` on the VPS. Profiles from your Mac / PC do **not** work on the VPS — log in on the VPS itself.

---

## 5. Test and run the scraper (inside the container)

```bash
docker exec -it zehitomo_new_scrape_1 bash
```

**Test one combination** (watch it in the VNC window):

```bash
python -m app.main tasnia --service 民泊清掃 --rerun --combination combination1 \
  --options combination_creation/Output/options_type_5_tokyo.json
```

`--rerun` is needed if `output.json` already marks that combination as done. If the agent does **not** call `wait_for_manual_login`, the login worked.

**Full rotation** (uses `scripts/rotate_config.json`):

```bash
./scripts/run_rotate.sh
```

`Missing profile: profiles/<name>` → that account is listed in `rotate_config.json` but not logged in on the VPS yet (step 4), or remove it from `"profiles"`.

---

## 6. Try the whole flow locally on a Linux PC (optional)

Your Linux PC can act as both "VPS" and "viewer" — no SSH tunnel needed:

```bash
sudo apt install tigervnc-viewer
cd ~/zehitomo_new
VNC=1 docker compose up --build                    # terminal 1
vncviewer localhost:5900                           # terminal 2
docker compose exec scrape python login_profile.py vnctest   # terminal 3
```

Use a throwaway profile name (`vnctest`): the container runs as root, so it creates root-owned files. Clean up with `sudo rm -rf profiles/vnctest profiles/vnctest.chrome.log`.

On a Linux desktop you normally **don't need VNC** — run `python login_profile.py <name>` and `./scripts/run_rotate.sh` directly on the host (with `.venv` active).

---

## Troubleshooting

| Problem | Fix |
|---|---|
| "Screen Sharing requires a password" | Set `VNC_PASSWORD` in `.env`, then `docker-compose down && docker-compose up -d`. Enter that password (not your Mac password). |
| `KeyError: 'ContainerConfig'` | Old `docker-compose` bug. `docker-compose down` then `docker-compose up -d`. Never `--force-recreate`. |
| VNC window won't connect | Is the SSH tunnel window still open? In the container: `pgrep -a x11vnc` and `tail /tmp/x11vnc.log`. |
| `VNC=` is empty in the container | Add `VNC=1` to `.env`, then `down` + `up -d`. |
| Chrome doesn't appear / "Chrome exited immediately" | `tail profiles/<name>.chrome.log` inside the container. |
| `Missing profile: profiles/<name>` | Run `python login_profile.py <name>` (step 4) or remove the name from `rotate_config.json`. |
| `Permission denied` on `profiles/` (Linux PC) | Files were created by the root container: `sudo chown -R $USER:$USER profiles` (or delete the folder if empty). |
| Scraper calls `wait_for_manual_login` | Session expired or profile from another machine — log in again (step 4). |

## Security notes

- Port 5900 is bound to the VPS's `127.0.0.1` only — **don't** open 5900 in the Hostinger firewall. Always use the SSH tunnel.
- Keep `.env` (API key, VNC password) out of git — it is already in `.gitignore`.
- Prefer an SSH key over the root password for `ssh root@<vps-ip>`.
