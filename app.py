import os, json, random, string
from pathlib import Path
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, session, jsonify
from square.client import Client  # NEW

# --- Square creds (env vars already set in Render) ---
SQUARE_APP_ID = os.getenv("SQUARE_APP_ID")
SQUARE_LOCATION_ID = os.getenv("SQUARE_LOCATION_ID")
SQUARE_ACCESS_TOKEN = os.getenv("SQUARE_ACCESS_TOKEN")

# Reuse one Square client
square_client = Client(
    access_token=SQUARE_ACCESS_TOKEN,
    environment="production"
)

# ---------- App setup ----------
app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-change-me")

BASE_DIR = Path(__file__).resolve().parent
UPLOADS = BASE_DIR / "uploads"
DATA_DIR = BASE_DIR / "data"
DB_FILE = DATA_DIR / "records.json"
UPLOADS.mkdir(exist_ok=True)
DATA_DIR.mkdir(exist_ok=True)

ALLOWED_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp"}

# ---------- Helpers ----------
def rand_digits(n=4):
    return ''.join(random.choices(string.digits, k=n))

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

# price map (cents)
PACKAGE_PRICES = {
    "platinum": 200000,
    "premium": 150000,
    "gold":    120000,
    "silver":  100000,
    "bronze":   70000,
    "regular":  50000,
}

# Serve uploads
@app.route("/uploads/<path:fname>")
def serve_upload(fname):
    from flask import send_from_directory
    return send_from_directory(UPLOADS, fname)

# ---------- Routes ----------
@app.route("/")
def index():
    return render_template("index.html")

@app.route("/celebrity", methods=["GET", "POST"])
def celebrity():
    if request.method == "POST":
        celeb_name = request.form.get("celeb_name", "").strip()
        celeb_img = request.files.get("celeb_image")

        # optional: save the uploaded image
        img_path = None
        if celeb_img and celeb_img.filename:
            upload_path = UPLOADS / celeb_img.filename
            celeb_img.save(upload_path)
            img_path = str(upload_path.name)

        # generate 4-digit code
        code4 = str(random.randint(1000, 9999))

        # store in session
        session["celebrity"] = {
            "name": celeb_name,
            "image_url": img_path,
            "gen_code": code4,
        }

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
            # collect client fields
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

            # build pending order in session
            order = {
                "ticket_id": rand_ticket(9),
                "celebrity": session.get("celebrity", {}),
                "client": client_data,
                "paid": False
            }
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
    price_cents = PACKAGE_PRICES.get(order["client"]["package"], 50000)
    return render_template("checkout.html", order=order, price_usd=price_cents//100)

@app.route("/payment/options")
def payment_options():
    order = session.get("pending_order")
    if not order:
        return redirect(url_for("client"))
    return render_template("payment_options.html", order=order)

# ----- Stripe (Checkout) -----
import stripe
stripe.api_key = os.environ.get("STRIPE_SECRET_KEY")  # set in your shell
STRIPE_PUBLISHABLE_KEY = os.environ.get("STRIPE_PUBLISHABLE_KEY","")

# REPLACE the whole /payment/card route with this Square version
@app.route("/payment/card", methods=["GET"])
def payment_card():
    order = session.get("pending_order")
    if not order:
        return redirect(url_for("client"))
    price_cents = PACKAGE_PRICES.get(order["client"]["package"], 50000)

    return render_template(
        "payment_card.html",
        order=order,
        amount_usd=price_cents // 100,
        square_app_id=SQUARE_APP_ID,            # <-- from your env
        square_location_id=SQUARE_LOCATION_ID   # <-- from your env
    )
    
    # NEW: Square card charge endpoint (same client you used for ACH)
@app.route("/api/square/pay/card", methods=["POST"])
def square_pay_card():
    order = session.get("pending_order")
    if not order:
        return jsonify({"error": "No active order"}), 400

    data = request.get_json() or {}
    token = data.get("token")  # tokenized by Square Web Payments SDK
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
        "autocomplete": True,  # capture immediately
    }

    result = square_client.payments.create_payment(body)
    if result.is_success():
        payment_id = result.body["payment"]["id"]

        # finalize order like your Stripe success did
        order["paid"] = True
        order["status"] = "verified"
        order["payment_info"] = {"method": "Square Card", "payment_id": payment_id}
        order["created_at"] = datetime.utcnow().isoformat()
        append_record(order)
        session.pop("pending_order", None)

        view_url = url_for("view_card", ticket_id=order["ticket_id"])
        return jsonify({"ok": True, "view_url": view_url})
    else:
        msg = (getattr(result, "errors", [{}])[0].get("detail")
               if getattr(result, "errors", None) else "Payment error")
        return jsonify({"error": msg}), 400

