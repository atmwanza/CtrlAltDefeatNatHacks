# USB Debugging Setup — Galaxy Tab S10 FE

Goal: `http://localhost:5000` on the tablet's Chrome talks to the laptop's DrawDx server over USB, with no WiFi dependency. `localhost` is also required for the PointerEvent API's Secure Context checks — `http://192.168.x.x` does not count as secure.

## 1. Enable Developer Options on the tablet

1. Settings → About tablet → Software information.
2. Tap "Build number" 7 times until "Developer mode has been enabled" appears.
3. Settings → Developer options → enable **USB debugging**.

## 2. Install ADB on the laptop

**Windows**
```bash
winget install Google.PlatformTools
```
Or download `platform-tools` from https://developer.android.com/tools/releases/platform-tools and add it to PATH.

**macOS**
```bash
brew install android-platform-tools
```

**Linux**
```bash
sudo apt install adb
```

## 3. Connect and authorize

1. Plug the tablet into the laptop with a USB-C cable.
2. On the tablet, a prompt appears: "Allow USB debugging?" → tap **Allow**.
3. Verify the connection:
   ```bash
   adb devices
   ```
   Should list the tablet's serial number with state `device` (not `unauthorized` — if so, re-check the prompt on the tablet).

## 4. Forward the port

```bash
adb reverse tcp:5000 tcp:5000
```
This maps `localhost:5000` on the tablet to `localhost:5000` on the laptop. Re-run this any time the tablet is unplugged and replugged.

## 5. Open the app

On the tablet, open Chrome and navigate to:
```
http://localhost:5000
```

## 6. Chrome DevTools remote debugging (recommended during dev)

1. On the laptop, open Chrome and go to `chrome://inspect/#devices`.
2. The Galaxy Tab should appear with its open tabs listed underneath.
3. Click **inspect** under the DrawDx tab.
4. Full DevTools opens on the laptop, attached to the tablet's browser — `console.log` output from `app.js`, breakpoints, and live inspection of PointerEvent data all work from here.

## Fallbacks

### A — Phone hotspot
Hackathon/university WiFi usually enforces AP client isolation, so devices on it can't reach each other. A phone hotspot does not have this restriction.
1. Turn on a phone's hotspot.
2. Connect both the laptop and the tablet to it.
3. Find the laptop's IP:
   - Windows: `ipconfig | findstr IPv4`
   - macOS/Linux: `ifconfig | grep inet`
4. On the tablet, open `http://<laptop-ip>:5000`.

### B — ngrok
Gives a public HTTPS URL, which satisfies the Secure Context requirement from anywhere:
```bash
ngrok http 5000
```
Open the printed `https://xxxx.ngrok.io` URL on the tablet.

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `adb devices` shows nothing | Cable is charge-only, or debugging not enabled | Use a data-capable USB-C cable; recheck Developer options |
| Device listed as `unauthorized` | Didn't tap Allow on the tablet's prompt | Unplug/replug, watch for the prompt, tap Allow |
| `localhost:5000` doesn't load on tablet | `adb reverse` not run, or ran before reconnecting | Re-run `adb reverse tcp:5000 tcp:5000` after every reconnect |
| S Pen pressure reads constant 0.5 | Chrome quirk on some builds | Try Samsung Internet; also verify with `https://hardwaretest.org/stylus-test/` |
| Page loads but PointerEvent API missing features | Not a Secure Context | Confirm the address bar says exactly `localhost`, not an IP address |
| Long S Pen press opens a context menu, drawing stops | Android Chrome's default long-press behavior | Already handled in `app.js` via `contextmenu` preventDefault — if it still happens, check that handler is attached to the canvas, not a parent element |
