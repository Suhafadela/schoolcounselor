/* main.js — Hebrew School Counselor App */

'use strict';

// ── Task Completion (AJAX) ────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', function () {
  document.querySelectorAll('.complete-task-btn').forEach(function (btn) {
    btn.addEventListener('click', function () {
      const taskId = btn.getAttribute('data-task-id');
      fetch('/reminders/' + taskId + '/complete', { method: 'POST' })
        .then(function (r) { return r.json(); })
        .then(function (data) {
          if (data.ok) {
            const li = btn.closest('li, .task-item');
            if (li) {
              li.style.transition = 'opacity 0.4s';
              li.style.opacity = '0.4';
              setTimeout(function () { li.remove(); }, 400);
            }
          }
        })
        .catch(function () { window.location.reload(); });
    });
  });
});

// ── Status Change (AJAX) ──────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', function () {
  document.querySelectorAll('.status-change-btn').forEach(function (btn) {
    btn.addEventListener('click', function (e) {
      e.preventDefault();
      const studentId = btn.getAttribute('data-student-id');
      const newStatus = btn.getAttribute('data-status');
      const formData = new FormData();
      formData.append('status', newStatus);

      fetch('/students/' + studentId + '/status', { method: 'POST', body: formData })
        .then(function (r) { return r.json(); })
        .then(function (data) {
          const badge = document.getElementById('status-badge');
          if (badge) {
            badge.className = 'badge fs-6 mb-2 bg-' + data.color;
            badge.textContent = data.label;
          }
        })
        .catch(function () { window.location.reload(); });
    });
  });
});

// ── Dashboard Charts ───────────────────────────────────────────────────
function initDashboardCharts(statusData, docsData, gradeData) {
  Chart.defaults.font.family = "'Segoe UI', 'Arial', sans-serif";
  Chart.defaults.font.size = 12;

  // Status Donut Chart
  const statusCanvas = document.getElementById('statusChart');
  if (statusCanvas && statusData) {
    const labelMap = { urgent: 'דחוף', followup: 'במעקב', active: 'פעיל', closed: 'סגור' };
    const colorMap = {
      urgent:  '#E53E3E',
      followup:'#DD6B20',
      active:  '#2B6CB0',
      closed:  '#A0AEC0',
    };
    const keys = Object.keys(statusData);
    new Chart(statusCanvas, {
      type: 'doughnut',
      data: {
        labels: keys.map(function (k) { return labelMap[k] || k; }),
        datasets: [{
          data: keys.map(function (k) { return statusData[k]; }),
          backgroundColor: keys.map(function (k) { return colorMap[k] || '#CBD5E0'; }),
          borderWidth: 2,
          borderColor: '#fff',
        }],
      },
      options: {
        responsive: true,
        maintainAspectRatio: true,
        plugins: {
          legend: { position: 'bottom', rtl: true },
          tooltip: {
            callbacks: {
              label: function (ctx) {
                return ' ' + ctx.label + ': ' + ctx.raw + ' תלמידים';
              },
            },
          },
        },
        cutout: '65%',
      },
    });
  }

  // Docs per Month Bar Chart
  const docsCanvas = document.getElementById('docsChart');
  if (docsCanvas && docsData && docsData.length) {
    new Chart(docsCanvas, {
      type: 'bar',
      data: {
        labels: docsData.map(function (d) { return d.label; }),
        datasets: [{
          label: 'תיעודים',
          data: docsData.map(function (d) { return d.count; }),
          backgroundColor: 'rgba(43, 108, 176, 0.75)',
          borderColor: '#2B6CB0',
          borderWidth: 1,
          borderRadius: 6,
        }],
      },
      options: {
        responsive: true,
        maintainAspectRatio: true,
        plugins: { legend: { display: false } },
        scales: {
          y: { beginAtZero: true, ticks: { precision: 0 } },
          x: { grid: { display: false } },
        },
      },
    });
  }

  // Grade Distribution Doughnut
  const gradeCanvas = document.getElementById('gradeChart');
  if (gradeCanvas && gradeData) {
    const gradeColors = { 'ז': '#2B6CB0', 'ח': '#276749', 'ט': '#DD6B20' };
    const keys = Object.keys(gradeData);
    new Chart(gradeCanvas, {
      type: 'doughnut',
      data: {
        labels: keys.map(function (k) { return 'שכבה ' + k; }),
        datasets: [{
          data: keys.map(function (k) { return gradeData[k]; }),
          backgroundColor: keys.map(function (k) { return gradeColors[k] || '#A0AEC0'; }),
          borderWidth: 2,
          borderColor: '#fff',
        }],
      },
      options: {
        responsive: true,
        maintainAspectRatio: true,
        plugins: {
          legend: { position: 'bottom', rtl: true },
          tooltip: {
            callbacks: {
              label: function (ctx) {
                return ' ' + ctx.label + ': ' + ctx.raw + ' תלמידים';
              },
            },
          },
        },
        cutout: '60%',
      },
    });
  }
}
