# Real phone camera through GitHub — no Windows Docker or WSL

This runs the **original Specs app and Python backend**, not the offline HTML simulation. Use **GitHub Codespaces**, not GitHub Pages. Pages cannot run FastAPI, WebSockets or the database services.

**Hosting change:** the backend runs on GitHub's cloud, not your Windows laptop. This is a development/test deployment using **SQLite + encrypted local filesystem storage**. It does not start PostgreSQL/Timescale/PostGIS, MQTT, Redis or MinIO. The complete production Compose stack remains included for later.

Codespaces availability, quotas and billing depend on your GitHub account. First-time image creation and dependency downloads can take several minutes or longer; **five minutes is not guaranteed**. No real GitHub Codespace has been provisioned or tested from this conversation.

## 1. Put the extracted source in a repository

On your laptop:

1. Download the **GitHub-ready ZIP** supplied with these instructions and choose **Extract All**.
2. Open the inner `safewalk-civicmesh` folder. You should see `.devcontainer`, `backend`, `specs_app`, `scripts`, and `docker-compose.yml`.
3. On GitHub, create a new **private repository**, for example `safewalk-camera`.
4. Choose **uploading an existing file** or **Add file → Upload files**.
5. Drag the **contents of the inner project folder** into the upload area and commit them. Do not upload only the ZIP, and do not add a containing `safewalk-civicmesh` directory above everything.
6. Confirm the repository root has **`.devcontainer/devcontainer.json`**. This file is what makes the automatic setup work.

No `.env`, credentials, medical clips, generated certificates or runtime data are included in the ZIP. Never upload them later either. `.env.example` is only a public settings example; do not rename it to `.env` for this standalone setup.

## 2. Create the Codespace

1. In the repository, click **Code → Codespaces → Create codespace on main** (or your actual default branch).
2. Allow the image and setup commands to finish. The configuration installs Python dependencies, ffmpeg, eSpeak and OCR, creates random private app credentials, and warms forty real audio phrases.
3. The backend starts automatically on port **8000**.
4. If prompted to use the repository's devcontainer, select it. If you created a Codespace before adding `.devcontainer`, run **Codespaces: Rebuild Container** from the command palette.

If setup fails, inspect its actual error. Do not delete the `.env` archive key or disable authentication to get past an error.

## 3. Get your addresses and app tokens

In the Codespace's browser editor, open **Terminal → New Terminal** and run:

```bash
bash scripts/codespace_info.sh
```

It prints:

- The **laptop dashboard** HTTPS address ending in `/portal/`.
- The **phone camera app** HTTPS address ending in `/specs/`.
- A **Device token** for Specs.
- A different **Caregiver token** for the dashboard.

These are application keys. **Do not use, print or share a GitHub personal access token or the Codespace's `GITHUB_TOKEN`.** Do not put SafeWalk tokens in URLs, repository files, screenshots or recordings.

In the editor's **PORTS** tab, make sure **8000** is forwarded and keep its **Port Visibility = Private**. If it is missing, click **Add port → 8000**.

Leave **Port Protocol = HTTP**: that describes the connection to Uvicorn inside the Codespace. The browser-facing forwarded address is still **HTTPS**. Do not switch the internal listener to HTTPS; this app has no TLS server on internal port 8000.

## 4. Open the actual camera on Android

1. Open the printed **phone `/specs/` address** directly in **Android Chrome**, not an embedded editor preview.
2. Sign into the same GitHub account if the private forwarded port asks you to authenticate. Keep the port private; do not publish it just to avoid signing in.
3. In Specs Settings, paste the **Device token** from the private operator terminal. You can view that terminal on the phone to copy the token if needed; never publish it.
4. Accept the camera/GPS and experimental-use notice.
5. Optionally enable the **rolling video buffer** to test actual incident clips. Leave automatic impact alerts off for a safe demonstration.
6. Tap **Enable & start session** and grant the camera/location/motion permissions you consent to.
7. Keep the phone unlocked and foregrounded. Point its rear camera at a safe indoor scene, and tap **Calibrate neutral tilt**.

No Android CA installation, LAN firewall change, APK, local Docker, WSL, phone hotspot, or shared Wi-Fi is required for this route. Both devices need internet access. Camera permission is still controlled by Android/Chrome and must be granted by you.

## 5. Watch the real images on the laptop

1. Open the printed **dashboard `/portal/` address** in a normal browser tab.
2. In **Access settings**, enter the **Caregiver token**.
3. Select the actual phone's device ID, not a `demo-specs-*` node.
4. The phone display is mostly black **on purpose**. Its actual camera snapshots are visible in the caregiver dashboard at roughly 800 ms cadence, not a 15 FPS call.
5. Gently tilt the calibrated phone to see actual relative pitch/roll. GPS depends on device permissions and accuracy.
6. Wait for **VOICE CACHE · 40 / 40**. Calibrate once more and immediately press **Replay guidance** to exercise a fresh cached cue.
7. If you opted into recording, wait at least ten seconds, then use the manual caregiver alert. The incident/SBAR and available encrypted video are saved on the Codespace's filesystem, **not MinIO** in this quick profile.

Metric head-clearance/drop gauges may correctly show **—**. A phone has no sonar or verified metric depth here. Use the dashboard's explicitly labelled simulation only for metric-input/geofence test cases. Computer-vision cues are a limited OpenCV baseline, not a general-purpose trained object detector. Do not stage a fall, drop the phone, or rely on this app for navigation or medical care.

## Manual recovery commands — only if needed

If automatic setup has not run:

```bash
bash scripts/setup_codespace.sh
bash scripts/start_codespace.sh
```

The start helper avoids starting a second instance if its recorded server is already running. Logs are in `data/codespace-server.log`; keep them private. Application credentials can be displayed again with:

```bash
bash scripts/codespace_info.sh
```

If the Codespace is stopped, the app is unavailable. Resume the Codespace to restart it. If a repository or network policy blocks Codespaces, ask the relevant administrator rather than circumventing it.

## Privacy, persistence and cost

This is real camera/GPS data being sent to **your GitHub-hosted Codespace**, with GitHub's infrastructure and your GitHub account as part of the trust boundary. Obtain consent; use your own safe indoor test scene, not unsuspecting people or patients.

- Keep the repository and forwarded port private.
- Distinct application role tokens remain required in addition to GitHub's private-port login.
- Database files, encrypted clips and generated voices stay under git-ignored `data/`; `.env` holds the archive key and app credentials. Never commit either.
- Back up **data + its matching encryption key** securely together if you need to retain test footage. Deleting the Codespace can delete that data. Do not regenerate `.env` for existing footage.
- Stop the Codespace when finished to stop compute usage; retained storage can still count against your allowance or bill. Review your account's current Codespaces limits and billing before starting.
- This is not an always-on production host, high-availability service or safety-certified deployment. The application remains portable; Codespaces is a hosting convenience, not a required proprietary application API.

Official port-forwarding documentation: https://docs.github.com/en/codespaces/developing-in-a-codespace/forwarding-ports-in-your-codespace
