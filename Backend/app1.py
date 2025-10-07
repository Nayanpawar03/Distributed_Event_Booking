# backend/app1.py
from flask import Flask, render_template, request, redirect, url_for, session, jsonify, send_from_directory
from flask_cors import CORS
from shared_data import seats, locks, holders
import json, os, time, threading
from db_config import get_db_connection
from werkzeug.security import generate_password_hash, check_password_hash


# config
HOLD_SECONDS = 30
SYNC_TIMEOUT = 15
USERS_FILE = "users.json"

app = Flask(__name__,
            template_folder="../frontend/templates",
            static_folder="../frontend/static",
            static_url_path="/static")
CORS(app)
app.secret_key = "supersecretkey"

# ---------------- In-memory global state ----------------
active_users = {}          # {username: last_seen_epoch}
announced_times = {}       # {username: client_time_epoch}
last_sync_time = 0
sync_in_progress = False
sync_completed = False     # ✅ new flag
sync_lock = threading.Lock()

# ---------------- Helpers ----------------
# def load_users():
#     if not os.path.exists(USERS_FILE):
#         return {}
#     try:
#         with open(USERS_FILE, "r") as f:
#             content = f.read().strip()
#             if not content:
#                 return {}
#             return json.loads(content)
#     except json.JSONDecodeError:
#         return {}

# def save_users(users):
#     with open(USERS_FILE, "w") as f:
#         json.dump(users, f, indent=4)

def prune_active_users(timeout=60):
    """Remove inactive users."""
    now = time.time()
    to_remove = []
    for u, last in list(active_users.items()):
        if now - last > timeout:
            to_remove.append(u)
    for u in to_remove:
        active_users.pop(u, None)
        announced_times.pop(u, None)

def ensure_sync():
    """Prevent booking before sync."""
    if not sync_completed:
        return jsonify({"status": "error", "message": "Clock synchronization pending"}), 403
    return None


# ---------------- Routes (auth + pages) ----------------
@app.route('/')
def home():
    return render_template("index.html")

@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        username = request.form['username']
        email = request.form['email']
        password = request.form['password']

        # hash the password before storing
        hashed_password = generate_password_hash(password, method='pbkdf2:sha256')

        conn = get_db_connection()
        cur = conn.cursor()

        # check if username or email already exist
        cur.execute("SELECT * FROM users WHERE username = %s OR email = %s", (username, email))
        existing_user = cur.fetchone()

        if existing_user:
            cur.close()
            conn.close()
            return render_template("signup.html", message="Username or email already exists!")

        cur.execute(
            "INSERT INTO users (username, email, password) VALUES (%s, %s, %s)",
            (username, email, hashed_password)
        )
        conn.commit()
        cur.close()
        conn.close()

        return redirect(url_for('login'))

    return render_template("signup.html")



@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        user_input = request.form['username']  # can be username or email
        password = request.form['password']

        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT * FROM users WHERE username = %s OR email = %s", (user_input, user_input))
        user = cur.fetchone()
        cur.close()
        conn.close()

        if user and check_password_hash(user[3], password):  # verify hashed password
            session['username'] = user[1]  # index 1 = username
            return redirect(url_for('dashboard'))
        else:
            return render_template("login.html", message="Invalid credentials")

    return render_template("login.html")



@app.route('/logout')
def logout():
    session.pop('username', None)
    return redirect(url_for('home'))

@app.route('/dashboard')
def dashboard():
    if 'username' not in session:
        return redirect(url_for('login'))
    active_users[session['username']] = time.time()
    return render_template("dashboard.html", username=session['username'])

@app.route('/booking')
def booking_page():
    if 'username' not in session:
        return redirect(url_for('login'))
    active_users[session['username']] = time.time()
    return render_template("booking.html")


