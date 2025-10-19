import os, json, random, string
from pathlib import Path
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, session, jsonify

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
    return "celebrity route OK"
        celeb_name = request.form.get("celeb_name","").strip()
        celeb_img  = save_upload(request.files.get("celeb_image"))
        # 4-digit passcode we’ll ask user to confirm (not 6)
        code4 = rand_digits(4)
        session["celebrity"] = {
            "name": celeb_name,
            "image_url": celeb_img,
            "gen_code": code4
        }
        return redirect(url_for("passcode"))
    return render_template("celebrity_form.html")

# NEW: never index session directly; pass a safe default
    celeb = session.get("celebrity", {})
    return render_template("celebrity_form.html", celeb=celeb)
# Always pass a safe default to the template (avoid KeyError)
    celeb = session.get("celebrity", {})
    return render_template("celebrity_form.html", celeb=celeb)

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

@app.route("/payment/card", methods=["GET","POST"])
def payment_card():
    order = session.get("pending_order")
    if not order:
        return redirect(url_for("client"))
    price_cents = PACKAGE_PRICES.get(order["client"]["package"], 50000)

    if request.method == "POST":
        try:
            success_url = url_for('payment_success', _external=True) + '?session_id={CHECKOUT_SESSION_ID}'
            cancel_url  = url_for('payment_options', _external=True)

            checkout_session = stripe.checkout.Session.create(
                mode='payment',
                payment_method_types=['card'],
                line_items=[{
                    'price_data': {
                        'currency': 'usd',
                        'product_data': {'name': f"{order['client']['package'].capitalize()} VIP Membership"},
                        'unit_amount': price_cents,
                    },
                    'quantity': 1
                }],
                success_url=success_url,
                cancel_url=cancel_url,
                metadata={
                    "ticket_id": order["ticket_id"]
                }
            )
            return jsonify({'id': checkout_session.id})
        except Exception as e:
            return jsonify({'error': str(e)}), 400

    return render_template(
        "payment_card.html",
        order=order,
        STRIPE_PUBLISHABLE_KEY=STRIPE_PUBLISHABLE_KEY,
        PRICE_USD=price_cents//100
    )

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
    return render_template("payment_bank.html", order=order)

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

if __name__ == "__main__":
    app.run(debug=True)