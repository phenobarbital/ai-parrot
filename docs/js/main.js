document.addEventListener('DOMContentLoaded', function () {
    // Initialize Mermaid
    mermaid.initialize({
        startOnLoad: true,
        theme: 'dark',
        securityLevel: 'loose',
        fontFamily: 'Inter, sans-serif'
    });

    // Smooth Scroll for anchor links
    document.querySelectorAll('a[href^="#"]').forEach(anchor => {
        anchor.addEventListener('click', function (e) {
            e.preventDefault();
            document.querySelector(this.getAttribute('href')).scrollIntoView({
                behavior: 'smooth'
            });
        });
    });

    // Simple Intersection Observer to fade in elements
    const observerOptions = {
        threshold: 0.1
    };

    const observer = new IntersectionObserver((entries) => {
        entries.forEach(entry => {
            if (entry.isIntersecting) {
                entry.target.classList.add('visible');
                observer.unobserve(entry.target);
            }
        });
    }, observerOptions);

    document.querySelectorAll('.feature-card, .code-wrapper').forEach(el => {
        el.style.opacity = '0';
        el.style.transform = 'translateY(20px)';
        el.style.transition = 'opacity 0.6s ease-out, transform 0.6s ease-out';
        observer.observe(el);
    });
});

// Helper for Fade In class
document.addEventListener('DOMContentLoaded', () => {
    const style = document.createElement('style');
    style.innerHTML = `
       .visible {
           opacity: 1 !important;
           transform: translateY(0) !important;
       }
   `;
    document.head.appendChild(style);
});
