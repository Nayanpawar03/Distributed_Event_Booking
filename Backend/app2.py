from flask import Flask, jsonify
from flask_cors import CORS
from shared_data import seats, locks
import time

app = Flask(__name__)
CORS(app)

@app.route('/seats', methods=['GET'])
def get_seats():
    return jsonify(seats)

@app.route('/book/<seat_id>', methods=['POST'])
def book_seat(seat_id):
    if seat_id not in seats:
        return jsonify({"status": "error", "message": "Invalid seat"}), 400

    lock = locks[seat_id]
    if not lock.acquire(blocking=False):
        return jsonify({"status": "error", "message": "Seat is being booked by someone else"}), 409

    try:
        if seats[seat_id] == "booked":
            return jsonify({"status": "error", "message": "Seat already booked"}), 409

        time.sleep(1)
        seats[seat_id] = "booked"
        return jsonify({"status": "success", "message": f"Seat {seat_id} booked successfully!"})
    finally:
        lock.release()

if __name__ == '__main__':
    app.run(port=5002, debug=True)
