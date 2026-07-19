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