# ---------------- Berkeley Time Synchronization ----------------
@app.route('/api/sync_time', methods=['POST'])
def sync_time():
    """
    Improved Berkeley synchronization.
    - Works even when users join later.
    - Prints who triggered sync, and shows all users’ times clearly.
    """
    if 'username' not in session:
        return jsonify({"status": "error", "message": "Login required"}), 401

    global last_sync_time, sync_completed
    username = session['username']
    data = request.get_json(force=True)
    client_time = data.get("client_time")

    if client_time is None:
        return jsonify({"status": "error", "message": "client_time missing"}), 400

    prune_active_users()
    with sync_lock:
        # update this user's announced time
        active_users[username] = time.time()
        announced_times[username] = float(client_time)

        server_time = time.time()
        all_users = list(announced_times.keys())

        print("\n[SYNC] ====================================================")
        print(f"[SYNC] Sync triggered by: {username}")
        print(f"[SYNC] Active announced users: {all_users}")
        print(f"[SYNC] Server time now: {time.strftime('%H:%M:%S', time.localtime(server_time))}")

        # If only one user, align directly with server time
        if len(all_users) == 1:
            sync_completed = True
            print(f"[SYNC] Only one user '{username}' active -> aligning with server.")
            print(f"[SYNC] User '{username}' entered local time: {time.strftime('%H:%M:%S', time.localtime(client_time))}")
            print(f"[SYNC] Final synchronized time: {time.strftime('%H:%M:%S', time.localtime(server_time))}")
            print("[SYNC] ====================================================\n")
            return jsonify({
                "status": "synced",
                "message": "Only one user - time aligned with server.",
                "server_time": server_time,
                "avg_offset": 0.0,
                "your_adjust": 0.0
            })

        # Compute offsets relative to server
        offsets = {}
        total_offset = 0.0
        for u, ct in announced_times.items():
            offset = ct - server_time
            offsets[u] = offset
            total_offset += offset

        avg_offset = total_offset / (len(offsets) + 1)  # include server in average
        adjustments = {u: avg_offset - offsets[u] for u in offsets}

        # Print in readable detail
        print(f"[SYNC] Average offset across all: {avg_offset:+.6f} sec")
        print("[SYNC] ---- User-wise details ----")
        # Calculate the common synchronized base time
        common_synced_time = server_time + avg_offset

        print(f"[SYNC] Target synchronized time for all: {time.strftime('%H:%M:%S', time.localtime(common_synced_time))}")
        print("[SYNC] ---- User-wise details ----")
        for u, adj in adjustments.items():
            ct = announced_times[u]
            print(f"[SYNC] {u}: entered={time.strftime('%H:%M:%S', time.localtime(ct))} "
                f"| offset={offsets[u]:+.3f}s "
                f"| adjust={adj:+.3f}s "
                f"| final_sync_time={time.strftime('%H:%M:%S', time.localtime(common_synced_time))}")


        sync_completed = True
        last_sync_time = time.time()

        user_adjust = adjustments.get(username, 0.0)

        # Do NOT clear announced_times — keep for future users
        return jsonify({
            "status": "synced",
            "message": f"Synchronized {len(offsets)} users successfully.",
            "server_time": server_time,
            "avg_offset": avg_offset,
            "your_adjust": user_adjust
        })


    """Keeps the current user marked active and prevents 404 spam."""
    if 'username' in session:
        active_users[session['username']] = time.time()
        return jsonify({"status": "ok"})
    return jsonify({"status": "error", "message": "not logged in"}), 401

# ---------------- Booking / Seats ----------------
def cleanup_expired_holds():
    """Release expired holds."""
    now = time.time()
    expired = []
    for s, info in list(holders.items()):
        if info and now >= info.get("expiry", 0):
            expired.append(s)
    for s in expired:
        holders.pop(s, None)
        if seats.get(s) == "held":
            seats[s] = "available"

@app.route('/api/seats', methods=['GET'])
def api_get_seats():
    not_ready = ensure_sync()
    if not_ready: return not_ready
    cleanup_expired_holds()
    payload = {}
    now = time.time()
    for s, status in seats.items():
        entry = {"status": status}
        if status == "held":
            h = holders.get(s)
            if h:
                remaining = max(0, int(h["expiry"] - now))
                entry["held_by"] = h["user"]
                entry["hold_expires_in"] = remaining
        payload[s] = entry
    return jsonify(payload)

@app.route('/api/hold/<seat_id>', methods=['POST'])
def api_hold(seat_id):
    not_ready = ensure_sync()
    if not_ready: return not_ready

    if 'username' not in session:
        return jsonify({"status": "error", "message": "Login required"}), 401
    username = session['username']
    if seat_id not in seats:
        return jsonify({"status": "error", "message": "Invalid seat"}), 400

    lock = locks[seat_id]
    acquired = lock.acquire(blocking=False)
    if not acquired:
        return jsonify({"status": "error", "message": "Seat busy"}), 409

    try:
        cleanup_expired_holds()
        status = seats.get(seat_id)
        if status == "booked":
            return jsonify({"status": "error", "message": "Seat already booked"}), 409
        if status == "held":
            h = holders.get(seat_id)
            if h and h.get("user") == username:
                holders[seat_id]["expiry"] = time.time() + HOLD_SECONDS
                return jsonify({"status": "ok", "message": "Hold refreshed", "expires_in": HOLD_SECONDS})
            else:
                return jsonify({"status": "error", "message": "Seat held by someone else"}), 409

        seats[seat_id] = "held"
        holders[seat_id] = {"user": username, "expiry": time.time() + HOLD_SECONDS}
        return jsonify({"status": "ok", "message": "Seat held", "expires_in": HOLD_SECONDS})
    finally:
        lock.release()

