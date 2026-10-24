# Run and demonstrate SafeWalk on Windows + Android

**Use a Windows laptop for the caregiver dashboard and Android Chrome for the Specs node.** Both devices must be on the same trusted Wi-Fi/LAN. The phone does not need Docker, Android Studio, an APK, or an app-store account.

This setup adds a local **Caddy HTTPS reverse proxy** and certificates generated with **mkcert**. No public tunnel, paid service, Cloudflare relay, or proprietary cloud API is required. Docker Desktop is a convenient Windows development host, not an application dependency; Docker Engine/Compose are the underlying portable runtime. Docker Desktop itself has separate licensing terms.

## 1. Prepare Windows once

Download the **updated** `SafeWalk_CivicMesh.zip`, extract it, and open PowerShell in the `safewalk-civicmesh` folder. The older ZIP may not have the mobile launcher or HTTPS override.

Install these if they are not already installed:

```powershell
winget install -e --id Docker.DockerDesktop
winget install -e --id FiloSottile.mkcert
```

Start Docker Desktop, complete any WSL2/restart prompts, and wait until Docker Engine is running. Use its **Linux containers / WSL2 backend**, not Windows containers. Reopen PowerShell after installation so `mkcert` is on PATH. You can verify prerequisites:

```powershell
docker info
docker compose version
mkcert -version
```

Use a trusted home Wi-Fi network or your own phone hotspot. On Windows, that trusted connection should have the **Private** network profile. Do not reclassify an untrusted/public network merely to bypass its security rules. School/office/guest Wi-Fi may block device-to-device traffic; use an approved network or ask its administrator.

## 2. Start the stack and create local HTTPS

In PowerShell, from the extracted project folder:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\start_mobile_demo.ps1
```

`-ExecutionPolicy Bypass` applies only to this invocation of the downloaded, inspectable launcher; it does not change the machine-wide execution policy. Do not use it to evade an organizational policy on a managed computer.

The launcher will:

1. Detect the laptop's IPv4 address; ask you to choose if there are multiple adapters.
2. Ask mkcert to trust your own local development CA on Windows.
3. Generate an HTTPS certificate valid for that LAN address and `localhost`.
4. Start PostgreSQL/Timescale/PostGIS, MQTT, Redis, MinIO, and FastAPI.
5. Start Caddy on **8443**, keeping raw backend HTTP bound to **127.0.0.1**.
6. Print your actual phone URL and generated access credentials.
7. Create a `phone-setup` folder containing the public CA, phone token, URL, and URL QR.

The initial build compiles MinIO and Timescale from source, so it can take a while. Let it finish; do not start multiple builds because it looks quiet. On later runs, use the cached images:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\start_mobile_demo.ps1 -SkipBuild
```

If the wrong adapter was detected, rerun with `-LanIp` followed by your actual laptop Wi-Fi IPv4 address shown by `ipconfig`. Do not use the phone's IP, a WSL/vEthernet IP, `localhost`, or a public internet IP. If DHCP changes the laptop IP, rerun the launcher; the phone URL and server certificate will update while the local CA normally remains the same.

## 3. Allow the phone through Windows Firewall

On your **trusted Private network**, open a separate **Administrator PowerShell** and run once:

```powershell
New-NetFirewallRule -DisplayName "SafeWalk HTTPS demo" -Direction Inbound -Action Allow -Protocol TCP -LocalPort 8443 -Profile Private -RemoteAddress LocalSubnet
```

Do not disable Windows Firewall. This rule allows only TCP 8443 from the local subnet on Private networks. If your computer is organization-managed, obtain its administrator's approval instead of circumventing controls.

Alternatively, an Administrator can run the launcher with `-OpenFirewall` to create the same scoped rule. It will not silently elevate or change an existing firewall rule.

## 4. Trust the certificate on Android — once

Transfer these two files from the generated `phone-setup` folder **privately**, preferably by USB:

- **`SafeWalk-CA.crt`** — your local public CA certificate.
- **`DEVICE_TOKEN.txt`** — a private bearer credential for the phone.

On Android, search Settings for **Install a certificate**. A common path is:

