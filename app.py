import os, json, random, string
from pathlib import Path
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, session, jsonify
import requests

# ===== Square config (use PRODUCTION by default) =====
SQUARE_APP_ID = os.environ.get("SQUARE_APP_ID")
SQUARE_ACCESS_TOKEN = os.environ.get("SQUARE_ACCESS_TOKEN")
SQUARE_LOCATION_ID = os.environ.get("SQUARE_LOCATION_ID")

# If you switch to sandbox keys (prefix "sandbox-"), change BASE_URL accordingly:
# BASE_URL = "https://connect.squareupsandbox.com"   # sandbox
BASE_URL = "https://connect.squareup.com"            # production

def square_create_payment(body: dict):
    """Call Square /v2/payments via REST. Returns (ok, data_or_error)."""
    url = f"{BASE_URL}/v2/payments"
    headers = {
        "Authorization": f"Bearer {SQUARE_ACCESS_TOKEN}",
        "Content-Type": "application/json",
        "Square-Version": "2024-08-21",  # recent Square API version
    }
    r = requests.post(url, headers=headers, json=body, timeout=30)
    if r.status_code in (200, 201):
        return True, r.json()
    try:
        return False, r.json()
    except Exception:
        return False, {"errors": [{"detail": r.text}]}

# ===== Flask app =====
app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-change-me")

BASE_DIR = Path(__file__).resolve().parent
UPLOADS = BASE_DIR / "uploads"
DATA_DIR = BASE_DIR / "data"
DB_FILE = DATA_DIR / "records.json"
UPLOADS.mkdir(exist_ok=True)
DATA_DIR.mkdir(exist_ok=True)

ALLOWED_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp"}

# ===== Helpers =====
def rand_ticket(n=10):
    alphabet = string.ascii_uppercase + string.digits
    return ''.join(random.choices(alphabet, k=n))

def save_upload(file_storage):
    if not file_storage or file_storage.filename == "":
        return None
    ext = Path(file_storage.filename).suffix.lower() or ".png"
    name = f"{datetime.utcnow().strftime('%Y%m%d%H%M%S')}_{rand_ticket(6)}{ext}"
    dest = UPLOADS / name
    file_storage.save(dest)
    return f"/uploads/{name}"

def load_records():
    if DB_FILE.exists():
        try:
            return json.loads(DB_FILE.read_text(encoding="utf-8"))
        except Exception:
            return []
    return []

def save_records(rows):
    DB_FILE.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")

def append_record(record):
    rows = load_records()
    rows.append(record)
    DB_FILE.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")

# ===== Price map (in cents) =====
PACKAGE_PRICES = {
    "platinum": 200000,
    "premium": 150000,
    "gold":    120000,
    "silver":  100000,
    "bronze":   70000,
    "regular":  50000,
}
PACKAGE_PERKS = {
    "platinum": {
        "title": "💎 Platinum — Elite Access",
        "bullets": [
            "✨ Priority replies",
            "🎥 Video-call slots (limited)",
            "🤝 Meet & greet access",
            "🕒 Early RSVP",
            "🛍️ 15% merch codes*",
            "🎬 Backstage moments",
            "🧱 Name on the wall",
            "🎁 Surprise drops",
            "🔁 Loyalty “reroll”",
        ],
    },
    "premium": {
        "title": "🏆 Premium — Inner Circle",
        "bullets": [
            "⚡️ Priority sorting",
            "🎥 Limited video calls",
            "🤝 Meet & greet lottery",
            "🕒 RSVP window",
            "🛍️ 10% merch codes*",
            "🎧 Monthly “uncut” clip",
            "🗝️ Secret newsletter clues",
        ],
    },
    "gold": {
        "title": "🥇 Gold — VIP Member",
        "bullets": [
            "📈 Fast-track points",
            "🛎️ Early merch pings",
            "🎥 Limited video calls",
            "🤝 Meet & greet windows",
            "🔦 Fan spotlight",
            "🎂 Birthday shout-out",
            "📲 Wallpapers & ringtones",
            "🗳️ Early polls",
        ],
    },
    "silver": {
        "title": "🥈 Silver — Active Supporter",
        "bullets": [
            "🫥 Hidden posts",
            "🎁 Giveaways",
            "🎥 Video-call queue",
            "🤝 Meet & greet window",
            "📲 Wallpaper pack",
            "🗳️ Polls",
            "💠 Sticker pack",
        ],
    },
    "bronze": {
        "title": "🥉 Bronze — Loyal Fan",
        "bullets": [
            "⏱️ Early previews",
            "🎁 Giveaways",
            "🎥 Group video calls",
            "🎟️ Meet & greet lottery",
            "🎲 Mystery reward",
            "❓ Bronze Q&A thread",
        ],
    },
    "regular": {
        "title": "🎟 Regular — Basic Access",
        "bullets": [
            "📣 Community updates",
            "🎁 Occasional giveaways",
            "🎥 Group-call raffles",
            "⏳ Meet & greet waitlist",
        ],
    },
}

