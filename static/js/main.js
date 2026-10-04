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

// ── Conversations ────────────────────────────────────────────────────────
// Each line: who said what to whom, the Brainfuck program and what it prints.

const talkEl  = document.getElementById('talk');
const moodsEl = document.getElementById('moods');
const esc = s => String(s).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));

function moodWord(m) {
    if (m > 0.5) return 'bright';
    if (m > 0.1) return 'content';
    if (m > -0.3) return 'quiet';
    return 'sleepy';
}

function refreshTalk() {
    fetch('/talk')
        .then(r => r.json())
        .then(data => {
            const log = (data.log || []).slice(-15).reverse();
            talkEl.innerHTML = log.length ? log.map(e => `
                <div class="line${e.ok ? '' : ' failed'}">
                    <span class="via">${e.via === 'ir' ? 'IR' : 'WiFi'} · ${new Date(e.t * 1000).toLocaleTimeString()}</span>
                    <span class="who">${esc(e.from)} &rarr; ${esc(e.to)}</span>
                    <span class="says">&ldquo;${esc(e.text)}&rdquo;</span>${e.ok ? '' : ' (no answer)'}
                    <span class="bf">${esc(e.bf)}</span>
                </div>`).join('') : '<p class="empty">No conversations yet.</p>';
            moodsEl.innerHTML = Object.entries(data.moods || {})
                .map(([n, m]) => `<span class="mood">${esc(n)}: ${moodWord(m)}</span>`).join('');
        })
        .catch(() => {});
}

document.getElementById('talkNow').addEventListener('click', () => {
    fetch('/talk', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' })
        .then(() => setTimeout(refreshTalk, 500))
        .catch(() => {});
});

function refreshAll() {
    refreshRobots();
    refreshPeers();
    refreshTalk();
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
