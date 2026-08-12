const robotsEl = document.getElementById('robots');
const peersEl  = document.getElementById('peers');

function renderNodes(el, items, emptyText) {
    if (!items.length) {
        el.innerHTML = `<p class="empty">${emptyText}</p>`;
        return;
    }
    el.innerHTML = items.map(item => `
        <div class="node-box">
            <span class="name">${item.name}</span>
            <span class="meta">${item.meta}</span>
        </div>
    `).join('');
}

function refreshRobots() {
    fetch('/robots')
        .then(r => r.json())
        .then(data => {
            const items = (data.robots || []).map(r => ({
                name: r.name,
                meta: `${r.type} @ ${r.ip} — ${(r.capabilities || []).join(', ') || 'no capabilities'}`,
            }));
            renderNodes(robotsEl, items, 'No robots registered yet.');
        })
        .catch(() => {});
}

function refreshPeers() {
    fetch('/peers')
        .then(r => r.json())
        .then(data => {
            const items = Object.entries(data).map(([name, url]) => ({ name, meta: url }));
            renderNodes(peersEl, items, 'No peers seen yet.');
        })
        .catch(() => {});
}

function refreshAll() {
    refreshRobots();
    refreshPeers();
}

refreshAll();
setInterval(refreshAll, 3000);

// ── Connection Mode ──────────────────────────────────────────────────────

const modeSelect  = document.getElementById('modeSelect');
const btPortInput = document.getElementById('btPortInput');
const modeApply   = document.getElementById('modeApply');
const modeStatus  = document.getElementById('modeStatus');

function syncBtPortVisibility() {
    btPortInput.style.display = modeSelect.value === 'bluetooth' ? 'inline-block' : 'none';
}

function loadMode() {
    fetch('/mode')
        .then(r => r.json())
        .then(data => {
            modeSelect.value = data.mode || 'wifi';
            if (data.bt_port) btPortInput.value = data.bt_port;
            syncBtPortVisibility();
        })
        .catch(() => {});
}

modeSelect.addEventListener('change', syncBtPortVisibility);

modeApply.addEventListener('click', () => {
    const mode = modeSelect.value;
    const bt_port = btPortInput.value.trim();
    modeStatus.textContent = 'applying…';
    fetch('/mode', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ mode, bt_port }),
    })
        .then(r => r.json().then(data => ({ ok: r.ok, data })))
        .then(({ ok, data }) => {
            modeStatus.textContent = ok ? `mode: ${data.mode}` : (data.error || 'failed');
        })
        .catch(() => { modeStatus.textContent = 'network error'; });
});

syncBtPortVisibility();
loadMode();
