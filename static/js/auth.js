let selectedRole = null;

function selectRole(role) {
    selectedRole = role;
    
    // 1. UI Update: Visual feedback for the cards
    // We remove active classes from all and add them only to the clicked one
    document.querySelectorAll('.role-card').forEach(card => {
        card.classList.remove('active', 'ring-2', 'ring-indigo-600', 'bg-indigo-50');
        card.classList.add('border-white'); // Reset border
    });

    const activeCard = document.getElementById(`card-${role}`);
    if (activeCard) {
        activeCard.classList.add('active', 'ring-2', 'ring-indigo-600', 'bg-indigo-50');
        activeCard.classList.remove('border-white');
    }

    // 2. Show Login Form
    const form = document.getElementById('loginForm');
    form.classList.remove('hidden');
    
    // 3. Update Form Title
    const title = document.getElementById('selectedRoleTitle');
    if (title) {
        title.innerText = `${role.charAt(0).toUpperCase() + role.slice(1)} Login`;
    }
    
    // 4. Smooth scroll to form so the user sees it immediately
    form.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

async function handleLogin() {
    const emailInput = document.getElementById('email');
    const passwordInput = document.getElementById('password');
    const email = emailInput.value;
    const password = passwordInput.value;

    // Basic Validation
    if(!email || !password) {
        alert("Please enter both email and password.");
        return;
    }

    // Button Loading State
    // We try to find the button inside the login form to change its text
    const btn = document.querySelector('#loginForm button');
    const originalBtnText = btn ? btn.innerText : 'Sign In';
    
    if(btn) {
        btn.innerText = "Verifying Credentials...";
        btn.disabled = true;
    }

    try {
        // CALL THE FLASK BACKEND (The Proxy Pattern)
        // We do not call Supabase directly here. We ask Flask to do it.
        const response = await fetch('/api/login', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ 
                email: email, 
                password: password 
            })
        });

        const data = await response.json();

        if (!response.ok) {
            throw new Error(data.error || "Login failed. Please check your credentials.");
        }

        // SUCCESS!
        // 1. Store the session token (useful for future API calls)
        localStorage.setItem('sb-access-token', data.session.access_token);
        
        // 2. Store the User Info returned by the database
        // NOTE: We trust the DB role, not just what card they clicked.
        localStorage.setItem('userRole', data.role);
        localStorage.setItem('userFullName', data.full_name);

        // 3. Optional: Check if they logged in via the wrong card
        if (selectedRole && selectedRole !== data.role) {
            console.warn(`User selected ${selectedRole} but account is ${data.role}. Redirecting based on DB role.`);
        }

        // 4. Redirect to Dashboard
        window.location.href = "/dashboard";

    } catch (err) {
        console.error("Login Error:", err);
        alert(err.message);
        
        // Reset button
        if(btn) {
            btn.innerText = originalBtnText;
            btn.disabled = false;
        }
    }
}