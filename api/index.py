"""
Tatkal Agent — Web Configuration UI
Deployed on Vercel as a FastAPI serverless function.

Workflow for users:
  1. Fill in booking details on this web page
  2. Submit → downloads tatkal_config.zip  (encrypted config + salt)
  3. Extract both .enc and .bin files into your local tatkal-agent/ directory
  4. Run: python main.py check   →   python main.py run
"""

import base64
import io
import json
import os
import zipfile

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, StreamingResponse, JSONResponse

app = FastAPI(title="Tatkal Agent")


# ── Encryption (mirrors config.py but fully in-memory) ────────────────────────

def _derive_key(passphrase: str, salt: bytes) -> bytes:
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(), length=32, salt=salt, iterations=480_000
    )
    return base64.urlsafe_b64encode(kdf.derive(passphrase.encode()))


def encrypt_config(data: dict, passphrase: str) -> tuple[bytes, bytes]:
    salt = os.urandom(16)
    key = _derive_key(passphrase, salt)
    token = Fernet(key).encrypt(json.dumps(data).encode())
    return token, salt


# ── Routes ────────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def index():
    return _HTML


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/api/configure")
async def configure(request: Request):
    try:
        data = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON body"}, status_code=400)

    passphrase = data.pop("passphrase", "").strip()
    if not passphrase:
        return JSONResponse({"error": "Passphrase is required"}, status_code=400)

    config = {
        "username":              data.get("username", ""),
        "password":              data.get("password", ""),
        "train_number":          data.get("train_number", ""),
        "from_station":          data.get("from_station", "").upper(),
        "to_station":            data.get("to_station", "").upper(),
        "journey_date":          data.get("journey_date", ""),
        "travel_class":          data.get("travel_class", "SL"),
        "boarding_point":        (data.get("boarding_point") or data.get("from_station", "")).upper(),
        "passengers":            data.get("passengers", []),
        "mobile":                data.get("mobile", ""),
        "payment":               data.get("payment", {}),
        "book_only_if_confirmed": data.get("book_only_if_confirmed", True),
        "captcha_api_key":       data.get("captcha_api_key") or None,
    }

    enc_bytes, salt_bytes = encrypt_config(config, passphrase)

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("booking_config.enc", enc_bytes)
        zf.writestr("booking_salt.bin",   salt_bytes)
        zf.writestr("README.txt", (
            "Tatkal Agent — Config Files\n"
            "============================\n\n"
            "1. Copy booking_config.enc and booking_salt.bin into your tatkal-agent/ folder\n"
            "2. Run: python main.py check   (enter your passphrase when prompted)\n"
            "3. Morning before journey: python main.py run   (keep terminal open)\n\n"
            "Your passphrase is NOT included here — keep it safe.\n"
            "Agent source: https://github.com/bharani-mandapaka/tatkal\n"
        ))
    buf.seek(0)

    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": "attachment; filename=tatkal_config.zip"},
    )


# ── Single-page HTML app ──────────────────────────────────────────────────────

