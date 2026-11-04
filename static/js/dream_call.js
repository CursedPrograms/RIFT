/*
 * dream_call.js - DREAM on a call, in RIFT's dashboard.
 *
 * When DREAM runs on another PC, the DREAM button opens a window with her live: the clip her own
 * screen is playing, at the same moment, and her voice as she speaks (both from her mirror on
 * :5015, which says which clip she's on and how far in). You talk back with the mic (hold to talk)
 * or the box: RIFT passes it to her (/dream/call), she answers on her own screen, and you see and
 * hear that here. The conversation shows like her dashboard's, as a chat: what you and anyone at
 * her own PC said to her, and everything she said (her mirror's /transcript), so she works as a
 * chatbot too, and her states (listening, thinking, talking) play along on both screens. On the
 * same PC her own window is the call, so the button stays hidden; her dashboard link shows either way.
 */
(() => {
  const $ = id => document.getElementById(id);
  const links = $('dreamLinks'), toggle = $('dreamToggle'), dash = $('dreamDash');
  const win = $('dreamCall'), video = $('dcVideo'), stateEl = $('dcState'), caption = $('dcCaption');
  const mic = $('dcMic'), text = $('dcText'), send = $('dcSend'), chat = $('dcChat');
  let chatSeq = 0, chatBusy = false;
  if (!links || !win) return;

  let info = null, poller = null, clip = null, speechId = null, voice = null;
  const DRIFT = 0.35;   // seconds off her screen before the clip is moved back in step

  async function loadInfo() {
    try { info = await (await fetch('/dream/info')).json(); } catch { info = null; }   // not RIFT's Python hub
    const found = info && info.found;
    links.hidden = !found;
    if (!found) { if (!win.hidden) close(); return; }
    dash.href = info.dashboard;
    toggle.hidden = info.same_pc;                  // same PC: her own window is the call
    if (info.same_pc && !win.hidden) close();
  }

  // ---- her screen, in step ----
  function seekTo(st) {
    if (!video.duration || !isFinite(video.duration)) return;
    let t = st.clip_ms / 1000;
    t = st.loop ? t % video.duration : Math.min(t, video.duration - 0.05);
    if (Math.abs(video.currentTime - t) > DRIFT) video.currentTime = t;
  }

  async function poll() {
    let st;
    try { st = await (await fetch(info.mirror + '/status', { cache: 'no-store' })).json(); }
    catch { stateEl.textContent = "can't reach her"; return; }
    stateEl.textContent = st.sleeping ? 'asleep' : (st.state || '');
    if (st.clip && st.clip !== clip) {
      clip = st.clip;
      video.loop = st.loop;
      video.src = `${info.mirror}/video/${encodeURIComponent(clip)}.mp4`;
      video.onloadedmetadata = () => { seekTo(st); video.play().catch(() => {}); };
    } else {
      seekTo(st);
      if (video.paused && video.src) video.play().catch(() => {});
    }
    // her voice: a new line starts from as far in as she already is
    if (st.speech && st.speech !== speechId) {
      speechId = st.speech;
      if (voice) voice.pause();
      voice = new Audio(`${info.mirror}/speech/${encodeURIComponent(speechId)}.wav`);
      const from = st.speech_ms / 1000;
      voice.onloadedmetadata = () => { if (from > 0.3 && from < voice.duration) voice.currentTime = from; };
      voice.play().catch(() => {});
    } else if (!st.speech) {
      speechId = null;                             // the same cached line ("Yes?") can play again
    }
  }

  // ---- the conversation, as on her dashboard ----
  function addLine(role, t) {
    const el = document.createElement('div');
    el.className = `dc-line ${role}`;
    el.textContent = t;
    const atEnd = chat.scrollHeight - chat.scrollTop - chat.clientHeight < 30;
    chat.appendChild(el);
    while (chat.children.length > 200) chat.removeChild(chat.firstChild);
    if (atEnd) chat.scrollTop = chat.scrollHeight;
  }
  async function pollChat() {
    if (chatBusy) return;
    chatBusy = true;
    try {
      const d = await (await fetch(`${info.mirror}/transcript?after=${chatSeq}`, { cache: 'no-store' })).json();
      if (d.seq < chatSeq) { chat.textContent = ''; chatSeq = 0; }   // DREAM restarted: start over
      for (const l of d.lines) addLine(l.role, l.text);
      chatSeq = d.seq;
    } catch { /* her mirror answers again soon */ }
    chatBusy = false;
  }

  function open() {
    if (!info || !info.found || info.same_pc) return;
    win.hidden = false;
    clip = null; speechId = null;
    chat.textContent = ''; chatSeq = 0;
    poll(); pollChat();
    poller = setInterval(() => { poll(); pollChat(); }, 500);
    localStorage.setItem('dreamCallOpen', '1');
  }
  function close() {
    win.hidden = true;
    clearInterval(poller); poller = null;
    video.pause(); video.removeAttribute('src'); video.load();
    if (voice) voice.pause();
    localStorage.removeItem('dreamCallOpen');
  }
  toggle.addEventListener('click', () => (win.hidden ? open() : close()));
  $('dcClose').addEventListener('click', close);

  // ---- you, to her ----
  async function call(body) {
    caption.textContent = 'DREAM is listening...';
    send.disabled = true;
    try {
      const r = await fetch('/dream/call', body);
      const d = await r.json();
      caption.textContent = d.error === 'busy' ? "She's answering someone. Try again in a moment."
        : d.error ? d.error
        : d.asleep ? (d.reply ? `(asleep) ${d.reply}` : '(asleep: she sleeps on)')
        : '';   // her answer shows in the chat, as she says it
    } catch { caption.textContent = "Couldn't reach her."; }
    send.disabled = false;
    pollChat();
  }
  function sendText() {
    const t = text.value.trim();
    if (!t) return;
    text.value = '';
    call({ method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ text: t }) });
  }
  send.addEventListener('click', sendText);
  text.addEventListener('keydown', e => { if (e.key === 'Enter') sendText(); });

  // hold to talk (the browser only allows the mic on a secure page: localhost or https)
  let rec = null, chunks = [];
  if (!navigator.mediaDevices || !window.MediaRecorder) mic.hidden = true;
  async function startRec() {
    if (rec) return;
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      rec = new MediaRecorder(stream);
      chunks = [];
      rec.ondataavailable = e => { if (e.data.size) chunks.push(e.data); };
      rec.onstop = () => {
        stream.getTracks().forEach(t => t.stop());
        const fd = new FormData();
        fd.append('audio', new Blob(chunks, { type: rec.mimeType || 'audio/webm' }), 'call.webm');
        rec = null;
        mic.classList.remove('rec');
        call({ method: 'POST', body: fd });
      };
      rec.start();
      mic.classList.add('rec');
    } catch { caption.textContent = 'No microphone here (it needs this page on localhost or https).'; }
  }
  function stopRec() { if (rec && rec.state === 'recording') rec.stop(); }
  mic.addEventListener('pointerdown', e => { e.preventDefault(); startRec(); });
  ['pointerup', 'pointerleave', 'pointercancel'].forEach(ev => mic.addEventListener(ev, stopRec));

  // ---- move the window by its title bar ----
  const head = win.querySelector('.dc-head');
  head.addEventListener('pointerdown', e => {
    if (e.target.tagName === 'BUTTON') return;
    const r = win.getBoundingClientRect(), dx = e.clientX - r.left, dy = e.clientY - r.top;
    const move = m => {
      win.style.left = `${Math.max(0, m.clientX - dx)}px`; win.style.top = `${Math.max(0, m.clientY - dy)}px`;
      win.style.right = 'auto'; win.style.bottom = 'auto';
    };
    const up = () => { removeEventListener('pointermove', move); removeEventListener('pointerup', up); };
    addEventListener('pointermove', move); addEventListener('pointerup', up);
  });

  loadInfo().then(() => { if (localStorage.getItem('dreamCallOpen') && info && info.found && !info.same_pc) open(); });
  setInterval(loadInfo, 10000);
})();
