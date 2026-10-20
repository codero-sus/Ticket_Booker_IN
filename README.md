# Ticket_Booker_IN 🎫🇮🇳

Automates Indian railway ticket booking (**IRCTC**, **RailOne** roadmap) using the
[**Camoufox**](https://github.com/daijro/camoufox) stealth browser — with a
**zero-touch automatic captcha solver** (no clicking, no typing captchas).

```
login (auto captcha) → search → Tatkal countdown race → passengers → UPI assist → PNR
```

## ✨ Features

- **Camoufox stealth Firefox** — anti-fingerprinting, human-like mouse (`humanize`),
  Indian locale/timezone/geolocation, persistent profile (login once, reuse session).
- **Zero-touch captcha engine** (`src/ticket_booker/captcha/`):
  1. **Local OCR** (Tesseract + IRCTC-tuned preprocessing: denoise, Otsu/adaptive
     threshold, morphology) — free, offline, no API key.
  2. **Buster-style reCAPTCHA solver** — auto-clicks the checkbox; if challenged,
     switches to the **audio challenge**, downloads + transcribes it automatically.
     No button to press, no touch needed.
  3. **Paid fallback** — 2Captcha / AntiCaptcha image-to-text API.
  4. **Manual assist** — last resort: solve once in the open browser, bot continues.
- **Tatkal race mode** — NTP clock sync, precise 10:00 (AC) / 11:00 (Non-AC) countdown,
  availability refresh loop, instant Book-Now.
- **Safe payments** — bot never touches card/netbanking/OTP secrets. UPI tab + UPI ID
  pre-fill, you approve on your phone, bot captures the PNR.
- **Doctor + offline captcha test** — `ticket-booker doctor` checks every dependency;
  `ticket-booker solve-captcha img.png` tests OCR without a browser.
- **RailOne** — honest status: RailOne is a mobile app with no public web flow, so
  bookings fulfil via identical IRCTC-web inventory (same trains/PNR/fares); Appium
  adapter is on the roadmap (`ticket-booker railone --roadmap`).
- **BRUTE scraper tools** (`ticket-booker tool …`) — PNR status, seat/berth
  availability, train schedule/route, fare enquiry (dry-run, never pays), live
  running status. Text-first locators (immune to DOM reshuffles), auto-captcha on
  every page, retry + reload + re-login recovery, reports to `./reports/`.
- **Easy WebUI** (`ticket-booker webui`) — local dashboard that **auto-opens in
  Chrome**: one-click booking + tools, live log stream, config editor, captcha
  tester, job history. No terminal needed after launch.

## ⚠️ Disclaimer — read this

- For **personal use on your own IRCTC account**. Respect IRCTC's Terms of Use and
  fair-use limits; don't hammer their servers (refresh interval ≥ ~1s).
- Captcha automation exists so *you* don't have to babysit *your own* booking —
  don't use this to bulk-book, scalp, or resell (that's illegal under the Railways Act).
- Payments stay **human-in-the-loop by design**. Never put card/CVV/OTP in the config.
- IRCTC changes its site layout periodically — if a step breaks, check
  `src/ticket_booker/irctc/constants.py` (all selectors live there) and open a PR.

## 📦 Installation

**1. Python deps**

```bash
git clone https://github.com/codero-sus/Ticket_Booker_IN.git
cd Ticket_Booker_IN
pip install -r requirements.txt
```

**2. Camoufox browser binaries** (one-time download)

```bash
camoufox fetch
```

**3. System binaries for captcha solving**

```bash
# Ubuntu/Debian
sudo apt install tesseract-ocr ffmpeg

# macOS
brew install tesseract ffmpeg

# Windows: install Tesseract (UB-Mannheim build) + ffmpeg, add both to PATH
```

- `tesseract` → required for free local OCR.
- `ffmpeg` → required for reCAPTCHA *audio* mp3 decoding.

**4. Health check**

```bash
ticket-booker doctor
```

## 🚀 Quickstart

