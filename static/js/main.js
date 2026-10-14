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

// Each robot's own web page: a web:<port> capability if it sent one, else
// its usual port (same table as app.py's WEB_PORTS).
const WEB_PORTS = { NORA: 5002, KIDA00: 5003, KIDA01: 5004, WHIP: 5005, DREAM: 5009, MILA: 5010, ARM: 5011, NINA: 5012 };
function webUrl(r) {
    const caps = r.capabilities || [];
    const cap = prefix => (caps.find(c => c.startsWith(prefix) && /^\d+$/.test(c.slice(prefix.length))) || '').slice(prefix.length);
    const port = cap('web:') || WEB_PORTS[(r.name || '').toUpperCase()] || cap('talk:');
    if (!port) return null;
    return `${(r.name || '').toUpperCase() === 'DREAM' ? 'https' : 'http'}://${r.ip}:${port}/`;
}

// The whole fleet with an Open button per robot. app.py serves /fleet (its
// registry + NORA's + NORA herself); the other hubs (C++, Go, Rust, Julia,
// F#) only have /robots, so fall back to that.
function refreshRobots() {
    fetch('/fleet')
        .then(r => r.ok ? r.json() : fetch('/robots').then(r2 => r2.json()))
        .then(data => {
            const items = (data.robots || []).map(r => ({
                name: r.name,
                url: r.url || webUrl(r),
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

// Conversations and the mission log come from app.py; on a hub without them
// the sections are hidden instead of sitting empty.
function hideIfMissing(r, sectionId) {
    document.getElementById(sectionId).style.display = r.ok ? '' : 'none';
    if (!r.ok) throw new Error('not on this hub');
    return r.json();
}

function refreshTalk() {
    fetch('/talk')
        .then(r => hideIfMissing(r, 'talkSection'))
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
        .then(r => hideIfMissing(r, 'missionSection'))
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

// ── Who's near whom ──────────────────────────────────────────────────────
// Each robot's own list (and RIFT's, over Bluetooth): zone, trend, what the
// other robot says it's doing - decoded from its Brainfuck by RIFT - and
// whether the robot is making way.
const nearEl = document.getElementById('near');

function nearLine(owner, st) {
    const robots = (st.robots || []).map(r => {
        const said = r.said ? ` says <code title="${esc(r.bf || '')}">${esc(r.said)}</code>` : (r.state ? ` (${esc(r.state)})` : '');
        return `<span class="who">${esc(r.name)}</span> ${esc(r.zone)}, ${esc(r.trend || 'steady')}${said} <span class="via">${esc(r.via || '')} ${r.rssi} dBm</span>`;
    }).join(' &middot; ');
    const doing = st.yielding_to ? `making way for ${esc(st.yielding_to)}` : esc(st.advice || 'clear');
    return `<div class="line"><span class="via">${esc(st.state || '')} &middot; ${doing}</span>
        <span class="who">${esc(owner)}</span> hears: ${robots || '<span class="empty">nobody</span>'}</div>`;
}

function refreshNear() {
    fetch('/near')
        .then(r => r.ok ? r.json() : Promise.reject())
        .then(d => {
            const parts = Object.entries(d.robots || {}).map(([name, st]) => nearLine(name, st));
            if (d.rift && (d.rift.robots || []).length) parts.unshift(nearLine('RIFT', d.rift));
            nearEl.innerHTML = parts.length ? parts.join('') : '<p class="empty">No robot reports anyone nearby yet.</p>';
        })
        .catch(() => {});
}

function refreshAll() {
    refreshRobots();
    refreshPeers();
    refreshTalk();
    refreshMission();
    refreshNear();
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

// ── Ask & tell (POST /talk with verb ask / do: Fleet/relay.py) ──────────

const tellRobot  = document.getElementById('tellRobot');
const tellAction = document.getElementById('tellAction');
const tellOut    = document.getElementById('tellOut');

function talkVerb(body) {
    return fetch('/talk', { method: 'POST', headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify(Object.assign({ from: 'RIFT dashboard' }, body)) })
        .then(r => r.json());
}

function fillRobots() {
    fetch('/fleet').then(r => r.json()).then(data => {
        const names = (data.robots || []).map(r => r.name);
        const keep = tellRobot.value;
        if (names.join() === [...tellRobot.options].map(o => o.value).join()) return;
        tellRobot.innerHTML = names.map(n => `<option>${esc(n)}</option>`).join('') || '<option value="">nobody online</option>';
        if (names.includes(keep)) tellRobot.value = keep;
    }).catch(() => {});
}

function showCore(c) {
    const parts = [];
    if (c.mode != null) parts.push(`mode <b>${esc(c.mode)}</b>`);
    if (c.moving != null) parts.push(c.moving ? '<b>moving</b>' : 'still');
    if (c.music) parts.push(`music <b>${esc(c.music)}</b>`);
    const d = Object.entries(c.distances_cm || {}).map(([k, v]) => `${esc(k)} ${esc(v)} cm`).join(', ');
    if (d) parts.push(d);
    return parts.join(' &middot; ') || 'no common fields in her status';
}

document.getElementById('askBtn').addEventListener('click', () => {
    if (!tellRobot.value) return;
    tellOut.textContent = 'asking...';
    talkVerb({ to: tellRobot.value, verb: 'ask' }).then(d => {
        tellAction.innerHTML = (d.does || []).map(a => `<option>${esc(a)}</option>`).join('');
        tellOut.innerHTML = d.ok
            ? `${esc(d.to)}: ${showCore(d.core || {})}${d.note ? `\n(${esc(d.note)})` : ''}${(d.does || []).length ? '' : '\nNothing she can be told yet.'}`
            : `<span class="bad">${esc(d.error || 'no answer')}</span>`;
    }).catch(() => { tellOut.innerHTML = "<span class='bad'>RIFT didn't answer.</span>"; });
});

function tell(body) {
    return talkVerb(body).then(d => {
        if (d.needs === 'confirmed' && !body.confirmed) {
            if (!confirm(`${body.action} can move ${body.to}. Go ahead?`)) return { ok: false, error: 'You said no.' };
            return tell(Object.assign({}, body, { confirmed: true }));
        }
        return d;
    });
}

document.getElementById('tellBtn').addEventListener('click', () => {
    if (!tellRobot.value || !tellAction.value) { tellOut.textContent = 'Ask her first: that lists what she can do.'; return; }
    const body = { to: tellRobot.value, verb: 'do', action: tellAction.value,
                   seconds: parseFloat(document.getElementById('tellSeconds').value) || 0.5 };
    tellOut.textContent = `telling ${body.to} to ${body.action}...`;
    tell(body).then(d => {
        tellOut.innerHTML = d.ok ? `${esc(d.to)} did <b>${esc(d.action)}</b>.` : `<span class="bad">${esc(d.error || 'she said no')}</span>`;
        refreshMission();
    }).catch(() => { tellOut.innerHTML = "<span class='bad'>RIFT didn't answer.</span>"; });
});

fillRobots();
setInterval(fillRobots, 10000);

// ── Music together (POST /music: Fleet/music.py) ────────────────────────

const musicOut = document.getElementById('musicOut');

function showMusic(d) {
    if (d.error) return `<span class="bad">${esc(d.error)}</span>`;
    return Object.entries(d.players || {}).map(([n, a]) =>
        a.ok ? `<b>${esc(n)}</b> ok` : `<span class="bad">${esc(n)}: ${esc(a.error || 'no')}</span>`).join(' &middot; ');
}

document.querySelectorAll('[data-music]').forEach(btn => btn.addEventListener('click', () => {
    const body = { action: btn.dataset.music, track: parseInt(document.getElementById('musicTrack').value, 10) };
    musicOut.textContent = `${body.action}...`;
    fetch('/music', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
        .then(r => r.json()).then(d => { musicOut.innerHTML = showMusic(d); refreshMission(); })
        .catch(() => { musicOut.innerHTML = "<span class='bad'>RIFT didn't answer.</span>"; });
}));

fetch('/music').then(r => r.ok ? r.json() : Promise.reject()).then(d => {
    musicOut.innerHTML = d.players.length ? `Players: ${d.players.map(esc).join(', ')}` : 'No players registered (music:&lt;port&gt;).';
}).catch(() => { document.getElementById('musicSection').style.display = 'none'; });