**Settings → Security & privacy → More security settings → Encryption & credentials → Install a certificate → CA certificate**.

Select `SafeWalk-CA.crt`. Android may require your screen-lock PIN and warn that a CA can monitor network traffic. Only install the certificate that **you generated on your own trusted laptop**. This grants trust to that local CA; remove it after the demo if you no longer need it.

**Never transfer `rootCA-key.pem`, `safewalk-key.pem`, or the whole `certs` folder to a phone or public location.** The launcher never copies the CA private key into the project. Do not share your device/caregiver tokens in a presentation recording or public repository.

Simply opening a self-signed page and clicking through Chrome's certificate warning is **not** the recommended camera setup. Install the proper CA and resolve the warning first.

## 5. Connect both screens

### Laptop

Open **https://localhost:8443/portal/** in Chrome or Edge. The certificate should now be trusted on Windows. In **Access settings**, paste the **Caregiver token** printed by the launcher.

If you need the tokens again:

```powershell
docker compose exec backend python -m backend.app.cli credentials
```

### Phone

Open the generated `phone-setup\PHONE_QR.png` on the laptop and scan it, or type the exact address from `phone-setup\OPEN_ON_PHONE.txt`. It has this structure:

**`https://your-laptop-Wi-Fi-IPv4:8443/specs/`**

The actual address is generated for you; the structure above is not a literal link. **Do not enter `localhost` on the phone**—that means the phone itself, not the laptop. Do not use the plain HTTP backend port 8000.

In **Android Chrome**, not an embedded messaging/browser preview:

1. Open Specs Settings and paste the contents of `DEVICE_TOKEN.txt` into **Device access token**.
2. Read and accept the camera/GPS and experimental-use notice.
3. For a live incident-video demonstration, also enable the **rolling video buffer**. Automatic impact alerts can stay off.
4. Tap **Enable & start session** and allow camera, location, and motion sensors if requested.
5. Point the rear camera at a safe indoor test scene. Hold a neutral forward pose and tap **Calibrate neutral tilt**.
6. Keep the phone **unlocked and foregrounded**. Wait for **VOICE CACHE · 40 / 40**.

The phone display is mostly black **by design**. Its live camera snapshots appear on the laptop. Monitoring stops when the browser is hidden or the phone locks; return and start the session again if that happens.

Optional: Chrome menu → **Install app / Add to Home screen** after the trusted HTTPS page is working. The PWA remains the same app; no APK build is needed.

## 6. Show the working in this order

Use a seated or supervised indoor demonstration. Do not walk into traffic, stage dangerous obstacles, drop the phone, or deliberately fall.

| Time | Action | What to show on the laptop |
|---|---|---|
| 0:00 | Start the Android Specs session; select its device ID in the dashboard menu. | Connected node, actual POV JPEG snapshots, GPS status/accuracy. Snapshot cadence is roughly 800 ms, not a 15 FPS video call. |
| 0:30 | Gently tilt the phone after neutral calibration. | Actual relative pitch/roll values change. This is a phone-IMU demonstration, not validated head tracking. |
| 0:45 | After the cache is ready, return to a neutral pose, tap **Calibrate neutral tilt**, then immediately **Replay guidance**. | A fresh calibration cue plays from the cache, forty decoded primitives, and scheduling status when reported. Cues older than 30 seconds are deliberately not replayed. Scheduling time is not guaranteed audible latency. |
| 1:00 | Double-tap the touch canvas; optionally toggle **RupeeGuard** with two fingers and show one test QR/note. | Limited visual-baseline description or read-only QR/OCR results. No banknote/payee authenticity claim or payment. |
| 1:30 | After at least ten seconds of recording, hold the canvas for two seconds, or press **Emergency caregiver alert** and confirm. | A real hub incident, factual SBAR, and available video archived to MinIO. Open **View SBAR → Load encrypted archive** to play it. No ambulance or 112 call is made. |
| 2:00 | Click **Run simulation**, then choose **demo-specs-a** in the device menu. | **Explicitly simulated** 165 cm overhead-height input and, around 12 seconds into the simulation, 45 cm drop-depth input. |
| 2:20 | Choose **demo-specs-b**. | The second simulated user receives a crowd-hazard warning before the 25 m zone. Configured warning distance is 45 m from the report. |
| 2:40 | Click **Inject test ticket**, then **GeoJSON** on the draft. | A downloadable PWD repair draft marked as a test/not submitted. |

