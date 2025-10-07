# backend/shared_data.py
from threading import Lock

# initial seats
seats = {f"A{i}": "available" for i in range(1, 13)}  # A1..A12
# a lock per seat to coordinate operations inside server
locks = {seat_id: Lock() for seat_id in seats}
# who holds each seat: { seat_id: {"user": username, "expiry": epoch_seconds} }
holders = {}
