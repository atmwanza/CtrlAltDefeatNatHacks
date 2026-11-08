# Raspberry Pi setup: finger-tapping camera

The software is finished and tested on the laptop. This guide gets the **Raspberry Pi 4 +
Camera Module V2** running it. No monitor, keyboard or micro-HDMI is needed.

**You need:** a USB microSD card reader, a **5 V / 3 A USB-C power adapter** (not a laptop
USB port), the camera with its ribbon cable and plastic focus tool, a bright desk lamp,
and tape. Optional: an LED, a 330 Ω resistor and 2 jumper wires.

**Hard rule:** if the Pi isn't recording good clips **2 hours after the camera arrives**,
stop and use the webcam: `start_demo.ps1 -Webcam`. The software and the tablet screen are
identical either way.

---

## 1. Laptop hotspot (2 min)
1. Open **Settings → Network & internet → Mobile hotspot**.
2. Under **Properties → Edit**, set:
   - **Band:** 2.4 GHz
   - **Security:** WPA2 if offered
3. Note the **network name and password exactly** (case-sensitive).
4. Turn **Power saving OFF**.

## 2. Write the SD card (15 min)
1. Install **Raspberry Pi Imager** from <https://www.raspberrypi.com/software/>.
2. Take the microSD out of the Pi and put it in the USB reader. If Windows offers to format it, click **Cancel**.
3. In Imager:
   - **Device:** Raspberry Pi 4
   - **OS:** *Raspberry Pi OS (other)* → **Raspberry Pi OS (Legacy, 64-bit) Lite**
   - **Storage:** the SD card. Check its size so you don't erase the wrong drive.
4. Customisation:
   - **Hostname:** `drawdx-pi`
   - **Localisation:** Canada / America/Edmonton
   - **Username:** `drawdx` (pick a password)
   - **Wi-Fi:** the hotspot name and password from step 1
   - **SSH:** enable, with password authentication
5. Click **Write**. When it finishes, put the card back in the Pi (contacts facing the board).

## 3. First boot and log in (5 min)
1. Hotspot ON. Plug in the Pi's power and **wait 3–5 minutes**.
2. The Pi appears under connected devices in the **Mobile hotspot** settings.
3. In PowerShell on the laptop:
```powershell
ssh drawdx@drawdx-pi.local          # or ssh drawdx@192.168.137.<number shown in hotspot settings>
```
Type `yes`, then your password. You'll see the prompt `drawdx@drawdx-pi:~ $`.

## 4. Install the software on the Pi (10 min)
```bash
sudo apt update
sudo apt install -y --no-install-recommends python3-picamera2
sudo apt install -y python3-flask python3-requests python3-gpiozero python3-lgpio python3-simplejpeg
sudo apt install -y rpicam-apps-lite || sudo apt install -y rpicam-apps
mkdir -p ~/drawdx
vcgencmd get_throttled              # want throttled=0x0 (anything else = weak power supply)
```
Copy the scripts over from the laptop (PowerShell, in the repo folder):
```powershell
scp pi\pi_capture.py pi\focus_check.py pi\drawdx-capture.service drawdx@drawdx-pi.local:~/drawdx/
```

## 5. Laptop: let the Pi in (once)
1. PowerShell **as Administrator**, in the repo folder:
```powershell
powershell -ExecutionPolicy Bypass -File tools\setup_firewall.ps1
```
2. Start the demo with `-Pi` (add `-Wireless` for the tablet as usual):
```powershell
powershell -ExecutionPolicy Bypass -File start_demo.ps1 -Wireless -Pi
```
3. Check the connection from the Pi:
```bash
curl -s http://192.168.137.1:5000/health        # want {"ok":true,...}; a hang = firewall
```

## 6. Camera (when it arrives)
1. **Power off first:** `sudo shutdown -h now`, wait for the green light to stop, then unplug.
2. Find the **CAMERA** connector between the micro-HDMI ports and the audio jack.
3. Lift its plastic flap 1–2 mm.
4. Insert the ribbon with the **metal contacts facing the HDMI ports**, press the flap down, and check the camera end is seated too.
5. Power on, SSH in, and run:
```bash
rpicam-hello --list-cameras          # want: imx219 [3280x2464 ...]
```

