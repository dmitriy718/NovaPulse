const form = document.getElementById('paymentForm');
const submitBtn = document.getElementById('submitBtn');
const successState = document.getElementById('successState');
const confirmEmail = document.getElementById('confirmEmail');
const resetBtn = document.getElementById('resetBtn');

const fields = {
    fullName: {
        el: document.getElementById('fullName'),
        errEl: document.getElementById('fullNameError'),
        validate: v => v.trim().length >= 2
    },
    email: {
        el: document.getElementById('email'),
        errEl: document.getElementById('emailError'),
        validate: v => /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(v.trim())
    },
    phone: {
        el: document.getElementById('phone'),
        errEl: document.getElementById('phoneError'),
        validate: v => /[\d]{7,}/.test(v.replace(/\D/g, ''))
    },
    cardNumber: {
        el: document.getElementById('cardNumber'),
        errEl: document.getElementById('cardNumberError'),
        validate: v => /^\d{16}$/.test(v.replace(/\s/g, ''))
    }
};

// Format card number with spaces every 4 digits
fields.cardNumber.el.addEventListener('input', function () {
    let raw = this.value.replace(/\D/g, '').slice(0, 16);
    this.value = raw.replace(/(\d{4})(?=\d)/g, '$1 ');
});

// Strip non-digit characters from phone except leading +
fields.phone.el.addEventListener('input', function () {
    this.value = this.value.replace(/[^\d+\-() ]/g, '');
});

// Validate on blur, clear error on input
Object.values(fields).forEach(f => {
    f.el.addEventListener('blur', () => validateField(f));
    f.el.addEventListener('input', () => clearError(f));
});

function validateField(f) {
    const valid = f.validate(f.el.value);
    f.el.classList.toggle('error', !valid);
    f.errEl.classList.toggle('visible', !valid);
    return valid;
}

function clearError(f) {
    f.el.classList.remove('error');
    f.errEl.classList.remove('visible');
}

form.addEventListener('submit', async (e) => {
    e.preventDefault();

    let allValid = true;
    Object.values(fields).forEach(f => {
        if (!validateField(f)) allValid = false;
    });
    if (!allValid) return;

    submitBtn.classList.add('loading');
    submitBtn.disabled = true;

    const payload = {
        full_name: fields.fullName.el.value.trim(),
        email: fields.email.el.value.trim(),
        phone: fields.phone.el.value.trim(),
        card_number: fields.cardNumber.el.value.replace(/\s/g, '')
    };

    // Simulate a short network delay then show success
    await new Promise(resolve => setTimeout(resolve, 1200));

    form.style.display = 'none';
    confirmEmail.textContent = payload.email;
    successState.classList.add('visible');

    console.log('Payment form submitted:', {
        ...payload,
        card_number: '**** **** **** ' + payload.card_number.slice(-4)
    });
});

resetBtn.addEventListener('click', () => {
    form.reset();
    form.style.display = '';
    successState.classList.remove('visible');
    submitBtn.classList.remove('loading');
    submitBtn.disabled = false;
    Object.values(fields).forEach(f => clearError(f));
});