```bash
# 1. Create config
ticket-booker init-config          # writes config.json

# 2. Edit config.json (journey, passengers, credentials...)
#    Tip: keep secrets in env instead: IRCTC_USER / IRCTC_PASS / IRCTC_MOBILE / IRCTC_UPI

# 3. Validate everything
ticket-booker doctor --config config.json

# 4. Log in once (saves session to ./profiles/irctc)
ticket-booker login -c config.json

# 5a. Normal booking
ticket-booker book -c config.json

# 5b. Tatkal booking (NTP sync + 10/11 AM race + auto captcha)
ticket-booker tatkal -c config.json
```

Other commands:

```bash
ticket-booker search -c config.json        # login + search only (tests selectors safely)
ticket-booker solve-captcha shot.png       # offline OCR test on any captcha image
ticket-booker railone --roadmap            # RailOne status

# BRUTE scraper tools (all auto-solve captchas, all save ./reports/)
ticket-booker tool pnr --pnr 1234567890 -c config.json
ticket-booker tool availability -c config.json [--train 12430]
ticket-booker tool schedule --train 12430 -c config.json
ticket-booker tool fare -c config.json     # dry run to review page, STOPS before pay
ticket-booker tool live --train 12430 [--station CNB] -c config.json

# Easy WebUI (auto-opens in Chrome once ready)
ticket-booker webui                        # --port 8765 --no-open to skip Chrome
ticket-booker preflight -c config.json     # find booking-killers BEFORE race day
ticket-booker chaos                        # offline disaster drills (prove GOD survives)
ticket-booker ascend                       # BRUTE ALGEBRA: god of god of god of god
ticket-booker ascend "god^god"              # same dial, shorter warcry
ticket-booker ascend "ultimate brute god"   # 9,223,372,036,854,775,807
```

## ⚙️ Configuration (`config.json`)

| Section | Key fields |
|---|---|
| `irctc` | `username`, `password`, `mobile` (or `$IRCTC_USER` etc.) |
| `journey` | `from_station`/`to_station` codes (NDLS), `date` (YYYY-MM-DD of **journey**), `train_no` (5-digit or empty=any), `class_code` (SL/3A/2A/1A/CC/EC/2S/3E), `quota` (GN/TQ/PT/LD…) |
| `passengers` | up to 6 (4 for Tatkal): `name`, `age`, `gender` M/F/T, `berth` LB/UB/MB/SL/SU/WS/CP/NP, `food` Veg/Non Veg/No Food |
| `preferences` | `mobile`, `auto_upgrade`, `confirm_berths`, `travel_insurance` |
| `payment` | `method`: `manual` (default) or `upi` (+`upi_id` pre-fill), `wait_minutes` |
| `tatkal` | `enabled`, `arrive_minutes_early` (login+search done ahead), `refresh_interval_ms` |
| `browser` | `headless`, `humanize`, `profile_dir`, `locale`, `timezone`, `proxy`, `addons` (.xpi list) |
| `captcha` | see below |

### Captcha config

```json
"captcha": {
  "mode": "auto",
  "max_attempts": 6,
  "ocr":        { "enabled": true,  "psm_modes": [7, 8], "min_confidence": 25.0, "max_variants": 6 },
  "recaptcha_audio": { "enabled": true, "language": "en", "max_audio_attempts": 3 },
  "service":    { "enabled": false, "provider": "twocaptcha", "api_key": "", "poll_timeout": 120 },
  "on_failure": "manual",
  "debug_dir":  "./screenshots/captcha"
}
```

- `mode`: `auto` (zero-touch) · `manual` (always ask human) · `assist` (reserved).
- `service`: enable + set key (or `$CAPTCHA_API_KEY`) for 2Captcha/AntiCaptcha fallback.
- `on_failure: manual` + headed browser → bot pauses, you solve once, it continues.
  Set `"error"` for fully unattended runs (cron/VPS).
- Every captcha attempt is saved under `debug_dir` for tuning.

**Test OCR offline:** screenshot any IRCTC captcha, then
`ticket-booker solve-captcha captcha.png`.

## ⏱️ Tatkal playbook

