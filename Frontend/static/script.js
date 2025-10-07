async function fetchSeats() {
    const res = await fetch("/seats");
    const seats = await res.json();
    renderSeats(seats);
}

function renderSeats(seats) {
    const container = document.getElementById("seat-container");
    container.innerHTML = "";
    Object.keys(seats).forEach(seatId => {
        const seatDiv = document.createElement("div");
        seatDiv.classList.add("seat", seats[seatId]);
        seatDiv.textContent = seatId;

        if (seats[seatId] === "available") {
            seatDiv.onclick = () => bookSeat(seatId);
        }

        container.appendChild(seatDiv);
    });
}

async function bookSeat(seatId) {
    const res = await fetch(`/book/${seatId}`, { method: "POST" });
    const data = await res.json();
    alert(data.message);
    fetchSeats();
}

setInterval(fetchSeats, 2000);
fetchSeats();