**Focus for 45 cm** (the V2 ships focused far away):
1. Tape a page of small text 45–50 cm from the lens.
2. Run:
```bash
python3 ~/drawdx/focus_check.py
```
3. Turn the lens with the plastic tool **1/8 turn at a time**. Anticlockwise focuses closer, and the first turn may be stiff.
4. Stop at the highest number. Ctrl+C to exit.

**Lighting:** aim a bright desk lamp at the hand. Horizontal bands in the picture mean
the lamp flickers; use a USB/battery LED, or set `EXPOSURE_US=8333`.

## 7. Run it
Quick test by hand (Ctrl+C to stop):
```bash
python3 ~/drawdx/pi_capture.py
```
The tablet's **Tapping** tab should show **"● Pi camera connected"** and a live preview.
Mark the hand position on the table with tape, then record a hand.

Make it start on every boot:
```bash
sudo cp ~/drawdx/drawdx-capture.service /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now drawdx-capture
journalctl -u drawdx-capture -f     # live log: look for "fps=40.0 ... drops=0"
```
Keep Wi-Fi reconnecting forever after hotspot blips:
```bash
nmcli -t -f NAME,TYPE con show                                   # find the Wi-Fi profile name
sudo nmcli con mod "<that name>" connection.autoconnect-retries 0
```

## 8. Optional: "recording" LED (Pi powered off)
Wire **GPIO17 (pin 11) → 330 Ω resistor → LED long leg**, and **LED short leg → GND (pin 9)**.
It's solid while recording and blinks while uploading. The script runs fine without it.

## 9. Optional: Ethernet fallback (if a friend has a cable)
On the Pi (once, while Wi-Fi works):
```bash
sudo nmcli con add type ethernet ifname eth0 con-name direct ipv4.method manual ipv4.addresses 10.42.0.2/24 ipv6.method ignore
```
On the laptop:
1. Go to **Settings → Network & internet → Ethernet → IP assignment → Manual**.
2. Set IPv4 to `10.42.0.1`, mask `255.255.255.0`, and leave the gateway empty.

The capture script tries the Ethernet address automatically if Wi-Fi fails.

## Tests to run and screenshot (for the pitch)
| Test | How | Pass |
|---|---|---|
| Camera | One recording; check `journalctl` | fps 39–41, drops 0 |
| Still hand | Hold the hand still, slightly open, and record | "Only 0 taps", low aperture SD |
| Metronome | Phone metronome at 120 / 180 / 240 bpm, tap on the click | Speed 2.0 / 3.0 / 4.0 taps/s (±0.1) |
| Shrinking taps | Deliberately make each tap smaller | Size change clearly negative, last-vs-first well under 100% |
| Repeatability | 3 people × 3 trials | Speed and size similar between trials |
| Fallback | `start_demo.ps1 -Webcam` | Same screen works with the laptop webcam |

## If something goes wrong
| Problem | Fix |
|---|---|
| Pi never shows in hotspot devices | Retype the Wi-Fi name and password in Imager and re-flash; hotspot on 2.4 GHz, WPA2 |
| `drawdx-pi.local` not found | Use the IP from the hotspot settings page |
| SSH `Permission denied` | Username is `drawdx`, not `pi` |
| SSH warns the host key changed | Run `ssh-keygen -R drawdx-pi.local` |
| `throttled=0x50005` or random reboots | Weak power supply: use a 5 V / 3 A adapter |
| `No cameras available` | Power off, reseat both ends of the ribbon (contacts towards HDMI) |
| Blurry hand | Refocus (step 6) |
| Dark or grainy | More light, or `GAIN=6` |
| Tablet says "Camera not connected" | Is the backend started with `-Pi`? Run `curl` from the Pi (step 5); check the firewall |
| `drops` > 0 | `JPEG_QUALITY=75` or `FPS=30` |

Settings can be changed without editing code. Set them in front of the command, for example:
```bash
FPS=30 EXPOSURE_US=8333 python3 ~/drawdx/pi_capture.py
```
(For the service, add `Environment=FPS=30` lines under `[Service]`.)