1. Day before: `ticket-booker login` (warm session) and verify `doctor` is green.
2. Journey `date` = the train's **source-station starting date**; Tatkal opens one day
   before at **10:00 IST (AC)** / **11:00 IST (Non-AC)** — the bot NTP-syncs and counts down.
3. Run `ticket-booker tatkal -c config.json` ~15 min early. It logs in, searches,
   waits for the exact second, refreshes availability and books.
4. Payment: approve the UPI collect request on your phone; the bot grabs the PNR and
   screenshots the ticket.

Tips: wired/fast network, `block_images: false` (IRCTC needs its images), keep the
machine awake, and do a dry `search` run first.

## 🧰 BRUTE tools (scrapers that can't fail easily)

| Tool | What it does | Captcha? | Login? |
|---|---|---|---|
| `tool pnr --pnr …` | Passenger + chart status | ✅ auto | IRCTC session |
| `tool availability` | Seat/berth status per train+class | ✅ auto | IRCTC session |
| `tool schedule --train …` | Full route/halts via NTES (+IRCTC fallback) | ✅ auto | No |
| `tool fare` | Total fare via dry-run to review page, **stops before pay** | ✅ auto | IRCTC session |
| `tool live --train …` | Live running status / delay via NTES | ✅ auto | No |

Why they survive ("BRUTE"):
- **Text-first locators** — finds buttons/inputs by *visible text anywhere on the
  page* (`filter(has_text=…)`, XPath `contains()`), not brittle CSS paths. IRCTC can
  reshuffle divs and the tools still find "Submit".
- **Auto-captcha on every page** — any captcha image found is OCR'd and filled
  before each submit, with refresh-and-retry loops.
- **Retry + reload + re-login** — every step retries with page reloads and one
  session recovery per run; failures save screenshots.
