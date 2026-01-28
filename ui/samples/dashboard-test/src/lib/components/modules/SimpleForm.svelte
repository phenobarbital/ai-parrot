<script lang="ts">
    // Sample component that fills the dashboard content area
    let formData = $state({
        firstName: "",
        lastName: "",
        email: "",
        phone: "",
        message: "",
    });

    let submitted = $state(false);

    function handleSubmit(e: Event) {
        e.preventDefault();
        submitted = true;
        console.log("Form submitted:", formData);
    }

    function resetForm() {
        formData = {
            firstName: "",
            lastName: "",
            email: "",
            phone: "",
            message: "",
        };
        submitted = false;
    }
</script>

<div class="simple-form-container">
    <div class="form-header">
        <h2>📝 Contact Form</h2>
        <p>This is a sample component rendered in "Component Layout" mode</p>
    </div>

    {#if submitted}
        <div class="success-message">
            <span class="success-icon">✅</span>
            <h3>Thank you, {formData.firstName}!</h3>
            <p>Your message has been submitted successfully.</p>
            <button type="button" class="btn-primary" onclick={resetForm}>
                Submit Another
            </button>
        </div>
    {:else}
        <form class="simple-form" onsubmit={handleSubmit}>
            <div class="form-row">
                <div class="form-group">
                    <label for="firstName">First Name</label>
                    <input
                        type="text"
                        id="firstName"
                        bind:value={formData.firstName}
                        placeholder="John"
                        required
                    />
                </div>
                <div class="form-group">
                    <label for="lastName">Last Name</label>
                    <input
                        type="text"
                        id="lastName"
                        bind:value={formData.lastName}
                        placeholder="Doe"
                        required
                    />
                </div>
            </div>

            <div class="form-row">
                <div class="form-group">
                    <label for="email">Email Address</label>
                    <input
                        type="email"
                        id="email"
                        bind:value={formData.email}
                        placeholder="john.doe@example.com"
                        required
                    />
                </div>
                <div class="form-group">
                    <label for="phone">Phone Number</label>
                    <input
                        type="tel"
                        id="phone"
                        bind:value={formData.phone}
                        placeholder="+1 (555) 123-4567"
                    />
                </div>
            </div>

            <div class="form-group full-width">
                <label for="message">Message</label>
                <textarea
                    id="message"
                    bind:value={formData.message}
                    placeholder="Write your message here..."
                    rows="5"
                    required
                ></textarea>
            </div>

            <div class="form-actions">
                <button type="button" class="btn-secondary" onclick={resetForm}>
                    Clear
                </button>
                <button type="submit" class="btn-primary"> Submit Form </button>
            </div>
        </form>
    {/if}
</div>

<style>
    .simple-form-container {
        max-width: 700px;
        margin: 0 auto;
        padding: 32px;
        background: var(--surface, #fff);
        border-radius: 12px;
        box-shadow: 0 4px 20px rgba(0, 0, 0, 0.08);
    }

    .form-header {
        text-align: center;
        margin-bottom: 32px;
    }

    .form-header h2 {
        margin: 0 0 8px 0;
        color: var(--text, #202124);
        font-size: 1.75rem;
    }

    .form-header p {
        margin: 0;
        color: var(--text-2, #5f6368);
        font-size: 0.95rem;
    }

    .simple-form {
        display: flex;
        flex-direction: column;
        gap: 20px;
    }

    .form-row {
        display: grid;
        grid-template-columns: 1fr 1fr;
        gap: 16px;
    }

    .form-group {
        display: flex;
        flex-direction: column;
        gap: 6px;
    }

    .form-group.full-width {
        grid-column: 1 / -1;
    }

    .form-group label {
        font-size: 0.875rem;
        font-weight: 500;
        color: var(--text, #202124);
    }

    .form-group input,
    .form-group textarea {
        padding: 12px 14px;
        font-size: 0.95rem;
        border: 1px solid var(--border, #dadce0);
        border-radius: 8px;
        background: var(--surface-2, #f8f9fa);
        transition:
            border-color 0.2s,
            box-shadow 0.2s;
    }

    .form-group input:focus,
    .form-group textarea:focus {
        outline: none;
        border-color: var(--primary, #1a73e8);
        box-shadow: 0 0 0 3px rgba(26, 115, 232, 0.15);
    }

    .form-group textarea {
        resize: vertical;
        min-height: 100px;
    }

    .form-actions {
        display: flex;
        justify-content: flex-end;
        gap: 12px;
        margin-top: 8px;
    }

    .btn-primary,
    .btn-secondary {
        padding: 12px 24px;
        font-size: 0.95rem;
        font-weight: 500;
        border-radius: 8px;
        cursor: pointer;
        transition: all 0.2s;
    }

    .btn-primary {
        background: var(--primary, #1a73e8);
        color: white;
        border: none;
    }

    .btn-primary:hover {
        background: var(--primary-dark, #1557b0);
    }

    .btn-secondary {
        background: transparent;
        color: var(--text-2, #5f6368);
        border: 1px solid var(--border, #dadce0);
    }

    .btn-secondary:hover {
        background: var(--surface-2, #f8f9fa);
    }

    .success-message {
        text-align: center;
        padding: 48px 24px;
    }

    .success-icon {
        font-size: 3rem;
        display: block;
        margin-bottom: 16px;
    }

    .success-message h3 {
        margin: 0 0 8px 0;
        color: var(--text, #202124);
    }

    .success-message p {
        margin: 0 0 24px 0;
        color: var(--text-2, #5f6368);
    }

    @media (max-width: 600px) {
        .form-row {
            grid-template-columns: 1fr;
        }
    }
</style>