@app.route("/payment/bank", methods=["GET","POST"])
def payment_bank():
    order = session.get("pending_order")
    if not order:
        return redirect(url_for("client"))
    if request.method == "POST":
        proof = request.files.get("bank_proof")
        proof_url = save_upload(proof)
        order["paid"] = True
        order["payment_info"] = {"method":"Bank Transfer","proof_url": proof_url}
        order["created_at"] = datetime.utcnow().isoformat()
        append_record(order)
        session.pop("pending_order", None)
        return render_template("card.html", order=order)
    return render_template(
    "payment_bank.html",
    order=order,
    square_app_id=SQUARE_APP_ID,
    square_location_id=SQUARE_LOCATION_ID
)

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
        from datetime import datetime
        order["created_at"] = datetime.utcnow().isoformat()
        append_record(order)
        session.pop("pending_order", None)
        return render_template("pending_review.html", order=order)

    # GET -> show the upload form
    return render_template("payment_giftcard.html", order=order)

@app.route("/payment/success")
def payment_success():
    session_id = request.args.get("session_id")
    if not session_id:
        return "Missing session_id", 400
    # verify with Stripe (optional strictness)
    stripe.checkout.Session.retrieve(session_id)

    order = session.get("pending_order")
    if not order:
        return "Order not found. Start again.", 404

    order["paid"] = True
    order["payment_info"] = {"method":"Stripe Card","session_id": session_id}
    order["created_at"] = datetime.utcnow().isoformat()
    append_record(order)
    session.pop("pending_order", None)
    
    order["status"] = "verified"   # so the badge shows for Stripe card payments
    return redirect(url_for('view_card', ticket_id=order["ticket_id"]))

# tiny health check (handy)
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

@app.route("/card/<ticket_id>")
def view_card(ticket_id):
    records = load_records()
    for r in records:
        if r.get("ticket_id") == ticket_id:
            return render_template("card.html", order=r)
    return "Card not found", 404

    @app.route("/api/square/pay/bank", methods=["POST"])
def square_pay_bank():
    order = session.get("pending_order")
    if not order:
        return jsonify({"error": "No active order"}), 400

    data = request.get_json() or {}
    token = data.get("token")
    if not token:
        return jsonify({"error": "Missing bank token"}), 400

    # amount from selected package
    amount_cents = PACKAGE_PRICES.get(order["client"]["package"], 50000)

    # unique idempotency key per attempt
    idem = f"ach-{order['ticket_id']}-{int(datetime.utcnow().timestamp())}"

    body = {
        "source_id": token,  # ACH bank account token from Web Payments SDK
        "idempotency_key": idem,
        "amount_money": {"amount": amount_cents, "currency": "USD"},
        "location_id": SQUARE_LOCATION_ID,
        "note": f"FanMeetZone ACH {order['ticket_id']}",
    }

    result = square_client.payments.create_payment(body)

    if result.is_success():
        payment_id = result.body["payment"]["id"]
        # Save & close the order (pending settlement)
        order["paid"] = False
        order["status"] = "pending_settlement"
        order["payment_info"] = {"method": "Square ACH", "payment_id": payment_id}
        order["created_at"] = datetime.utcnow().isoformat()
        append_record(order)
        session.pop("pending_order", None)
        return jsonify({"ok": True, "status": "pending_settlement"})
    else:
        msg = (getattr(result, "errors", [{}])[0].get("detail")
               if getattr(result, "errors", None) else "Payment error")
        return jsonify({"error": msg}), 400

if __name__ == "__main__":
    app.run(debug=True)