/**
 * BauCu Dashboard – Real-time updates with Chart.js
 */

let dashboardChart = null;
let refreshInterval = null;
const REFRESH_SECONDS = 30;

const COLORS = [
    '#0d6efd', '#198754', '#dc3545', '#ffc107', '#0dcaf0',
    '#6f42c1', '#fd7e14', '#20c997', '#6610f2', '#d63384',
];

function initDashboard(electionPk) {
    // Parse initial data
    const dataEl = document.getElementById('dashboardData');
    let initialData;
    try {
        initialData = JSON.parse(dataEl.textContent);
    } catch (e) {
        initialData = { candidates: [], total_ballots: 0, verified_ballots: 0 };
    }

    // Create Chart.js pie chart
    createChart(initialData);

    // Start auto-refresh
    startAutoRefresh(electionPk);
}

function createChart(data) {
    const ctx = document.getElementById('chartCanvas');
    if (!ctx) return;

    const labels = data.candidates.map(c => c.order + ' – ' + c.name);
    const values = data.candidates.map(c => c.total_votes);
    const colors = data.candidates.map((_, i) => COLORS[i % COLORS.length]);

    if (dashboardChart) {
        dashboardChart.destroy();
    }

    dashboardChart = new Chart(ctx, {
        type: 'doughnut',
        data: {
            labels: labels,
            datasets: [{
                data: values,
                backgroundColor: colors,
                borderWidth: 2,
                borderColor: '#fff',
            }],
        },
        options: {
            responsive: true,
            maintainAspectRatio: true,
            plugins: {
                legend: {
                    position: 'bottom',
                    labels: {
                        padding: 15,
                        usePointStyle: true,
                    },
                },
                tooltip: {
                    callbacks: {
                        label: function (context) {
                            const total = context.dataset.data.reduce((a, b) => a + b, 0);
                            const pct = total ? ((context.parsed / total) * 100).toFixed(1) : 0;
                            return context.label + ': ' + context.parsed + ' (' + pct + '%)';
                        },
                    },
                },
            },
        },
    });
}

function updateDashboard(data) {
    // Update summary cards
    const totalEl = document.getElementById('totalBallots');
    const verifiedEl = document.getElementById('verifiedBallots');
    const pendingEl = document.getElementById('pendingBallots');

    if (totalEl) totalEl.textContent = data.total_ballots;
    if (verifiedEl) verifiedEl.textContent = data.verified_ballots;
    if (pendingEl) pendingEl.textContent = data.total_ballots - data.verified_ballots;

    // Update progress bars
    const barsContainer = document.getElementById('voteBars');
    if (barsContainer && data.candidates) {
        let html = '';
        data.candidates.forEach(function (c) {
            html += `
            <div class="mb-3">
                <div class="d-flex justify-content-between mb-1">
                    <span class="fw-semibold">
                        <span class="badge bg-secondary me-1">${c.order}</span> ${c.name}
                    </span>
                    <span>${c.total_votes} votes <span class="text-muted">(${c.percentage}%)</span></span>
                </div>
                <div class="progress" style="height: 28px;">
                    <div class="progress-bar bar-animated bg-primary"
                         role="progressbar"
                         style="width: ${c.percentage}%;">${c.percentage}%</div>
                </div>
                <div class="small text-muted mt-1">
                    Verified: ${c.verified_votes} (${c.verified_percentage}%)
                </div>
            </div>`;
        });
        barsContainer.innerHTML = html;
    }

    // Update summary table
    const tbody = document.querySelector('#summaryTable tbody');
    if (tbody && data.candidates) {
        let rows = '';
        data.candidates.forEach(function (c) {
            rows += `<tr>
                <td><span class="badge bg-secondary">${c.order}</span> ${c.name}</td>
                <td class="text-end">${c.total_votes}</td>
                <td class="text-end">${c.percentage}%</td>
                <td class="text-end">${c.verified_votes}</td>
            </tr>`;
        });
        tbody.innerHTML = rows;
    }

    // Update chart
    if (dashboardChart && data.candidates) {
        dashboardChart.data.datasets[0].data = data.candidates.map(c => c.total_votes);
        dashboardChart.data.labels = data.candidates.map(c => c.order + ' – ' + c.name);
        dashboardChart.update('none');
    }
}

function startAutoRefresh(electionPk) {
    let countdown = REFRESH_SECONDS;
    const countdownEl = document.getElementById('countdown');

    refreshInterval = setInterval(function () {
        countdown--;
        if (countdownEl) countdownEl.textContent = countdown;

        if (countdown <= 0) {
            countdown = REFRESH_SECONDS;
            fetchDashboardData(electionPk);
        }
    }, 1000);
}

function fetchDashboardData(electionPk) {
    fetch(`/voting/api/${electionPk}/dashboard/`, {
        headers: { 'X-Requested-With': 'XMLHttpRequest' },
        credentials: 'same-origin',
    })
        .then(response => response.json())
        .then(data => updateDashboard(data))
        .catch(err => console.error('Dashboard refresh failed:', err));
}