_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Tatkal Agent — Configure Booking</title>
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
  <style>
    *{box-sizing:border-box;margin:0;padding:0}
    body{font-family:'Inter',system-ui,sans-serif;background:#f0fdf4;color:#0f172a;min-height:100vh}

    /* Header */
    .hdr{background:#15803d;color:#fff;padding:1.5rem 2rem}
    .hdr h1{font-size:1.75rem;font-weight:700}
    .hdr p{opacity:.85;margin-top:.25rem;font-size:.9375rem}

    /* Banners */
    .banner{max-width:840px;margin:.75rem auto;padding:.75rem 1rem;border-radius:0 8px 8px 0;font-size:.875rem;line-height:1.5}
    .banner-warn{background:#fef3c7;border-left:4px solid #f59e0b}
    .banner-info{background:#dbeafe;border-left:4px solid #3b82f6}

    /* Layout */
    .wrap{max-width:840px;margin:0 auto;padding:1.25rem 1rem 4rem}

    /* Progress pills */
    .pills{display:flex;gap:.5rem;margin-bottom:1.75rem}
    .pill{flex:1;height:4px;background:#dcfce7;border-radius:99px;transition:background .25s}
    .pill.on{background:#16a34a}

    /* Cards */
    .card{background:#fff;border-radius:12px;padding:1.75rem;box-shadow:0 1px 3px rgba(0,0,0,.08);margin-bottom:1rem}
    .card h2{font-size:1.1rem;font-weight:600;color:#15803d;margin-bottom:1.25rem}

    /* Grid */
    .g2{display:grid;grid-template-columns:1fr 1fr;gap:1rem}
    @media(max-width:580px){.g2{grid-template-columns:1fr}}

    /* Fields */
    .f{margin-bottom:.875rem}
    .f label{display:block;font-size:.8125rem;font-weight:500;color:#374151;margin-bottom:.3rem}
    .f input,.f select{width:100%;padding:.6rem .875rem;border:1.5px solid #d1fae5;border-radius:8px;font-size:.9375rem;background:#f9fffe;outline:none;transition:border-color .15s,box-shadow .15s;font-family:inherit}
    .f input:focus,.f select:focus{border-color:#16a34a;box-shadow:0 0 0 3px rgba(22,163,74,.12)}
    .f .hint{font-size:.75rem;color:#6b7280;margin-top:.25rem}
    .f.full{grid-column:1/-1}

    /* Passenger block */
    .pax{border:1.5px solid #dcfce7;border-radius:10px;padding:1.25rem;margin-bottom:.875rem;background:#f9fffe}
    .pax-hdr{display:flex;justify-content:space-between;align-items:center;margin-bottom:1rem;font-weight:600;color:#15803d}
    .rm{background:none;border:none;color:#ef4444;cursor:pointer;font-size:1.25rem;padding:0 .25rem;line-height:1}

    /* Payment tabs */
    .ptabs{display:flex;gap:.5rem;margin-bottom:1.25rem}
    .ptab{flex:1;padding:.6rem;border:2px solid #d1fae5;border-radius:8px;text-align:center;cursor:pointer;font-size:.875rem;font-weight:500;background:#f0fdf4;transition:all .15s}
    .ptab.on{border-color:#16a34a;background:#dcfce7;color:#15803d}

    /* Buttons */
    .btn{padding:.7rem 1.5rem;border-radius:8px;font-size:.9375rem;font-weight:600;cursor:pointer;border:none;transition:all .15s;font-family:inherit}
    .btn-add{background:#dcfce7;color:#16a34a;border:1.5px dashed #86efac;padding:.45rem 1rem;border-radius:8px;cursor:pointer;font-size:.875rem;font-weight:500;margin-top:.25rem}
    .btn-add:hover{background:#bbf7d0}
    .nav{display:flex;gap:.75rem;margin-top:1.25rem}
    .back{background:#f3f4f6;color:#374151;flex:1}
    .back:hover{background:#e5e7eb}
    .nxt{background:#16a34a;color:#fff;flex:2}
    .nxt:hover{background:#15803d;box-shadow:0 4px 12px rgba(22,163,74,.3)}
    .submit{background:#16a34a;color:#fff;width:100%;margin-top:1.25rem;padding:.85rem}
    .submit:hover:not(:disabled){background:#15803d;box-shadow:0 4px 16px rgba(22,163,74,.35);transform:translateY(-1px)}
    .submit:disabled{opacity:.6;cursor:not-allowed}

    /* Spinner */
    .spin{display:inline-block;width:1.1rem;height:1.1rem;border:2px solid rgba(255,255,255,.35);border-top-color:#fff;border-radius:50%;animation:sp .75s linear infinite;vertical-align:middle;margin-right:.4rem}
    @keyframes sp{to{transform:rotate(360deg)}}

    /* Success */
    .suc{display:none;text-align:center;padding:3rem 1rem}
    .suc .ck{font-size:4rem;margin-bottom:1rem}
    .suc h2{font-size:1.5rem;font-weight:700;color:#15803d;margin-bottom:.5rem}
    .suc p{color:#374151;margin-bottom:1.25rem;line-height:1.65}
    .steps{text-align:left;background:#fff;border-radius:10px;padding:1.5rem;margin:0 auto 1.5rem;max-width:520px}
    .steps li{padding:.45rem 0;font-size:.9375rem;color:#374151;list-style:none;display:flex;gap:.5rem}
    .steps li::before{content:'→';color:#16a34a;flex-shrink:0}
    code{background:#f0fdf4;border:1px solid #d1fae5;border-radius:4px;padding:.1rem .375rem;font-size:.875rem;color:#15803d}
  </style>
</head>
<body>

<div class="hdr">
  <h1>🚂 Tatkal Agent</h1>
  <p>Configure your IRCTC Tatkal booking — get an encrypted config, run the agent locally</p>
</div>

<div class="banner banner-warn">
  ⚠️ <strong>Disclaimer:</strong> IRCTC's Terms of Service prohibit automated bots. This agent is for personal use with human oversight at the payment step. Use responsibly.
</div>
<div class="banner banner-info">
  🔒 <strong>Privacy:</strong> Data is encrypted in-transit (HTTPS) and never logged on this server. Your config is protected by the passphrase only you know.
</div>

<!-- FORM -->
<div class="wrap" id="main">
  <div class="pills">
    <div class="pill on" id="p1"></div>
    <div class="pill" id="p2"></div>
    <div class="pill" id="p3"></div>
    <div class="pill" id="p4"></div>
  </div>

  <!-- Step 1 — Journey -->
  <div id="s1">
    <div class="card">
      <h2>🔑 IRCTC Login</h2>
      <div class="g2">
        <div class="f"><label>Username</label><input id="username" autocomplete="username" placeholder="IRCTC username"></div>
        <div class="f"><label>Password</label><input id="password" type="password" autocomplete="current-password" placeholder="IRCTC password"></div>
      </div>
    </div>

    <div class="card">
      <h2>🚆 Journey Details</h2>
      <div class="g2">
        <div class="f"><label>Train Number</label><input id="train_number" placeholder="e.g. 12951" maxlength="5"></div>
        <div class="f"><label>Date of Journey</label><input id="journey_date" placeholder="DD-MM-YYYY" maxlength="10"><span class="hint">Example: 27-05-2026</span></div>
        <div class="f"><label>From Station Code</label><input id="from_station" placeholder="e.g. NDLS" maxlength="5" style="text-transform:uppercase"></div>
        <div class="f"><label>To Station Code</label><input id="to_station" placeholder="e.g. MAS" maxlength="5" style="text-transform:uppercase"></div>
        <div class="f">
          <label>Travel Class</label>
          <select id="travel_class">
            <option value="SL">SL — Sleeper Class</option>
            <option value="3A">3A — Third AC</option>
            <option value="2A">2A — Second AC</option>
            <option value="1A">1A — First AC</option>
            <option value="CC">CC — AC Chair Car</option>
            <option value="EC">EC — Executive Chair Car</option>
            <option value="3E">3E — AC Economy</option>
            <option value="2S">2S — Second Sitting</option>
          </select>
        </div>
        <div class="f"><label>Boarding Point <span style="font-weight:400;color:#9ca3af">(optional)</span></label><input id="boarding_point" placeholder="Leave blank = From station" maxlength="5" style="text-transform:uppercase"></div>
      </div>
    </div>

    <div class="nav">
      <button class="btn nxt" onclick="go(2)">Passengers →</button>
    </div>
  </div>

  <!-- Step 2 — Passengers -->
  <div id="s2" style="display:none">
    <div class="card">
      <h2>👥 Passengers</h2>
      <div id="pax-wrap"></div>
      <button class="btn-add" id="add-btn" onclick="addPax()">+ Add Passenger</button>
    </div>
    <div class="card">
      <h2>📱 Contact</h2>
      <div class="f"><label>Mobile Number (for SMS)</label><input id="mobile" type="tel" placeholder="10-digit mobile" maxlength="10"></div>
    </div>
    <div class="nav">
      <button class="btn back" onclick="go(1)">← Back</button>
      <button class="btn nxt" onclick="go(3)">Payment →</button>
    </div>
  </div>

  <!-- Step 3 — Payment -->
  <div id="s3" style="display:none">
    <div class="card">
      <h2>💳 Payment Method</h2>
      <div class="ptabs">
        <div class="ptab on" id="t-UPI" onclick="selPay('UPI')">📲 UPI</div>
        <div class="ptab" id="t-EWALLET" onclick="selPay('EWALLET')">👜 e-Wallet</div>
        <div class="ptab" id="t-CARD" onclick="selPay('CARD')">💳 Card</div>
      </div>

      <div id="pay-UPI">
        <div class="f"><label>UPI ID</label><input id="upi_id" placeholder="yourname@upi"><span class="hint">You approve the collect request on your phone — no browser action needed</span></div>
      </div>
      <div id="pay-EWALLET" style="display:none">
        <div class="f"><label>IRCTC Wallet MPIN</label><input id="wallet_mpin" type="password" placeholder="4–6 digit MPIN"><span class="hint">Fully automated — agent enters MPIN, no user action needed</span></div>
      </div>
      <div id="pay-CARD" style="display:none">
        <div class="g2">
          <div class="f full"><label>Card Number</label><input id="card_number" placeholder="16-digit number" maxlength="19"></div>
          <div class="f"><label>Expiry (MM/YY)</label><input id="card_expiry" placeholder="MM/YY" maxlength="5"></div>
          <div class="f"><label>CVV</label><input id="card_cvv" type="password" placeholder="3–4 digits" maxlength="4"></div>
        </div>
        <span class="hint">Card OTP will be typed into your terminal during the booking run</span>
      </div>
    </div>
    <div class="nav">
      <button class="btn back" onclick="go(2)">← Back</button>
      <button class="btn nxt" onclick="go(4)">Options →</button>
    </div>
  </div>

  <!-- Step 4 — Options & passphrase -->
  <div id="s4" style="display:none">
    <div class="card">
      <h2>⚙️ Options</h2>
      <div class="f">
        <label style="display:flex;align-items:center;gap:.5rem;cursor:pointer;font-size:.9375rem">
          <input type="checkbox" id="confirmed" checked style="width:auto;accent-color:#16a34a">
          Book only if confirmed seats are available
        </label>
        <span class="hint" style="margin-top:.375rem;display:block">Recommended — prevents TQWL waitlisted bookings</span>
      </div>
      <div class="f" style="margin-top:.75rem">
        <label>2captcha API Key <span style="font-weight:400;color:#9ca3af">(optional)</span></label>
        <input id="captcha_key" placeholder="Leave blank to solve CAPTCHA manually in browser">
        <span class="hint">~$0.001/solve at 2captcha.com — auto-fills the IRCTC image CAPTCHA in ~5s</span>
      </div>
    </div>

    <div class="card">
      <h2>🔐 Encryption Passphrase</h2>
      <p style="font-size:.875rem;color:#374151;margin-bottom:1.1rem;line-height:1.6">
        Set a passphrase. You'll type it when running the agent. It is <strong>never stored</strong> — only you know it. If you forget it, run this configurator again.
      </p>
      <div class="g2">
        <div class="f"><label>Passphrase</label><input id="pass" type="password" placeholder="Choose a strong passphrase"></div>
        <div class="f"><label>Confirm Passphrase</label><input id="pass2" type="password" placeholder="Type it again"></div>
      </div>
      <div id="perr" style="color:#ef4444;font-size:.875rem;display:none;margin-top:.25rem">⚠ Passphrases do not match</div>
    </div>

    <div class="nav">
      <button class="btn back" onclick="go(3)">← Back</button>
    </div>
    <button class="btn submit" id="submit-btn" onclick="doSubmit()">
      ⬇️ Generate &amp; Download Encrypted Config
    </button>
  </div>
</div>

<!-- SUCCESS -->
<div class="wrap suc" id="suc">
  <div class="ck">✅</div>
  <h2>Config downloaded!</h2>
  <p>Your encrypted booking config is in <strong>tatkal_config.zip</strong>.</p>
  <ul class="steps">
    <li>Extract <code>booking_config.enc</code> and <code>booking_salt.bin</code> into your <code>tatkal-agent/</code> folder</li>
    <li>Run <code>python main.py check</code> and enter your passphrase</li>
    <li>The morning before your journey, run <code>python main.py run</code></li>
    <li>Keep the terminal open — don't let your laptop sleep</li>
  </ul>
  <p style="font-size:.875rem;color:#6b7280">
    Your passphrase is <strong>not</strong> in the ZIP — keep it safe.<br>
    Source &amp; local agent: <a href="https://github.com/bharani-mandapaka/tatkal" style="color:#16a34a">github.com/bharani-mandapaka/tatkal</a>
  </p>
</div>

<script>
let step = 1, payMode = 'UPI', paxN = 0;
document.addEventListener('DOMContentLoaded', () => addPax());

function go(n) {
  if (n > step && !validate(step)) return;
  document.getElementById('s'+step).style.display = 'none';
  document.getElementById('s'+n).style.display = 'block';
  step = n;
  [1,2,3,4].forEach(i => document.getElementById('p'+i).classList.toggle('on', i <= n));
  window.scrollTo(0, 0);
}

function validate(n) {
  const req = (id) => document.getElementById(id)?.value?.trim();
  if (n === 1) {
    for (const id of ['username','password','train_number','journey_date','from_station','to_station']) {
      if (!req(id)) { alert('Please fill in all required fields.'); document.getElementById(id).focus(); return false; }
    }
    if (!/^\d{2}-\d{2}-\d{4}$/.test(req('journey_date'))) {
      alert('Journey date must be DD-MM-YYYY (e.g. 27-05-2026)');
      document.getElementById('journey_date').focus(); return false;
    }
  }
  if (n === 2) {
    if (paxN === 0) { alert('Add at least one passenger.'); return false; }
    if (!req('mobile')) { alert('Enter a mobile number.'); return false; }
  }
  return true;
}

function addPax() {
  if (paxN >= 4) return;
  paxN++;
  const c = document.getElementById('pax-wrap');
  const d = document.createElement('div');
  d.className = 'pax'; d.id = 'px'+paxN;
  d.innerHTML = `<div class="pax-hdr">
    Passenger ${paxN}
    ${paxN > 1 ? '<button class="rm" onclick="rmPax('+paxN+')">✕</button>' : ''}
  </div>
  <div class="g2">
    <div class="f"><label>Full Name <span style="font-weight:400;color:#9ca3af">(max 15 chars)</span></label><input id="pn${paxN}" placeholder="As on ID proof" maxlength="15"></div>
    <div class="f"><label>Age</label><input id="pa${paxN}" type="number" placeholder="Age" min="1" max="125"></div>
    <div class="f"><label>Gender</label><select id="pg${paxN}"><option value="M">Male</option><option value="F">Female</option><option value="T">Transgender</option></select></div>
    <div class="f"><label>Berth Preference</label><select id="pb${paxN}"><option value="LB">Lower Berth</option><option value="MB">Middle Berth</option><option value="UB">Upper Berth</option><option value="SL">Side Lower</option><option value="SU">Side Upper</option><option value="NO PREFERENCE">No Preference</option></select></div>
    <div class="f"><label>ID Type <span style="color:#ef4444">*</span></label><select id="pt${paxN}"><option value="AADHAAR CARD">Aadhaar Card</option><option value="PAN CARD">PAN Card</option><option value="VOTER ID CARD">Voter ID</option><option value="PASSPORT">Passport</option><option value="DRIVING LICENCE">Driving Licence</option></select></div>
    <div class="f"><label>ID Number <span style="color:#ef4444">*</span></label><input id="pi${paxN}" placeholder="Mandatory for Tatkal"></div>
  </div>`;
  c.appendChild(d);
  if (paxN >= 4) document.getElementById('add-btn').style.display = 'none';
}

function rmPax(n) {
  document.getElementById('px'+n).remove();
  paxN--;
  document.getElementById('add-btn').style.display = '';
}

function selPay(m) {
  payMode = m;
  ['UPI','EWALLET','CARD'].forEach(x => {
    document.getElementById('t-'+x).classList.toggle('on', x === m);
    document.getElementById('pay-'+x).style.display = x === m ? 'block' : 'none';
  });
}

async function doSubmit() {
  const v = id => document.getElementById(id)?.value?.trim() || '';
  const pass = v('pass');
  if (!pass) { alert('Set a passphrase.'); document.getElementById('pass').focus(); return; }
  if (pass !== v('pass2')) { document.getElementById('perr').style.display = 'block'; return; }
  document.getElementById('perr').style.display = 'none';

  // Collect passengers
  const passengers = [];
  for (let i = 1; i <= 4; i++) {
    const el = document.getElementById('pn'+i);
    if (!el) continue;
    const name = el.value.trim();
    if (!name) continue;
    const idNum = document.getElementById('pi'+i).value.trim();
    if (!idNum) { alert('Passenger '+i+': ID number is required for Tatkal.'); return; }
    passengers.push({
      name, age: parseInt(document.getElementById('pa'+i).value)||0,
      gender: document.getElementById('pg'+i).value,
      berth_preference: document.getElementById('pb'+i).value,
      id_type: document.getElementById('pt'+i).value,
      id_number: idNum,
    });
  }
  if (!passengers.length) { alert('Add at least one passenger.'); return; }

  // Payment
  let payment = { method: payMode };
  if (payMode === 'UPI') {
    payment.upi_id = v('upi_id');
    if (!payment.upi_id) { alert('Enter your UPI ID.'); return; }
  } else if (payMode === 'EWALLET') {
    payment.wallet_mpin = document.getElementById('wallet_mpin').value;
    if (!payment.wallet_mpin) { alert('Enter your wallet MPIN.'); return; }
  } else {
    payment.card_number = v('card_number').replace(/\\s/g,'');
    payment.card_expiry = v('card_expiry');
    payment.card_cvv    = document.getElementById('card_cvv').value;
    if (!payment.card_number||!payment.card_expiry||!payment.card_cvv) { alert('Fill in all card details.'); return; }
  }

  const payload = {
    username: v('username'), password: document.getElementById('password').value,
    train_number: v('train_number'), from_station: v('from_station').toUpperCase(),
    to_station: v('to_station').toUpperCase(), journey_date: v('journey_date'),
    travel_class: document.getElementById('travel_class').value,
    boarding_point: v('boarding_point').toUpperCase(),
    passengers, mobile: v('mobile'), payment,
    book_only_if_confirmed: document.getElementById('confirmed').checked,
    captcha_api_key: v('captcha_key') || null,
    passphrase: pass,
  };

  const btn = document.getElementById('submit-btn');
  btn.disabled = true;
  btn.innerHTML = '<span class="spin"></span>Encrypting config…';

  try {
    const r = await fetch('/api/configure', {
      method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(payload)
    });
    if (!r.ok) { const e = await r.json().catch(()=>({error:'Server error'})); throw new Error(e.error); }
    const blob = await r.blob();
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob); a.download = 'tatkal_config.zip'; a.click();
    document.getElementById('main').style.display = 'none';
    document.getElementById('suc').style.display   = 'block';
    window.scrollTo(0,0);
  } catch(e) {
    alert('Error: '+e.message);
    btn.disabled = false;
    btn.innerHTML = '⬇️ Generate &amp; Download Encrypted Config';
  }
}
</script>
</body>
</html>"""