# ===== Static uploads =====
@app.route("/uploads/<path:fname>")
def serve_upload(fname):
    from flask import send_from_directory
    return send_from_directory(UPLOADS, fname)

# ===== Routes =====
@app.route("/")
def index():
    return render_template("index.html")

@app.route("/celebrity", methods=["GET", "POST"])
def celebrity():
    if request.method == "POST":
        celeb_name = request.form.get("celeb_name", "").strip()
        celeb_img = request.files.get("celeb_image")

        img_path = None
        if celeb_img and celeb_img.filename:
            upload_path = UPLOADS / celeb_img.filename
            celeb_img.save(upload_path)
            img_path = str(upload_path.name)

        code4 = str(random.randint(1000, 9999))
        session["celebrity"] = {"name": celeb_name, "image_url": img_path, "gen_code": code4}
        return redirect(url_for("passcode"))

    return render_template("celebrity_form.html")

@app.route("/passcode", methods=["GET","POST"])
def passcode():
    celeb = session.get("celebrity")
    if not celeb:
        return redirect(url_for("celebrity"))
    if request.method == "POST":
        entered = request.form.get("code","").strip()
        if entered == celeb["gen_code"]:
            session["celeb_locked"] = True
            return redirect(url_for("client"))
        return render_template("passcode.html", celeb_name=celeb["name"], code=celeb["gen_code"], error="Wrong passcode")
    return render_template("passcode.html", celeb_name=celeb["name"], code=celeb["gen_code"], error=None)

@app.route("/client", methods=["GET","POST"])
def client():
    if not session.get("celeb_locked"):
        return redirect(url_for("celebrity"))
    if request.method == "POST":
        try:
            client_image_url = save_upload(request.files.get("client_image"))
            client_data = {
                "image_url": client_image_url,
                "full_name": request.form.get("full_name","").strip(),
                "email":     request.form.get("email","").strip(),
                "address":   request.form.get("address","").strip(),
                "city":      request.form.get("city","").strip(),
                "state":     request.form.get("state","").strip(),
                "zip":       request.form.get("zip","").strip(),
                "country":   request.form.get("country","").strip(),
                "dob":       request.form.get("dob","").strip(),
                "package":   request.form.get("package","regular"),
            }
            order = {"ticket_id": rand_ticket(9), "celebrity": session.get("celebrity", {}), "client": client_data, "paid": False}
            session["pending_order"] = order
            return redirect(url_for("checkout"))
        except Exception as e:
            print(">>> /client POST error:", e)
            return "There was a problem with your submission. Please go back and try again.", 400
    return render_template("client_form.html")

@app.route("/checkout")
def checkout():
    order = session.get("pending_order")
    if not order:
        return redirect(url_for("client"))
    pkg = (order["client"].get("package") or "regular").lower()
    price_cents = PACKAGE_PRICES.get(pkg, 50000)
    perks = PACKAGE_PERKS.get(pkg)
    return render_template(
        "checkout.html",
        order=order,
        price_usd=price_cents // 100,
        perks=perks,           # <-- add this
    )

@app.route("/payment/options")
def payment_options():
    order = session.get("pending_order")
    if not order:
        return redirect(url_for("client"))
    price_cents = PACKAGE_PRICES.get(order["client"]["package"], 50000)
    return render_template(
        "payment_options.html",
        order=order,
        amount_usd=price_cents // 100   # <— give the template a clean integer amount
    )

# ===== Card (Web Payments SDK + REST charge) =====
@app.route("/payment/card", methods=["GET"])
def payment_card():
    order = session.get("pending_order")
    if not order:
        return redirect(url_for("client"))
    price_cents = PACKAGE_PRICES.get(order["client"]["package"], 50000)

    # Fail fast if env vars are missing
    assert SQUARE_APP_ID, "SQUARE_APP_ID is empty"
    assert SQUARE_LOCATION_ID, "SQUARE_LOCATION_ID is empty"

    return render_template(
        "payment_card.html",
        order=order,
        amount_usd=price_cents // 100,
        square_app_id=SQUARE_APP_ID,
        square_location_id=SQUARE_LOCATION_ID
    )

@app.route("/api/square/pay/card", methods=["POST"])
def square_pay_card():
    order = session.get("pending_order")
    if not order:
        return jsonify({"error": "No active order"}), 400

    data = request.get_json() or {}
    token = data.get("token")
    if not token:
        return jsonify({"error": "Missing card token"}), 400

    amount_cents = PACKAGE_PRICES.get(order["client"]["package"], 50000)
    idem = f"card-{order['ticket_id']}-{int(datetime.utcnow().timestamp())}"

    body = {
        "source_id": token,
        "idempotency_key": idem,
        "amount_money": {"amount": amount_cents, "currency": "USD"},
        "location_id": SQUARE_LOCATION_ID,
        "note": f"FanMeetZone card {order['ticket_id']}",
        "autocomplete": True,
    }

    ok, resp = square_create_payment(body)
    if ok:
        payment_id = resp["payment"]["id"]
        order["paid"] = True
        order["status"] = "verified"
        order["payment_info"] = {"method": "Square Card", "payment_id": payment_id}
        order["created_at"] = datetime.utcnow().isoformat()
        append_record(order)
        session.pop("pending_order", None)
        view_url = url_for("view_card", ticket_id=order["ticket_id"])
        return jsonify({"ok": True, "view_url": view_url})
    else:
        msg = (resp.get("errors") or [{}])[0].get("detail", "Payment error")
        return jsonify({"error": msg}), 400

