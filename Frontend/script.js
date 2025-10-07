const seatContainer = document.getElementById("seat-container");
const serverSelect = document.getElementById("server-select");

function getServerURL() {
    return serverSelect.value;
}

async function fetchSeats() {
    const res = await fetch(`${getServerURL()}/seats`);
    const seats = await res.json();
    renderSeats(seats);
}

function renderSeats(seats) {
    seatContainer.innerHTML = "";
    Object.keys(seats).forEach(seatId => {
        const seatDiv = document.createElement("div");
        seatDiv.classList.add("seat", seats[seatId]);
        seatDiv.textContent = seatId;

        if (seats[seatId] === "available") {
            seatDiv.onclick = () => bookSeat(seatId);
        }

        seatContainer.appendChild(seatDiv);
    });
}

async function bookSeat(seatId) {
    const res = await fetch(`${getServerURL()}/book/${seatId}`, { method: "POST" });
    const data = await res.json();
    alert(data.message);
    fetchSeats();
}

// Auto-refresh every 2 seconds
setInterval(fetchSeats, 2000);
fetchSeats();