@app.route('/api/confirm/<seat_id>', methods=['POST'])
def api_confirm(seat_id):
    not_ready = ensure_sync()
    if not_ready: return not_ready

    if 'username' not in session:
        return jsonify({"status": "error", "message": "Login required"}), 401
    username = session['username']
    if seat_id not in seats:
        return jsonify({"status": "error", "message": "Invalid seat"}), 400

    lock = locks[seat_id]
    acquired = lock.acquire(blocking=False)
    if not acquired:
        return jsonify({"status": "error", "message": "Seat busy"}), 409

    try:
        cleanup_expired_holds()
        status = seats.get(seat_id)
        if status != "held":
            return jsonify({"status": "error", "message": "Seat not held"}), 409
        h = holders.get(seat_id)
        if not h or h.get("user") != username:
            return jsonify({"status": "error", "message": "You do not hold this seat"}), 403

        seats[seat_id] = "booked"
        holders.pop(seat_id, None)
        return jsonify({"status": "ok", "message": "Seat booked"})
    finally:
        lock.release()

@app.route('/api/cancel_hold/<seat_id>', methods=['POST'])
def api_cancel_hold(seat_id):
    not_ready = ensure_sync()
    if not_ready: return not_ready

    if 'username' not in session:
        return jsonify({"status": "error", "message": "Login required"}), 401
    username = session['username']
    if seat_id not in seats:
        return jsonify({"status": "error", "message": "Invalid seat"}), 400

    lock = locks[seat_id]
    with lock:
        h = holders.get(seat_id)
        if not h or h.get("user") != username:
            return jsonify({"status": "error", "message": "You don't hold this seat"}), 403
        holders.pop(seat_id, None)
        seats[seat_id] = "available"
        return jsonify({"status": "ok", "message": "Hold cancelled"})


# ---------------- Utility ----------------
@app.route('/api/whoami', methods=['GET'])
def whoami():
    if 'username' not in session:
        return jsonify({"username": None})
    return jsonify({"username": session['username']})

@app.route('/static/<path:path>')
def send_static_file(path):
    return send_from_directory(app.static_folder, path)


# ---------------- Heartbeat Support ----------------
HEARTBEAT_TIMEOUT = 20  # seconds before user considered inactive
PRUNE_INTERVAL = 5      # seconds between pruning

def prune_inactive_users_background():
    """Background thread to remove inactive users and release their holds."""
    while True:
        now = time.time()
        to_remove = []
        for u, last_seen in list(active_users.items()):
            if now - last_seen > HEARTBEAT_TIMEOUT:
                to_remove.append(u)

        for u in to_remove:
            print(f"[HEARTBEAT] User '{u}' inactive for {HEARTBEAT_TIMEOUT}s, removing...")
            active_users.pop(u, None)
            announced_times.pop(u, None)

            # Release any seats held by this user
            for seat_id, h in list(holders.items()):
                if h.get("user") == u:
                    seats[seat_id] = "available"
                    holders.pop(seat_id, None)
                    print(f"[HEARTBEAT] Seat '{seat_id}' released due to inactivity of user '{u}'")

        time.sleep(PRUNE_INTERVAL)

@app.route('/api/heartbeat', methods=['POST'])
def heartbeat():
    """Mark the current user as active and print for demo."""
    if 'username' not in session:
        return jsonify({"status": "error", "message": "not logged in"}), 401

    username = session['username']
    active_users[username] = time.time()  # keep existing functionality
    print(f"[HEARTBEAT] Received from '{username}' at {time.strftime('%H:%M:%S', time.localtime())}")
    return jsonify({"status": "ok"})

# ---------------- Start Background Thread ----------------
threading.Thread(target=prune_inactive_users_background, daemon=True).start()
print("[SYSTEM] Heartbeat pruning thread started")


if __name__ == '__main__':
    app.run(port=5001, debug=True)
