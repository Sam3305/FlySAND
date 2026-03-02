let currentRole = 'user'; // Default selected role on login screen

// --- 1. LOGIN PAGE LOGIC ---
function selectRole(role) {
    currentRole = role;
    
    // Update active tab button visually
    document.querySelectorAll('.role-btn').forEach(btn => btn.classList.remove('active'));
    document.getElementById(`btn-${role}`).classList.add('active');

    // Autofill credentials for demo purposes
    const userField = document.getElementById('username');
    const passField = document.getElementById('password');
    
    if (role === 'user') { userField.value = 'passenger123'; passField.value = 'pass123'; }
    if (role === 'analyst') { userField.value = 'business_pro'; passField.value = 'data123'; }
    if (role === 'admin') { userField.value = 'sys_admin'; passField.value = 'root123'; }
}

function doLogin() {
    // 1. Hide Login Page, Show Dashboard Page
    document.getElementById('login-page').classList.remove('active');
    document.getElementById('dashboard-page').classList.add('active');

    // 2. Hide all dashboard contents first
    document.querySelectorAll('.dashboard-content').forEach(el => el.classList.remove('active'));

    // 3. Setup the Dashboard based on the logged-in role
    const welcomeText = document.getElementById('welcome-text');

    if (currentRole === 'analyst') {
        welcomeText.innerText = 'Analyst Dashboard';
        document.getElementById('dashboard-analyst').classList.add('active');
    } 
    else if (currentRole === 'admin') {
        welcomeText.innerText = 'System Administrator';
        document.getElementById('dashboard-booking').classList.add('active');
        document.getElementById('admin-sim-panel').style.display = 'block'; // Show Physics panel
    } 
    else {
        welcomeText.innerText = 'Passenger Portal';
        document.getElementById('dashboard-booking').classList.add('active');
        document.getElementById('admin-sim-panel').style.display = 'none'; // Hide Physics panel
    }
}

function doLogout() {
    document.getElementById('dashboard-page').classList.remove('active');
    document.getElementById('login-page').classList.add('active');
}

// --- 2. DASHBOARD LOGIC (Search & Autocomplete) ---
const airports = [
    { code: 'DEL', city: 'Delhi', name: 'Indira Gandhi Int.' },
    { code: 'BOM', city: 'Mumbai', name: 'Chhatrapati Shivaji Int.' },
    { code: 'BLR', city: 'Bengaluru', name: 'Kempegowda Int.' },
    { code: 'MAA', city: 'Chennai', name: 'Chennai Int.' }
];

function setupAutocomplete(inputId, suggestionBoxId) {
    const input = document.getElementById(inputId);
    const suggestionBox = document.getElementById(suggestionBoxId);

    input.addEventListener('input', function() {
        const val = this.value.toLowerCase().trim();
        suggestionBox.innerHTML = ''; 
        if (!val) { suggestionBox.style.display = 'none'; return; }

        const matches = airports.filter(a => a.city.toLowerCase().includes(val) || a.code.toLowerCase().includes(val));

        if (matches.length > 0) {
            suggestionBox.style.display = 'block';
            matches.forEach(match => {
                const div = document.createElement('div');
                div.className = 'suggestion-item';
                div.innerHTML = `<b>${match.city} (${match.code})</b>`;
                div.onclick = function() {
                    input.value = match.code; 
                    suggestionBox.style.display = 'none';
                };
                suggestionBox.appendChild(div);
            });
        } else {
            suggestionBox.style.display = 'none';
        }
    });

    document.addEventListener('click', e => { if (e.target !== input) suggestionBox.style.display = 'none'; });
}

setupAutocomplete('origin', 'origin-suggestions');
setupAutocomplete('dest', 'dest-suggestions');

function searchFlights() {
    const origin = document.getElementById('origin').value || 'DEL';
    const dest = document.getElementById('dest').value || 'BOM';
    
    document.getElementById('res-origin').innerText = origin;
    document.getElementById('res-dest').innerText = dest;
    document.getElementById('flight-results').style.display = 'block';
}