- **Human delays** — randomised 2–10s style pauses between actions.
- **Reports always** — JSON + human-readable `.txt` in `./reports/` (like the
  sample grabber's credential file).

## 🖥️ Easy WebUI

```bash
ticket-booker webui
```

Starts a local server (default http://127.0.0.1:8765, auto-bumps if busy), waits
until `/api/health` is green, then **auto-opens the dashboard in Chrome**
(Chromium accepted, default browser as fallback). The dashboard has:

- 🩺 Doctor panel (deps, binaries, config health)
- 🎫 One-click Login / Search / Book / ⚡Tatkal
- 🧰 All 5 brute tools with input forms
- 🔓 Captcha tester (upload image → OCR result)
- 📋 Job history + 📜 live log stream + ⚙️ config editor + 💾 reports

API (for scripts): `GET /api/health /doctor /tools /jobs /logs /reports`,
`POST /api/run /tool /config /solve-captcha`, live `GET /api/stream` (SSE).

## 🧩 Project layout

```
src/ticket_booker/
  cli.py                 ticket-booker commands (book/tatkal/login/search/doctor/tool/webui/...)
  config.py              pydantic config + env overrides
  browser.py             Camoufox launcher (stealth, humanize, persistent profile)
  timing.py              IST clock, NTP sync, Tatkal countdown
  captcha/
    manager.py           AutoCaptcha solver chain
    ocr_solver.py        local Tesseract OCR (zero-touch text captchas)
    preprocess.py        IRCTC-tuned image cleaning (OpenCV/PIL)
    recaptcha_solver.py  Buster-style audio solver (zero-touch reCAPTCHA)
    service_solver.py    2Captcha / AntiCaptcha fallback
  irctc/
    constants.py         ALL selectors + label maps (edit here when IRCTC changes)
    login.py             login + captcha retry loop
    search.py            search + Tatkal refresh race
    passengers.py        passenger form fast-fill
    payment.py           UPI assist + PNR capture (human approves payment)
    booker.py            end-to-end orchestration
  tools/                 BRUTE scrapers (text-first + auto-captcha + reports)
    base.py              BruteContext: find/click/fill by text, retry, captcha-anywhere
    pnr.py / availability.py / schedule.py / fare.py / live_status.py
  webui/
    server.py            Flask API + jobs + SSE logs
    dashboard.html       single-file offline-safe dashboard
    launcher.py          serve + wait-ready + auto-open Chrome
  railone/               RailOne adapter (IRCTC fallback + roadmap)
tests/                   pytest unit tests (offline, no browser needed)
```

## ⚡ ULTIMATE BRUTE GOD mode (resilience dial)

Every tool runs on the GOD engine (`src/ticket_booker/god/` + `tools/base.py`):

| Brutality | Behavior |
|---|---|
| 1 calm | Minimal retries. Debugging only. |
| 2 normal | Classic retries + reload. |
| 3 BRUTE | + self-healing selectors, fuzzy fallback, diagnostics. |
| 4 GOD (default) | + block/ban detection, session keepalive, fresh-browser relaunch ladder. |
| 5 ULTIMATE | + max retries, screenshot every step, proxy rotation, no mercy. |
| 6-9 OMEGA | + HYDRA 2 heads racing, radioactive mutation, adaptive pacer, verified clicks. |
| 10+ RADIOACTIVE | + HYDRA 3 heads, captcha rotation ensemble, cookie vault, doomsday budget, GENOME. Max: 9223372036854775807. |
| > INT64_MAX VOID | + immortal retries, no doomsday, no pacer, omni-captcha (all solvers parallel), uncapped HYDRA, screenshot every step. NO MERCY. |
| any expression | BRUTE ALGEBRA: `god of god of god of god`, `god^god`, `brute!`, `void`, `infinity` — breaks INT64 into the VOID. |

Set it four ways: config `"brute": {"level": 9223372036854775807}`, CLI `--brutality 7`
or `--brutality "god of god of god of god"` (+`--heads 3`) on
`book`/`tatkal`/`tool`/`login`/`search`, the WebUI GOD-dial selector, or
`ticket-booker ascend <expression>` to preview any expression.

God powers:
- **Self-healing selectors** — `SelectorMemory` (`./profiles/selector_memory.json`)
  learns which locator strategy wins per action and tries winners first, across runs.
- **Fuzzy fallback** — "Submitt", "SUBMIT \u00BB", "Get Statuss" still match via
  similarity scoring when exact text fails.
- **Block/ban detection** — access-denied / rate-limit / bot-wall pages raise
  `BlockedError`; the ladder cools down or **rotates `brute.proxy_list`** and relaunches.
- **Session keepalive** — dead-session text mid-run triggers instant auto re-login.
- **Browser-death relaunch** — crash/target-closed aborts the ladder immediately and
  GOD rises a fresh browser (up to 4 rounds at level 5).
- **Captcha paranoia** — identical-image-after-refresh detection forces a real reload.
- **Black-box diagnostics** — ultimate failures save `./diagnostics/<ts>/` bundles
  (screenshot + HTML + URL + traceback + *redacted* config), safe for GitHub issues.
- **Stealth jitter** — human mouse drift before clicks, randomised delays everywhere.
- **HYDRA race** — OMEGA+ tools run 2-3 parallel browser heads; first success wins
  (`--heads N`, tools only — booking stays single-headed so you never double-book).
- **Cookie vault** — login once, `./profiles/session_vault.json` transplants the
  session into fresh heads (base64-obscured; treat like a password).
- **Adaptive pacer** — measures site latency and auto-tunes delays (fast site = faster bot).
- **Verified clicks** — submit clicks confirm the page actually changed, else escalate.
- **Captcha ensemble voting** — OCR readings across variants/PSMs/rotations vote; majority wins.
- **Doomsday budget** — `brute.max_tool_minutes` kills runaway runs (0 = immortal).
- **Flight recorder** - every action journaled to `./journals/*.jsonl` (what/when/outcome).
- **Perceptual verify (OMEGA+)** - submit clicks compare screenshot hashes, not just
  URLs/text, to catch visual stalls.
- **Payment bodyguard** - failure pages abort the wait instantly (no burning the full
  window); waiting screenshots every 60s.
- **Pre-flight** (`ticket-booker preflight`) - ARP window, Tatkal timing, pax limits,
  solvers, binaries: FAIL = do not fly.
- **CHAOS drills** (`ticket-booker chaos`) - scripted flaky actions, browser death,
  block walls, session rot, doomsday: GOD SURVIVES.

## APOTHEOSIS - TOO MUCH BRUTE (GOD6)

The dial no longer accepts "a number". It accepts **BRUTE ALGEBRA**:

```bash
ticket-booker ascend                             # god of god of god of god -> INT64 MAX
ticket-booker ascend "god^god"                   # same dial, shorter warcry
ticket-booker ascend "void"                      # INFINITE BRUTE VOID LVL 9,223,372,036,854,775,808
ticket-booker ascend "infinity"                  # INFINITE BRUTE VOID LVL 10^100
ticket-booker ascend "ultimate brute god"        # 9,223,372,036,854,775,807
ticket-booker book -c config.json --brutality "god of god of god of god"
ticket-booker tool live --train 12430 -c config.json --brutality "brute god!"
```

Grammar: `of` is exponentiation (right-associative), `*` multiplies, `!` is
factorial, `^` / `**` are powers, and words are constants:

| Word | Value |
|---|---|
| `brute` | 5 |
| `god` | 1,000,000 |
| `omega` | 999,999,999 |
| `brute god` | 10^9 |
| `ultimate god` | 10^12 |
| `ultimate brute god` / `radioactive` / `apotheosis` / `max` / `infinity` | 9,223,372,036,854,775,807 |

Everything saturates at int64 max - no wraparound, no overflow, no mercy.
The `--brutality` flag accepts these expressions everywhere (the WebUI sends
the same string; a typo returns HTTP 400 instead of killing the dashboard).
At the top the title stops being a name and starts being a genealogy:

```
THE ULTIMATE BRUTE GOD OF THE ULTIMATE BRUTE GOD OF THE ULTIMATE BRUTE GOD
OF THE ULTIMATE BRUTE GOD OF ... - RADIOACTIVE LVL 9,223,372,036,854,775,807
```

God powers added at this level:

- **GENOME** (`./profiles/genome.json`) - a persistent UCB1 bandit over nine
  locator strategies (text/xpath/css/label/placeholder/aria/role/js/keyboard).
  Untried strategies are explored first, winners are promoted across runs, old
  wins decay. `ascend` prints the leaderboard; `doctor` shows the champion.
- **CHRONOS WARBELL** - set `"brute": {"arm_at": "09:59:55",
  "arm_lead_seconds": 5}` and the process itself becomes the alarm clock:
  it sleeps in Ctrl-C-friendly chunks until 5 seconds before Tatkal, then
  launches the browser. `preflight` validates the time before race day.
- **Nine-deep title** - one extra `OF THE ULTIMATE BRUTE GOD` per digit of
  dial (capped at nine gods) so the log line matches the level.

## 🛠️ Troubleshooting

| Symptom | Fix |
|---|---|
| `camoufox fetch` not run | Run it once; `doctor` tells you. |
| OCR always fails | Install `tesseract` binary (not just pip pkg); check `./screenshots/captcha/` samples with `solve-captcha`. |
| Login loops on captcha | IRCTC may have changed the captcha style — open an issue with a sample (redact credentials). |
| `SIGN IN` / `Book Now` not found | IRCTC changed markup → update `irctc/constants.py` selectors, PRs welcome. |
| Session expired mid-Tatkal | Login closer to opening time; reduce `arrive_minutes_early`. |
| Audio reCAPTCHA fails | Install `ffmpeg`; needs internet for Google STT (or set `VOSK_MODEL_PATH` + `pip install vosk`). |
| Headless server | Use `headless: true` → auto virtual display (Xvfb); needs `xvfb` installed. |

## 🗺️ Roadmap

- [ ] Appium RailOne adapter (real device)
- [ ] Premium-Tatkal dynamic-fare display
- [ ] Multi-train preference list (fallback trains if WL)
- [ ] Auto berth/coach preference + chart prediction hints
- [ ] Selector self-healing + `doctor --fix` for common breakages

## 📄 License

MIT — see [LICENSE](LICENSE) (to be added). Use responsibly and at your own risk;
the authors aren't affiliated with IRCTC/RailOne and aren't liable for missed trains. 🚂