# ===== Bank (ACH via Web Payments SDK token) + manual upload fallback =====
@app.route("/payment/bank", methods=["GET","POST"])
def payment_bank():
    order = session.get("pending_order")
    if not order:
        return redirect(url_for("client"))

    # POST = manual upload fallback
    if request.method == "POST":
        proof = request.files.get("bank_proof")
        proof_url = save_upload(proof)
        order["paid"] = True
        order["payment_info"] = {"method":"Bank Transfer","proof_url": proof_url}
        order["created_at"] = datetime.utcnow().isoformat()
        append_record(order)
        session.pop("pending_order", None)
        return render_template("card.html", order=order)

    # GET = render ACH page
    assert SQUARE_APP_ID, "SQUARE_APP_ID is empty"
    assert SQUARE_LOCATION_ID, "SQUARE_LOCATION_ID is empty"
    try:
        return render_template(
            "payment_bank.html",
            order=order,
            square_app_id=SQUARE_APP_ID,
            square_location_id=SQUARE_LOCATION_ID
        )
    except Exception as e:
        app.logger.exception("payment_bank GET failed")
        return f"Template error: {e}", 500

@app.route("/api/square/pay/bank", methods=["POST"])
def square_pay_bank():
    order = session.get("pending_order")
    if not order:
        return jsonify({"error": "No active order"}), 400

    data = request.get_json() or {}
    token = data.get("token")
    if not token:
        return jsonify({"error": "Missing bank token"}), 400

    amount_cents = PACKAGE_PRICES.get(order["client"]["package"], 50000)
    idem = f"ach-{order['ticket_id']}-{int(datetime.utcnow().timestamp())}"

    body = {
        "source_id": token,  # bank account token from Web Payments SDK
        "idempotency_key": idem,
        "amount_money": {"amount": amount_cents, "currency": "USD"},
        "location_id": SQUARE_LOCATION_ID,
        "note": f"FanMeetZone ACH {order['ticket_id']}",
    }

    ok, resp = square_create_payment(body)
    if ok:
        payment_id = resp["payment"]["id"]
        order["paid"] = False
        order["status"] = "pending_settlement"
        order["payment_info"] = {"method": "Square ACH", "payment_id": payment_id}
        order["created_at"] = datetime.utcnow().isoformat()
        append_record(order)
        session.pop("pending_order", None)
        return jsonify({"ok": True, "status": "pending_settlement"})
    else:
        msg = (resp.get("errors") or [{}])[0].get("detail", "Payment error")
        return jsonify({"error": msg}), 400

@app.route("/payment/gift", methods=["GET","POST"])
def payment_gift():
    order = session.get("pending_order")
    if not order:
        return redirect(url_for("client"))
    if request.method == "POST":
        proof = request.files.get("gift_proof")
        proof_url = save_upload(proof)
        order["payment_info"] = {"method": "Gift Card", "proof_url": proof_url}
        order["status"] = "pending_verification"
        order["created_at"] = datetime.utcnow().isoformat()
        append_record(order)
        session.pop("pending_order", None)
        return render_template("pending_review.html", order=order)
    return render_template("payment_giftcard.html", order=order)

@app.route("/_ping")
def ping():
    return "ok"

@app.route('/admin/records')
def admin_records():
    records = load_records()
    records = sorted(records, key=lambda r: r.get('created_at',''), reverse=True)
    return render_template('admin_records.html', records=records)

@app.route('/admin/verify/<ticket>/<action>', methods=['POST'])
def admin_verify(ticket, action):
    records = load_records()
    for r in records:
        if r.get('ticket_id') == ticket:
            if action == 'approve':
                r['status'] = 'verified'
                r['paid'] = True
            elif action == 'reject':
                r['status'] = 'rejected'
                r['paid'] = False
            break
    save_records(records)
    return redirect(url_for('admin_records'))

@app.route('/admin/delete/<ticket>', methods=['POST'])
def admin_delete(ticket):
    records = load_records()
    new_records = [r for r in records if r.get('ticket_id') != ticket]
    save_records(new_records)
    return redirect(url_for('admin_records'))

@app.route("/card/<ticket_id>")
def view_card(ticket_id):
    records = load_records()
    for r in records:
        if r.get("ticket_id") == ticket_id:
            return render_template("card.html", order=r)
    return "Card not found", 404

# --- Apple Pay domain verification (serves the file in static/.well-known) ---
@app.route('/.well-known/apple-developer-merchantid-domain-association')
def apple_pay_verification():
    # Use Flask's static file server; path is relative to the /static folder
    return app.send_static_file('.well-known/apple-developer-merchantid-domain-association')

@app.route("/terms")
def terms():
    return render_template("terms.html")

if __name__ == "__main__":
    app.run(debug=True)