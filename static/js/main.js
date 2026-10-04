const robotsEl = document.getElementById('robots');
const peersEl  = document.getElementById('peers');

function renderNodes(el, items, emptyText) {
    if (!items.length) {
        el.innerHTML = `<p class="empty">${emptyText}</p>`;
        return;
    }
    el.innerHTML = items.map(item => `
        <div class="node-box">
            ${item.url ? `<a class="name" href="${item.url}" target="_blank" rel="noopener">${item.name}</a>`
                       : `<span class="name">${item.name}</span>`}
            <span class="meta">${item.meta}</span>
            ${item.url ? `<a class="open" href="${item.url}" target="_blank" rel="noopener">Open &rarr;</a>` : ''}
        </div>
    `).join('');
}

// The whole fleet (RIFT's registry + NORA's + NORA herself), each with a
// button that opens its own web page in a new tab.
function refreshRobots() {
    fetch('/fleet')
        .then(r => r.json())
        .then(data => {
            const items = (data.robots || []).map(r => ({
                name: r.name,
                url: r.url,
                meta: `${r.type} @ ${r.ip} — ${(r.capabilities || []).join(', ') || 'no capabilities'}`,
            }));
            renderNodes(robotsEl, items, 'No robots online yet.');
        })
        .catch(() => {});
}

function refreshPeers() {
    fetch('/peers')
        .then(r => r.json())
        .then(data => {
            const items = Object.entries(data).map(([name, url]) => ({ name, url: url + '/', meta: url }));
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

// ── Mission log ─────────────────────────────────────────────────────────
const missionEl = document.getElementById('mission');

function refreshMission() {
    fetch('/mission')
        .then(r => r.json())
        .then(data => {
            document.getElementById('missionDay').textContent = `mission day ${data.day}`;
            const entries = (data.entries || []).slice().reverse();
            if (!entries.length) return;
            let html = '', lastDay = null;
            for (const e of entries) {
                if (e.day !== lastDay) {
                    html += `<div class="dayhead">DAY ${e.day}</div>`;
                    lastDay = e.day;
                }
                const time = new Date(e.t * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
                html += `<div class="entry"><span class="time">${time}</span><span class="k-${esc(e.kind)}">${e.kind === 'note' ? `<b>${esc(e.who)}:</b> ` : ''}${esc(e.text)}</span></div>`;
            }
            missionEl.innerHTML = html;
        })
        .catch(() => {});
}

function refreshAll() {
    refreshRobots();
    refreshPeers();
    refreshTalk();
    refreshMission();
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