Use **Test SOS** instead of a live phone alert if you want a synthetic incident/video with no live recording. If you want to show the impact logic, use the labelled test workflow; **do not throw, strike, or drop the phone to reach 3.5 g**.

### What is real versus simulated?

**Real:** camera capture, relative phone IMU, GPS when permitted, cached audio, telemetry, caregiver events, authenticated video upload, encryption, MinIO retrieval, SBAR formatting, database/geofence logic, and GeoJSON export.

**Not measured by the phone:** sonar, metric head clearance, or metric ground-drop depth. It is correct for the real phone session's centimetre gauges to show **—**. Use the labelled simulation for the 165/45 cm gauge demonstration; do not present those values as live camera-derived measurements.

**Not claimed:** general-purpose scene understanding, safe crossing, actual voice cloning, accredited clinical diagnosis, guaranteed <40 ms audible latency, municipal acknowledgement, or automatic emergency-service dispatch. The default voice is synthetic. Actual loved-one playback requires the consented recording pack described in README.

## 7. Troubleshooting

- **Phone cannot open the page:** same Wi-Fi/LAN, correct Wi-Fi IPv4, laptop awake, Docker running, Windows Private-network firewall rule. Disable neither the firewall nor an organization's policies. Guest Wi-Fi/AP isolation may block clients; use an approved network or your own hotspot.
- **Certificate warning:** install the public CA from this laptop, verify the URL uses the laptop IP for which the certificate was generated, correct phone date/time, and reopen Chrome. Rerun the launcher if the laptop IP changed.
- **Camera blocked:** use trusted HTTPS in a real Chrome tab; check Chrome site permissions and Android app camera permission. Don't use an embedded Arena/WhatsApp browser, an untrusted certificate, or plain LAN HTTP.
- **No orientation:** Chrome → site settings → Motion sensors; device/browser support varies. Physical-device calibration has not been certified.
- **No GPS or large uncertainty:** allow location if you consent. Indoor GPS may be poor. Civic proximity warnings are disabled for missing/inaccurate GPS; use the separate simulation to demonstrate the geofence logic.
- **Access denied:** use the device token on the phone and caregiver token on the laptop. They are different. Retrieve them with the CLI above.
- **Disconnected after switching apps:** intentional background safety stop. Restart the Specs session and keep it foregrounded.
- **No sound:** turn up media volume to a safe level, press a button to unlock playback, and wait for the cache. Preserve environmental hearing; don't use this app as a cane replacement.
- **Video not archived:** inspect the actual archive status. Check video-buffer consent, wait ten seconds, ensure the camera remains running, and check backend/MinIO logs. A phone that just started has less history. An unsupported recorder still sends SOS without video.
- **Build stopped:** read the error before rerunning. Let the first source build finish; a repeated build can compete for RAM/disk. Recommended free resources are documented in README.

## Stop and clean up safely

Stop the stack without deleting data:

```powershell
docker compose -f docker-compose.yml -f docker-compose.https.yml down
```

The data and encryption-key volumes remain. Do not add `-v` unless you intend to erase the database, objects, and archive key. Back up them together before destruction; a missing archive key makes old clips unreadable.

After the demo, you can remove the **SafeWalk HTTPS demo** firewall rule in Administrator PowerShell:

```powershell
Remove-NetFirewallRule -DisplayName "SafeWalk HTTPS demo"
```

Remove the installed demo CA from Android's **Trusted credentials → User** when no longer needed. Delete transferred token text from places where others could read it, and rotate credentials if exposed. `mkcert -uninstall` removes its CA from the Windows trust store; do not use it if you still need the CA for other local development projects.

The generated `certs` and `phone-setup` directories are excluded from Git, Docker build contexts, and the source packager. Never publish them or a screen recording containing credentials.
