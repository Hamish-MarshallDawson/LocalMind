'use strict';
// LocalMind gateway page. Everything live arrives on one event stream from the gateway: the PC's
// status, progress of messages on their way to it, and chats as they change.
(() => {
  const $ = (sel, root = document) => root.querySelector(sel);
  const CACHE = 'lm-gateway-v1';
  const OPTS = 'lm-gateway-options';
  const ACTIVE = ['queued', 'waking', 'starting', 'sending', 'running'];
  const touch = window.matchMedia('(pointer: coarse)').matches;

  const S = {
    user: null, pc: null, conversations: [], jobs: new Map(), convs: new Map(),
    cid: null, skew: 0, online: true, version: null, opts: load(OPTS) || { web: false, kb: false, thinking: false },
  };

  // ------------------------------------------------------------------ small helpers
  function load(key) { try { return JSON.parse(localStorage.getItem(key)); } catch { return null; } }
  function save(key, value) { try { localStorage.setItem(key, JSON.stringify(value)); } catch { /* private mode */ } }
  const now = () => Date.now() / 1000 + S.skew;
  const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

  function saveCache() {
    const recent = S.conversations.slice(0, 20).map((c) => S.convs.get(c.id)).filter(Boolean);
    save(CACHE, { pc: S.pc, conversations: S.conversations, convs: recent, user: S.user });
  }

  async function api(path, body, method) {
    const init = body === undefined ? (method ? { method } : {}) : { method: method || 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(body) };
    const res = await fetch(path, { credentials: 'same-origin', ...init });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.error || `The gateway answered ${res.status}`);
    return data;
  }

  function duration(seconds) {
    seconds = Math.max(0, Math.round(seconds));
    if (seconds < 60) return `${seconds}s`;
    const m = Math.floor(seconds / 60);
    if (m < 5 && seconds % 60) return `${m} min ${seconds % 60}s`;
    if (m < 60) return `${m} min`;
    const h = Math.floor(m / 60);
    return m % 60 ? `${h} h ${m % 60} min` : `${h} h`;
  }

  function when(ts) {
    if (!ts) return 'never';
    const d = new Date(ts * 1000);
    const time = d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    const today = new Date(); today.setHours(0, 0, 0, 0);
    const day = new Date(d); day.setHours(0, 0, 0, 0);
    const days = Math.round((today - day) / 86400000);
    if (days === 0) return `at ${time}`;
    if (days === 1) return `yesterday at ${time}`;
    return `${d.toLocaleDateString([], { weekday: 'short', day: 'numeric', month: 'short' })} at ${time}`;
  }

  // ------------------------------------------------------------------ markdown (escaped first, so safe)
  function inline(text) {
    const codes = [];
    let s = esc(text).replace(/`([^`\n]+)`/g, (_, c) => `\u0000${codes.push(c) - 1}\u0000`);
    s = s.replace(/\[([^\]\n]+)\]\((https?:\/\/[^)\s]+)\)/g, '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>');
    s = s.replace(/(^|[\s(])(https?:\/\/[^\s<)]+[^\s<).,;:!?])/g, '$1<a href="$2" target="_blank" rel="noopener noreferrer">$2</a>');
    s = s.replace(/\*\*([^*\n]+)\*\*/g, '<strong>$1</strong>');
    s = s.replace(/(^|[^*\w])\*([^*\s][^*\n]*?)\*(?!\w)/g, '$1<em>$2</em>');
    s = s.replace(/(^|[^\w])_([^_\s][^_\n]*?)_(?!\w)/g, '$1<em>$2</em>');
    return s.replace(/\u0000(\d+)\u0000/g, (_, i) => `<code>${codes[i]}</code>`);
  }

  const BLOCK = /^(```|#{1,6}\s|\s*[-*+]\s+|\s*\d+[.)]\s+|>|\s*\|.*\|\s*$)/;
  function md(src) {
    const lines = String(src || '').replace(/\r\n/g, '\n').split('\n');
    const out = [];
    let i = 0;
    while (i < lines.length) {
      const line = lines[i];
      if (/^```/.test(line)) {
        const code = [];
        i++;
        while (i < lines.length && !/^```/.test(lines[i])) code.push(lines[i++]);
        i++;
        out.push(`<pre><code>${esc(code.join('\n'))}</code></pre>`);
      } else if (/^#{1,6}\s/.test(line)) {
        const level = Math.min(4, line.match(/^#+/)[0].length + 1);
        out.push(`<h${level}>${inline(line.replace(/^#+\s*/, ''))}</h${level}>`);
        i++;
      } else if (/^\s*([-*+]|\d+[.)])\s+/.test(line)) {
        const ordered = /^\s*\d/.test(line);
        const items = [];
        while (i < lines.length && /^\s*([-*+]|\d+[.)])\s+/.test(lines[i])) items.push(lines[i++].replace(/^\s*([-*+]|\d+[.)])\s+/, ''));
        const tag = ordered ? 'ol' : 'ul';
        out.push(`<${tag}>${items.map((it) => `<li>${inline(it)}</li>`).join('')}</${tag}>`);
      } else if (/^>/.test(line)) {
        const quote = [];
        while (i < lines.length && /^>/.test(lines[i])) quote.push(lines[i++].replace(/^>\s?/, ''));
        out.push(`<blockquote>${md(quote.join('\n'))}</blockquote>`);
      } else if (/^\s*\|.*\|\s*$/.test(line)) {
        const rows = [];
        while (i < lines.length && /^\s*\|.*\|\s*$/.test(lines[i])) rows.push(lines[i++]);
        const cells = (r) => r.trim().replace(/^\||\|$/g, '').split('|').map((c) => c.trim());
        const body = rows.filter((r) => !/^\s*\|[\s:|-]+\|\s*$/.test(r)).map(cells);
        out.push(`<div style="overflow-x:auto"><table>${body.map((r, n) => `<tr>${r.map((c) => (n ? `<td>${inline(c)}</td>` : `<th>${inline(c)}</th>`)).join('')}</tr>`).join('')}</table></div>`);
      } else if (!line.trim()) {
        i++;
      } else {
        const para = [];
        while (i < lines.length && lines[i].trim() && !BLOCK.test(lines[i])) para.push(lines[i++]);
        if (!para.length) para.push(lines[i++]);
        out.push(`<p>${para.map(inline).join('<br>')}</p>`);
      }
    }
    return out.join('');
  }

  // ------------------------------------------------------------------ the PC
  const PC_TEXT = {
    online: ['PC on', 'Your PC is on'],
    waking: ['Waking…', 'Waking your PC'],
    shutting_down: ['Shutting down', 'Your PC is shutting down'],
    offline: ['PC off', 'Your PC is off'],
  };

  function pcState() { return (S.pc && S.pc.state) || 'offline'; }

  function pcSummary() {
    const pc = S.pc || {};
    const report = pc.report || {};
    const power = report.power || {};
    const state = pcState();
    if (state === 'waking') {
      return `${esc(pc.wake_detail || 'Waking')} · <span data-since="${pc.waking_since}"></span>`;
    }
    if (state === 'shutting_down') return `${esc(report.reason || 'Shutting down')} (${when(pc.received_at)})`;
    if (state === 'offline') {
      if (!pc.received_at) return 'It hasn’t reported to the gateway yet.';
      if (report.state === 'shutting_down' || report.state === 'stopped') {
        return `Went off ${when(pc.received_at)}: ${esc(report.reason || 'LocalMind stopped')}.`;
      }
      return `Last heard from ${when(pc.received_at)}.`;
    }
    if (!power.auto_shutdown) return 'Auto-shutdown is off.';
    const limit = power.idle_limit_seconds || 600;
    if (power.keep_awake_until) return `Kept awake until ${when(power.keep_awake_until).replace(/^at /, '')}.`;
    return `Turns off after ${duration(limit)} without activity. Idle <span data-idle></span>.`;
  }

  function idleNow() {
    const report = (S.pc && S.pc.report) || {};
    const power = report.power || {};
    if (pcState() !== 'online' || !S.pc.received_at) return null;
    return (power.idle_seconds || 0) + Math.max(0, now() - S.pc.received_at);
  }

  function pcDetails(where) {
    const pc = S.pc || {};
    const report = pc.report || {};
    const state = pcState();
    const gpu = report.gpu;
    const facts = [];
    const past = state !== 'online';
    if (report.loaded_model || report.host) facts.push([past ? 'Last model' : 'Model loaded', report.loaded_model || (past ? 'none loaded' : 'none yet')]);
    if (gpu) facts.push([past ? 'GPU (last seen)' : 'GPU', `${esc(gpu.name)} · ${gpu.used_gb.toFixed(1)} / ${gpu.total_gb.toFixed(0)} GB VRAM`]);
    if (report.running && report.running.length && !past) facts.push(['Answering', `${report.running.length} message${report.running.length > 1 ? 's' : ''}`]);
    if (report.started_at) facts.push([past ? 'Was on since' : 'On since', when(report.started_at).replace(/^at /, '')]);
    if (report.host) facts.push(['Computer', esc(report.host)]);
    const limit = ((report.power || {}).idle_limit_seconds) || 600;
    const idle = idleNow();
    const meter = idle !== null && (report.power || {}).auto_shutdown
      ? `<div class="meter" title="Idle time before auto-shutdown"><i style="width:${Math.min(100, (idle / limit) * 100).toFixed(1)}%"></i></div>` : '';
    const actions = [];
    if (state === 'offline' && pc.can_wake) actions.push('<button class="btn primary" data-action="wake">Wake PC</button>');
    if (state === 'waking') actions.push('<button class="btn" disabled>Waking…</button>');
    if (state === 'online') {
      actions.push('<button class="btn" data-action="keep_awake">Keep awake 1 h</button>');
      actions.push('<button class="btn danger" data-action="shutdown">Shut down</button>');
      if (pc.pc_ui_url) actions.push(`<a class="btn" href="${esc(pc.pc_ui_url)}" target="_blank" rel="noopener">Full LocalMind</a>`);
    }
    if (state === 'shutting_down') actions.push('<button class="btn primary" data-action="cancel_shutdown">Cancel shutdown</button>');
    return `
      <div class="pc-head" ${where === 'sheet' ? 'id="pc-sheet-title"' : ''} data-pc="${state}"><span class="dot"></span>${PC_TEXT[state][1]}</div>
      <p class="pc-sub">${pcSummary()}</p>${meter}
      ${facts.length ? `<dl class="facts">${facts.map(([k, v]) => `<dt>${k}</dt><dd>${v}</dd>`).join('')}</dl>` : ''}
      <div class="pc-actions">${actions.join('')}</div>`;
  }

  function renderRequests() {
    const box = $('#requests');
    const pending = (((S.pc || {}).report || {}).extensions || {}).requests || [];
    if (!pending.length || pcState() !== 'online') { box.hidden = true; box.innerHTML = ''; return; }
    box.hidden = false;
    box.innerHTML = pending.map((r) => `
      <div class="request">
        <div><b>LocalMind asks to add ${r.kind === 'skill' ? 'a skill' : 'an MCP server'}</b></div>
        <code>${esc(r.source)}</code>
        <div class="request-reason">${esc(r.reason)}</div>
        <div class="pc-actions">
          <button class="btn primary" data-action="approve" data-request="${esc(r.id)}">Approve</button>
          <button class="btn" data-action="deny" data-request="${esc(r.id)}">Deny</button>
        </div>
      </div>`).join('');
  }

  function renderPc() {
    renderRequests();
    const state = pcState();
    const pill = $('#pc-pill');
    pill.dataset.pc = state;
    $('#pc-pill-label').textContent = PC_TEXT[state][0];
    $('#pc-card').innerHTML = pcDetails('card');
    $('#pc-sheet-content').innerHTML = pcDetails('sheet');
    renderHint();
    tick();
  }

  function renderHint() {
    const state = pcState();
    const hint = $('#hint');
    const queued = [...S.jobs.values()].some((j) => ['queued', 'waking'].includes(j.state));
    if (!S.online) hint.textContent = 'Offline: messages can’t be sent until this device reaches the gateway.';
    else if (state === 'offline') hint.textContent = S.pc && S.pc.can_wake ? 'Your PC is off. Sending wakes it; the first answer takes a minute or two.' : 'Your PC is off, and waking isn’t set up.';
    else if (state === 'waking' || queued) hint.textContent = 'Waking your PC. Your message will be sent as soon as LocalMind is ready.';
    else if (state === 'shutting_down') hint.textContent = 'Your PC is shutting down. Sending a message cancels it.';
    else hint.textContent = '';
  }

  // ------------------------------------------------------------------ options
  function models() {
    const report = (S.pc && S.pc.report) || {};
    return report.models && report.models.length ? report.models : (load(CACHE)?.pc?.report?.models || []);
  }

  function renderOptions() {
    const list = models();
    const report = (S.pc && S.pc.report) || {};
    const model = $('#model');
    const chosen = S.opts.model && list.some((m) => m.key === S.opts.model) ? S.opts.model : report.default_model || (list[0] || {}).key;
    model.innerHTML = list.length
      ? list.map((m) => `<option value="${esc(m.key)}">${esc(m.label)}${m.cloud ? ' · cloud' : ''}</option>`).join('')
      : '<option value="">Default model</option>';
    model.value = chosen || '';
    const spec = list.find((m) => m.key === model.value) || {};
    const kvs = report.kv_types || [];
    const kv = $('#kv');
    kv.innerHTML = kvs.map((t) => `<option value="${esc(t.key)}" title="${esc(t.description)}">${esc(t.key)} cache</option>`).join('');
    kv.value = S.opts.kv && kvs.some((t) => t.key === S.opts.kv) ? S.opts.kv : report.default_kv || (kvs[0] || {}).key || '';
    $('#kv-wrap').hidden = !kvs.length || !!spec.cloud;
    const sections = report.sections || [];
    const scope = $('#scope');
    scope.innerHTML = '<option value="">All knowledge</option>' + sections
      .map((s) => `<option value="${esc(s.name)}">${esc(s.name)}${s.shared ? '' : ' + shared'}</option>`).join('');
    scope.value = S.opts.scope && sections.some((s) => s.name === S.opts.scope) ? S.opts.scope : '';
    $('#scope-wrap').hidden = !sections.length;
    document.querySelectorAll('.chip[data-opt]').forEach((chip) => {
      const opt = chip.dataset.opt;
      let on = !!S.opts[opt];
      chip.disabled = false;
      if (opt === 'thinking' && spec.thinking === 'none') { on = false; chip.disabled = true; }
      if (opt === 'thinking' && spec.thinking === 'always') { on = true; chip.disabled = true; }
      chip.setAttribute('aria-pressed', String(on));
    });
  }

  function options() {
    const spec = models().find((m) => m.key === $('#model').value) || {};
    return {
      model: $('#model').value || undefined,
      kv_cache: spec.cloud ? undefined : $('#kv').value || undefined,
      web: !!S.opts.web,
      kb: !!S.opts.kb,
      thinking: spec.thinking === 'always' || (spec.thinking !== 'none' && !!S.opts.thinking),
      scope: $('#scope').value || undefined,
    };
  }

  // ------------------------------------------------------------------ chats
  function jobsFor(cid) {
    return [...S.jobs.values()]
      .filter((j) => j.conversation_id === cid && (ACTIVE.includes(j.state) || j.state === 'failed'))
      .sort((a, b) => a.created - b.created);
  }

  function renderChats() {
    const nav = $('#chats');
    if (!S.conversations.length) {
      nav.innerHTML = '<div class="chats-empty">No chats yet. Your conversations with LocalMind appear here, even while the PC is off.</div>';
      return;
    }
    const busy = new Set([...S.jobs.values()].filter((j) => ACTIVE.includes(j.state)).map((j) => j.conversation_id));
    const today = new Date(); today.setHours(0, 0, 0, 0);
    const group = (ts) => {
      const days = Math.floor((today / 1000 - ts) / 86400) + 1;
      return ts * 1000 >= today ? 'Today' : days <= 1 ? 'Yesterday' : days < 7 ? 'Previous 7 days' : 'Older';
    };
    let last = '';
    nav.innerHTML = S.conversations.map((c) => {
      const g = group(c.updated_at);
      const head = g !== last ? `<div class="chat-group">${g}</div>` : '';
      last = g;
      return `${head}<button class="chat-item" data-cid="${esc(c.id)}" ${c.id === S.cid ? 'aria-current="true"' : ''}>
        <span class="t">${esc(c.title)}</span>${busy.has(c.id) ? '<span class="busy" title="On its way"></span>' : ''}</button>`;
    }).join('');
  }

  function renderPanel(m) {
    const dur = m.duration != null ? `<span class="dur">${m.duration}s</span>` : '';
    return `<details class="panel${m.pending ? ' pending' : ''}"><summary><span class="panel-title">${esc(m.title)}</span>${dur}</summary>
      <div class="panel-body msg bot">${md(m.text)}</div></details>`;
  }

  function renderMessage(m) {
    if (m.kind === 'attachment' && m.file) {
      const [cid, name] = m.file.split('/');
      return `<a class="msg file" href="/api/files/${encodeURIComponent(cid)}/${encodeURIComponent(name)}" download>`
        + `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M7 10l5 5 5-5M12 15V3"/></svg>${esc(m.text)}</a>`;
    }
    if (m.kind === 'attachment') return `<div class="msg attachment">\u{1F4CE} ${esc(m.text)}</div>`;
    if (m.role === 'user') return `<div class="msg user">${esc(m.text)}</div>`;
    if (m.kind === 'tool' || m.kind === 'thinking') return renderPanel(m);
    if (m.kind === 'note') return `<div class="msg note">${esc(m.title)}</div>`;
    return `<div class="msg bot">${md(m.text)}</div>`;
  }

  const STEPS = [['waking', 'Wake PC'], ['sending', 'Deliver'], ['running', 'Answer']];
  function renderJob(job) {
    const order = { queued: -1, waking: 0, starting: 0, sending: 1, running: 2 };
    const at = order[job.state] ?? -1;
    const steps = STEPS.map(([key, label], n) => `<li class="${n < at ? 'done' : n === at ? 'now' : ''}">${label}</li>`).join('');
    const reply = (job.reply || []).map(renderMessage).join('');
    if (job.state === 'failed') {
      return `${reply}<div class="job failed"><div class="error">${esc(job.error || 'Something went wrong.')}</div>
        <div class="job-actions"><button class="btn primary" data-action="retry" data-job="${job.id}">Try again</button>
        <button class="btn" data-action="discard" data-job="${job.id}">Discard</button></div></div>`;
    }
    const detail = job.detail || (job.state === 'queued' ? 'Waiting its turn' : '');
    const stop = job.state === 'running' ? 'Stop' : 'Cancel';
    return `${reply}<div class="job"><ul class="steps">${steps}</ul>
      <div class="job-detail"><span>${esc(detail)}</span><span class="elapsed" data-since="${job.created}"></span>
      <button class="btn ghost" data-action="cancel" data-job="${job.id}">${stop}</button></div></div>`;
  }

  function shortCount(n) {
    if (n >= 1e6) return `${(n / 1e6).toFixed(1).replace(/\.0$/, '')}M`;
    if (n >= 1e3) return `${(n / 1e3).toFixed(1).replace(/\.0$/, '')}K`;
    return String(n);
  }

  function renderContext() {
    const box = $('#ctx');
    const running = S.cid ? jobsFor(S.cid).filter((j) => j.context).pop() : null;
    const context = (running && running.context) || (S.convs.get(S.cid) || {}).context;
    $('#delete-chat').hidden = !S.cid;
    if (!S.cid || !context || !context.window) { box.hidden = true; return; }
    const used = Math.min(1, context.tokens / context.window);
    const left = Math.max(0, context.window - context.tokens);
    box.hidden = false;
    box.classList.toggle('warn', used >= 0.7 && used < 0.85);
    box.classList.toggle('full', used >= 0.85);
    $('#ctx-fill').style.width = `${(used * 100).toFixed(1)}%`;
    $('#ctx-text').textContent = `Context ${shortCount(context.tokens)} of ${shortCount(context.window)} used · ${shortCount(left)} left`
      + (used >= 0.85 ? ' · start a new chat soon' : '');
  }

  function renderMessages() {
    renderContext();
    const box = $('#messages');
    const scroller = $('#scroller');
    const nearBottom = scroller.scrollHeight - scroller.scrollTop - scroller.clientHeight < 120;
    const conv = S.cid ? S.convs.get(S.cid) : null;
    const jobs = S.cid ? jobsFor(S.cid) : [];
    $('#title').textContent = conv ? conv.title : (S.conversations.find((c) => c.id === S.cid) || {}).title || 'New chat';
    if (!S.cid || (!jobs.length && !(conv && conv.messages.length))) {
      box.innerHTML = $('#empty-state').innerHTML;
      $('.empty-sub', box).textContent = pcState() === 'online'
        ? 'Your PC is on and ready.'
        : 'Your PC is off. Send a message and it wakes up, answers, then switches itself off again when you’re done.';
      return;
    }
    let messages = conv ? conv.messages.slice() : [];
    // A message already in the PC's copy of the chat is shown once, as part of its delivery.
    for (const job of jobs) {
      for (let i = messages.length - 1; i >= Math.max(0, messages.length - 30); i--) {
        if (messages[i].role === 'user' && messages[i].kind === 'text' && messages[i].text.trim() === job.text.trim()) {
          messages = messages.slice(0, i);
          break;
        }
      }
    }
    const html = messages.map(renderMessage).join('') +
      jobs.map((job) => `<div class="msg user${ACTIVE.includes(job.state) && job.state !== 'running' ? ' queued' : ''}">${esc(job.text)}</div>${renderJob(job)}`).join('');
    box.innerHTML = html;
    tick();
    if (nearBottom) scroller.scrollTop = scroller.scrollHeight;
  }

  async function openChat(cid, { closeDrawer = true } = {}) {
    S.cid = cid;
    if (cid) history.replaceState(null, '', `#c=${encodeURIComponent(cid)}`);
    else history.replaceState(null, '', location.pathname);
    renderChats();
    renderMessages();
    if (closeDrawer) drawer(false);
    if (!cid) return;
    try {
      const conv = await api(`/api/conversations/${encodeURIComponent(cid)}`);
      S.convs.set(cid, conv);
      if (conv.settings) {
        S.opts.scope = conv.settings.scope || '';
        for (const key of ['model', 'web', 'kb', 'thinking']) if (conv.settings[key] !== undefined && conv.settings[key] !== null) S.opts[key] = conv.settings[key];
        if (conv.settings.kv) S.opts.kv = conv.settings.kv;
        renderOptions();
      }
      saveCache();
    } catch { /* a chat that exists only as a queued message, or we're offline: show what we have */ }
    if (S.cid === cid) {
      renderMessages();
      const scroller = $('#scroller');
      scroller.scrollTop = scroller.scrollHeight;
    }
  }

  // ------------------------------------------------------------------ sending
  async function send() {
    const input = $('#input');
    const text = input.value.trim();
    if (!text) return;
    input.value = '';
    autosize();
    try {
      const job = await api('/api/messages', { conversation_id: S.cid || undefined, text, ...options() });
      S.jobs.set(job.id, job);
      if (!S.convs.has(job.conversation_id)) S.convs.set(job.conversation_id, { id: job.conversation_id, title: text.slice(0, 48), messages: [] });
      if (!S.conversations.some((c) => c.id === job.conversation_id)) S.conversations.unshift({ id: job.conversation_id, title: text.slice(0, 48), updated_at: now() });
      S.cid = job.conversation_id;
      history.replaceState(null, '', `#c=${encodeURIComponent(S.cid)}`);
      renderChats();
      renderMessages();
      renderHint();
      const scroller = $('#scroller');
      scroller.scrollTop = scroller.scrollHeight;
    } catch (e) {
      input.value = text;
      autosize();
      banner(`Couldn’t send: ${e.message}`);
    }
  }

  function batchItems() {
    return $('#batch-items').value.split(/^\s*-{3,}\s*$/m).map((s) => s.trim()).filter(Boolean);
  }

  function updateBatchCount() {
    const n = batchItems().length;
    $('#batch-count').textContent = n ? `${n} task${n === 1 ? '' : 's'} will be queued.` : '';
    $('#batch-submit').disabled = !n;
  }

  async function queueBatch() {
    const button = $('#batch-submit');
    button.disabled = true;
    try {
      const result = await api('/api/batches', {
        name: $('#batch-name').value, instructions: $('#batch-instructions').value, items: $('#batch-items').value, ...options(),
      });
      for (const job of result.jobs) S.jobs.set(job.id, job);
      $('#batch-sheet').close();
      $('#batch-items').value = '';
      updateBatchCount();
      banner(`Queued ${result.queued} task${result.queued === 1 ? '' : 's'}. They run one after another${pcState() === 'online' ? '' : ' once the PC is awake'}.`);
      const first = result.jobs[0];
      if (first) openChat(first.conversation_id);
    } catch (e) {
      banner(`Couldn’t queue: ${e.message}`);
    } finally {
      updateBatchCount();
    }
  }

  function autosize() {
    const input = $('#input');
    input.style.height = 'auto';
    input.style.height = `${Math.min(input.scrollHeight, window.innerHeight * 0.4)}px`;
    $('#send').disabled = !input.value.trim();
  }

  // ------------------------------------------------------------------ actions
  async function act(action, button) {
    const job = button && button.dataset.job;
    if (button) button.disabled = true;
    try {
      if (action === 'wake') await api('/api/pc/wake', {});
      else if (action === 'keep_awake') await api('/api/pc/power', { action: 'keep_awake', minutes: 60 });
      else if (action === 'shutdown') {
        if (!confirm('Shut the PC down now?')) return;
        await api('/api/pc/power', { action: 'shutdown', reason: 'Shut down from the gateway' });
      } else if (action === 'cancel_shutdown') await api('/api/pc/power', { action: 'cancel_shutdown' });
      else if (action === 'cancel' || action === 'discard') S.jobs.set(job, await api(`/api/jobs/${job}/cancel`, {}));
      else if (action === 'retry') S.jobs.set(job, await api(`/api/jobs/${job}/retry`, {}));
      else if (action === 'approve' || action === 'deny') {
        const result = await api(`/api/pc/requests/${encodeURIComponent(button.dataset.request)}`, { approve: action === 'approve' });
        banner(result.result || (action === 'approve' ? 'Approved.' : 'Denied.'));
      } else if (action === 'delete-chat') {
        const title = (S.conversations.find((c) => c.id === S.cid) || {}).title || 'this chat';
        if (!confirm(`Delete “${title}”? This removes it from the PC too.`)) return;
        await api(`/api/conversations/${encodeURIComponent(S.cid)}`, undefined, 'DELETE');
        forget(S.cid);
      }
      renderMessages();
      renderChats();
    } catch (e) {
      banner(e.message);
    } finally {
      if (button) button.disabled = false;
    }
  }

  function forget(cid) {
    S.convs.delete(cid);
    S.conversations = S.conversations.filter((c) => c.id !== cid);
    for (const [id, job] of S.jobs) if (job.conversation_id === cid) S.jobs.delete(id);
    saveCache();
    if (S.cid === cid) openChat(null, { closeDrawer: false });
    else renderChats();
  }

  // ------------------------------------------------------------------ banner, drawer, clock
  let bannerTimer = null;
  function banner(text, sticky = false) {
    const el = $('#banner');
    el.textContent = text;
    el.hidden = !text;
    clearTimeout(bannerTimer);
    if (text && !sticky) bannerTimer = setTimeout(() => { el.hidden = true; }, 6000);
  }

  function drawer(open) {
    $('#app').classList.toggle('drawer-open', open);
    $('#scrim').hidden = !open;
  }

  function tick() {
    document.querySelectorAll('[data-since]').forEach((el) => {
      const since = parseFloat(el.dataset.since);
      el.textContent = since ? duration(now() - since) : '';
    });
    const idle = idleNow();
    document.querySelectorAll('[data-idle]').forEach((el) => { el.textContent = idle === null ? '' : duration(idle); });
  }

  // ------------------------------------------------------------------ live connection
  function applyState(state) {
    if (S.version && state.version && state.version !== S.version) {
      location.reload();  // the gateway has been updated: pick up the new page
      return;
    }
    S.version = state.version;
    S.user = state.user;
    S.pc = state.pc;
    if (state.pc && state.pc.now) S.skew = state.pc.now - Date.now() / 1000;
    S.conversations = state.conversations || [];
    S.jobs = new Map((state.jobs || []).map((j) => [j.id, j]));
    saveCache();
    renderPc();
    renderOptions();
    renderChats();
    renderMessages();
  }

  async function refresh() {
    try {
      applyState(await api('/api/state'));
      S.online = true;
      banner('');
      if (S.cid) openChat(S.cid, { closeDrawer: false });
    } catch (e) {
      S.online = false;
      banner(`Can’t reach the gateway (${e.message}). Showing what this device saved; check Tailscale is connected.`, true);
      renderHint();
    }
  }

  function connect() {
    const events = new EventSource('/api/events');
    let lost = false;
    events.addEventListener('open', () => {
      if (lost) refresh();
      lost = false;
      S.online = true;
      renderHint();
    });
    events.addEventListener('error', () => {
      if (!lost) {
        lost = true;
        S.online = false;
        banner('Lost the connection to the gateway. Reconnecting…', true);
        renderHint();
      }
    });
    events.addEventListener('pc', (e) => {
      S.pc = JSON.parse(e.data);
      if (S.pc.now) S.skew = S.pc.now - Date.now() / 1000;
      saveCache();
      renderPc();
      renderOptions();
      if (!S.cid || !(S.convs.get(S.cid) || { messages: [] }).messages.length) renderMessages();
    });
    events.addEventListener('job', (e) => {
      const job = JSON.parse(e.data);
      S.jobs.set(job.id, job);
      renderChats();
      renderHint();
      if (job.conversation_id === S.cid) renderMessages();
    });
    events.addEventListener('conversations', (e) => {
      S.conversations = JSON.parse(e.data);
      saveCache();
      renderChats();
    });
    events.addEventListener('deleted', (e) => forget(JSON.parse(e.data).id));
    events.addEventListener('conversation', (e) => {
      const conv = JSON.parse(e.data);
      S.convs.set(conv.id, conv);
      saveCache();
      if (conv.id === S.cid) renderMessages();
    });
  }

  // ------------------------------------------------------------------ wiring
  function wire() {
    const input = $('#input');
    input.addEventListener('input', autosize);
    input.addEventListener('keydown', (e) => {
      // Enter sends on a keyboard; on a phone it's a new line and the send button sends.
      if (e.key === 'Enter' && !e.shiftKey && !touch && !e.isComposing) {
        e.preventDefault();
        send();
      }
    });
    $('#composer').addEventListener('submit', (e) => { e.preventDefault(); send(); });
    $('#new-chat').addEventListener('click', () => { openChat(null); $('#input').focus(); });
    $('#delete-chat').dataset.action = 'delete-chat';
    $('#open-batch').addEventListener('click', () => { updateBatchCount(); $('#batch-sheet').showModal(); });
    $('#batch-cancel').addEventListener('click', () => $('#batch-sheet').close());
    $('#batch-items').addEventListener('input', updateBatchCount);
    $('#batch-form').addEventListener('submit', (e) => { e.preventDefault(); queueBatch(); });
    $('#batch-sheet').addEventListener('click', (e) => { if (e.target === e.currentTarget) e.currentTarget.close(); });
    $('#menu').addEventListener('click', () => drawer(true));
    $('#close-drawer').addEventListener('click', () => drawer(false));
    $('#scrim').addEventListener('click', () => drawer(false));
    $('#pc-pill').addEventListener('click', () => $('#pc-sheet').showModal());
    $('#pc-sheet').addEventListener('click', (e) => { if (e.target === e.currentTarget) e.currentTarget.close(); });
    $('#chats').addEventListener('click', (e) => {
      const item = e.target.closest('[data-cid]');
      if (item) openChat(item.dataset.cid);
    });
    document.addEventListener('click', (e) => {
      const button = e.target.closest('[data-action]');
      if (button) act(button.dataset.action, button);
    });
    $('#model').addEventListener('change', (e) => { S.opts.model = e.target.value; save(OPTS, S.opts); renderOptions(); });
    $('#kv').addEventListener('change', (e) => { S.opts.kv = e.target.value; save(OPTS, S.opts); });
    $('#scope').addEventListener('change', (e) => { S.opts.scope = e.target.value; save(OPTS, S.opts); });
    document.querySelectorAll('.chip[data-opt]').forEach((chip) => chip.addEventListener('click', () => {
      S.opts[chip.dataset.opt] = chip.getAttribute('aria-pressed') !== 'true';
      save(OPTS, S.opts);
      renderOptions();
    }));
    setInterval(tick, 1000);
    document.addEventListener('visibilitychange', () => { if (!document.hidden) refresh(); });
  }

  function boot() {
    wire();
    const cached = load(CACHE);
    if (cached) {
      S.pc = cached.pc;
      S.user = cached.user;
      S.conversations = cached.conversations || [];
      for (const conv of cached.convs || []) S.convs.set(conv.id, conv);
    }
    const match = location.hash.match(/#c=([^&]+)/);
    S.cid = match ? decodeURIComponent(match[1]) : null;
    renderPc();
    renderOptions();
    renderChats();
    renderMessages();
    autosize();
    refresh();
    connect();
    if ('serviceWorker' in navigator && window.isSecureContext) {
      navigator.serviceWorker.register('sw.js', { updateViaCache: 'none' }).catch(() => {});
      // A new service worker taking over means new files are in place.
      let reloading = false;
      navigator.serviceWorker.addEventListener('controllerchange', () => {
        if (!reloading) { reloading = true; location.reload(); }
      });
    }
  }

  boot();
})();
