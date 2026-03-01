/**
 * BauCu Voting System – Main JavaScript
 */

document.addEventListener('DOMContentLoaded', function () {
    // Auto-dismiss alerts after 5 seconds
    document.querySelectorAll('.alert-dismissible').forEach(function (alert) {
        setTimeout(function () {
            const btn = alert.querySelector('.btn-close');
            if (btn) btn.click();
        }, 5000);
    });

    // Add loading spinner on form submit
    document.querySelectorAll('form').forEach(function (form) {
        form.addEventListener('submit', function () {
            // Don't add spinner for small forms
            if (form.querySelector('[type="file"]') || form.id === 'bulkForm') {
                const overlay = document.createElement('div');
                overlay.className = 'spinner-overlay';
                overlay.innerHTML = '<div class="spinner-border text-primary" role="status">' +
                    '<span class="visually-hidden">Processing...</span></div>';
                document.body.appendChild(overlay);
            }
        });
    });

    // Tooltip initialization
    var tooltipTriggerList = [].slice.call(
        document.querySelectorAll('[data-bs-toggle="tooltip"]')
    );
    tooltipTriggerList.forEach(function (el) {
        new bootstrap.Tooltip(el);
    });
});
