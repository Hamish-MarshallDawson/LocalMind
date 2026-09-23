  // ------------------------------------------------------------------ voice conversation
  // Voice mode is a loop: listen until you stop talking, transcribe on the server (faster-whisper),
  // send that as your message, read the reply aloud a sentence at a time as it streams (Kokoro),
  // then listen again. The Voice chip's server event decides on or off; this runs the loop.
  // Runs inside the page-load function in theme.py, alongside the free-scroll code.
  const V = {
    on: false, state: 'off', stream: null, ctx: null, analyser: null, samples: null,
    recorder: null, heard: 0, quiet: 0, loud: 0, floor: 0.01, listenStart: 0,
    audio: null, queue: [], playing: false, stopAudio: null, gen: 0,
    reply: null, sending: false, timer: null, message: '',
  };
  const TICK = 50;              // ms between microphone level readings
  const START_MS = 150;         // this much sound above the noise floor counts as speech
  const SILENCE_MS = 1100;      // and this much quiet after it ends what you said
  const MIN_SPEECH_MS = 350;    // shorter blips (a cough, a door) are ignored
  const MAX_UTTERANCE_MS = 60000;
  const IDLE_RESTART_MS = 20000; // restart an idle recording so it never grows large
  const HEADERS = { 'x-localmind-voice': '1' };
  const SILENT_WAV = 'data:audio/wav;base64,UklGRiQAAABXQVZFZm10IBAAAAABAAEAQB8AAIA+AAACABAAZGF0YQAAAAA=';
  const api = (path) => new URL('localmind/voice/' + path, document.baseURI).toString();
  const $ = (sel) => document.querySelector(sel);
  const visible = (el) => !!el && el.offsetParent !== null;
  const busy = () => visible($('#lm-composer .stop-button'));

  // ---------------------------------------------------------------- status bar above the composer
  const LABELS = {
    starting: ['Starting the microphone…', ''],
    listening: ['Listening. Just start talking', ''],
    hearing: ['Hearing you…', 'Done'],
    transcribing: ['Transcribing…', ''],
    waiting: ['Thinking…', 'Stop'],
    speaking: ['Speaking', 'Interrupt'],
    error: ['', 'Dismiss'],
  };

  function bar() {
    const card = $('#lm-composer-card');
    if (!card) return null;
    let el = document.getElementById('lm-voice-bar');
    if (!el || el.nextElementSibling !== card) {
      if (el) el.remove();
      el = document.createElement('div');
      el.id = 'lm-voice-bar';
      el.setAttribute('role', 'status');
      el.setAttribute('aria-live', 'polite');
      el.innerHTML = '<span class="lm-vb-meter" aria-hidden="true"><i></i><i></i><i></i><i></i><i></i></span>' +
        '<span class="lm-vb-label"></span><button type="button" class="lm-vb-action"></button>';
      el.querySelector('.lm-vb-action').addEventListener('click', onAction);
      card.parentElement.insertBefore(el, card);
    }
    return el;
  }

  function setState(state, message) {
    V.state = state;
    if (message !== undefined) V.message = message;
    const el = bar();
    if (!el) return;
    const [label, action] = LABELS[state] || ['', ''];
    el.className = 'lm-vb-' + state;
    el.hidden = state === 'off';
    el.querySelector('.lm-vb-label').textContent = state === 'error' ? V.message : label;
    const button = el.querySelector('.lm-vb-action');
    button.textContent = action;
    button.hidden = !action;
  }

  function meter(level) {
    const bars = document.querySelectorAll('#lm-voice-bar .lm-vb-meter i');
    const shape = [0.55, 0.8, 1, 0.8, 0.55];
    bars.forEach((b, i) => { b.style.transform = 'scaleY(' + Math.min(1, 0.15 + level * 14 * shape[i]).toFixed(2) + ')'; });
  }

  function onAction() {
    if (V.state === 'hearing') return finishUtterance();
    if (V.state === 'waiting' || V.state === 'speaking') {
      // You want the floor: stop talking, stop the answer, and listen.
      stopSpeaking();
      if (busy()) $('#lm-composer .stop-button').click();
      V.reply = null;
      return listen();
    }
    if (V.state === 'error') setState(V.on ? 'listening' : 'off');
  }

  // ---------------------------------------------------------------- switching on and off
  function unlockAudio() {
    // Phones only let a page play sound it started from a tap, so claim the audio element and the
    // audio context now, during the tap on the Voice chip. Later replies then play freely.
    if (!V.audio) V.audio = new Audio();
    V.audio.src = SILENT_WAV;
    V.audio.play().catch(() => {});
    const Ctx = window.AudioContext || window.webkitAudioContext;
    if (!V.ctx && Ctx) V.ctx = new Ctx();
    if (V.ctx && V.ctx.state === 'suspended') V.ctx.resume().catch(() => {});
  }

  function refuse(message) {
    // Tell the server too, so the chip goes back to off and replies aren't written for speech.
    V.on = false;
    shutdown();
    setState('error', message);
    const chip = $('#lm-chip-voice');
    if (chip && chip.classList.contains('lm-chip-on')) chip.click();
  }

  async function start() {
    if (!window.isSecureContext || !(navigator.mediaDevices && navigator.mediaDevices.getUserMedia)) {
      return refuse('The browser only allows the microphone over a secure connection. Use the https:// address LocalMind prints in LAN mode, or open it on this PC at localhost.');
    }
    setState('starting');
    fetch(api('warm'), { method: 'POST', headers: HEADERS, credentials: 'same-origin' })
      .then((r) => (r.ok ? null : r.json().then((j) => refuse(j.error || 'Voice is unavailable (' + r.status + ')'))))
      .catch(() => {});
    try {
      V.stream = await navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true, channelCount: 1 },
      });
    } catch (e) {
      return refuse(e && e.name === 'NotAllowedError'
        ? 'Microphone access was blocked. Allow it for this site in the browser settings, then turn Voice on again.'
        : 'No microphone is available (' + ((e && e.message) || e) + ').');
    }
    if (!V.on) return shutdown();
    const Ctx = window.AudioContext || window.webkitAudioContext;
    V.ctx = V.ctx || new Ctx();
    await V.ctx.resume().catch(() => {});
    const source = V.ctx.createMediaStreamSource(V.stream);
    V.analyser = V.ctx.createAnalyser();
    V.analyser.fftSize = 1024;
    V.samples = new Float32Array(V.analyser.fftSize);
    source.connect(V.analyser);
    if (!V.audio) V.audio = new Audio();
    clearInterval(V.timer);
    V.timer = setInterval(tick, TICK);
    // If a reply is already streaming in this chat, speak the rest of it rather than talk over it.
    if (busy()) { V.reply = { before: userRows() - 1, seen: true, said: 0, t0: Date.now(), done: false }; setState('waiting'); }
    else listen();
  }

  function shutdown() {
    V.gen++;
    clearInterval(V.timer);
    stopRecorder(true);
    stopSpeaking();
    if (V.stream) V.stream.getTracks().forEach((t) => t.stop()); // turns the browser's mic light off
    V.stream = null;
    V.analyser = null;
    V.reply = null;
    setState('off');
  }

  window.lmVoice = {
    set(on) {
      on = !!on;
      if (on === V.on) return;
      V.on = on;
      if (on) start(); else shutdown();
    },
    get state() { return V.state; },
  };

  // ---------------------------------------------------------------- listening
  function level() {
    if (!V.analyser) return 0;
    V.analyser.getFloatTimeDomainData(V.samples);
    let sum = 0;
    for (let i = 0; i < V.samples.length; i++) sum += V.samples[i] * V.samples[i];
    return Math.sqrt(sum / V.samples.length);
  }

  function startRecorder() {
    stopRecorder(true);
    const types = ['audio/webm;codecs=opus', 'audio/webm', 'audio/mp4', 'audio/ogg;codecs=opus'];
    const type = types.find((t) => window.MediaRecorder && MediaRecorder.isTypeSupported && MediaRecorder.isTypeSupported(t));
    // Each recording keeps its own chunks: a discarded one still delivers its last piece after
    // stop(), and that must not land in the next recording.
    const chunks = [];
    V.recorder = new MediaRecorder(V.stream, type ? { mimeType: type } : undefined);
    V.recorder.chunks = chunks;
    V.recorder.ondataavailable = (e) => { if (e.data && e.data.size) chunks.push(e.data); };
    V.recorder.start();
    V.listenStart = Date.now();
  }

  function stopRecorder(discard) {
    const recorder = V.recorder;
    V.recorder = null;
    if (!recorder || recorder.state === 'inactive') return Promise.resolve(null);
    return new Promise((resolve) => {
      recorder.onstop = () => resolve(discard ? null : new Blob(recorder.chunks, { type: recorder.mimeType || 'audio/webm' }));
      recorder.stop();
    });
  }

  function listen() {
    if (!V.on || !V.stream) return;
    V.heard = V.quiet = V.loud = 0;
    startRecorder();
    setState('listening');
  }

  function tick() {
    if (!V.on) return;
    if (V.state === 'listening' || V.state === 'hearing') {
      const rms = level();
      meter(rms);
      const threshold = Math.max(0.012, V.floor * 2.6);
      if (V.state === 'listening') {
        // Track the room's background level while nobody is talking.
        V.floor = V.floor * 0.97 + Math.min(rms, 0.05) * 0.03;
        V.loud = rms > threshold ? V.loud + TICK : 0;
        if (V.loud >= START_MS) { V.heard = V.loud; V.quiet = 0; setState('hearing'); }
        else if (Date.now() - V.listenStart > IDLE_RESTART_MS) startRecorder();
      } else {
        if (rms > threshold * 0.8) { V.heard += TICK; V.quiet = 0; } else V.quiet += TICK;
        if (V.quiet >= SILENCE_MS || Date.now() - V.listenStart > MAX_UTTERANCE_MS) finishUtterance();
      }
    }
    if (V.reply) followReply();
  }

  async function finishUtterance() {
    const enough = V.heard >= MIN_SPEECH_MS;
    setState('transcribing');
    const blob = await stopRecorder(!enough);
    if (!enough || !blob) return listen();
    const gen = V.gen;
    let text = '';
    try {
      const r = await fetch(api('transcribe'), {
        method: 'POST', headers: { ...HEADERS, 'content-type': blob.type }, body: blob, credentials: 'same-origin',
      });
      const data = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(r.status === 401 ? 'You were signed out. Reload the page and sign in again.' : data.error || 'error ' + r.status);
      text = (data.text || '').trim();
    } catch (e) {
      if (gen === V.gen) { setState('error', 'Transcription failed: ' + e.message); setTimeout(() => { if (V.state === 'error' && V.on) listen(); }, 3500); }
      return;
    }
    if (gen !== V.gen || !V.on) return;
    if (!text) return listen();
    send(text);
  }

  // ---------------------------------------------------------------- sending
  function userRows() { return document.querySelectorAll('#lm-chatbox .message-row.user-row').length; }

  function send(text) {
    const box = $('#lm-composer textarea');
    if (!box) return listen();
    // Set the value the way typing does, so the textbox's own state sees it.
    Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value').set.call(box, text);
    box.dispatchEvent(new Event('input', { bubbles: true }));
    expectReply();
    V.sending = true;
    setTimeout(() => {
      const submit = $('#lm-composer .submit-button');
      if (submit) submit.click(); else box.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
      V.sending = false;
    }, 80);
  }

  function expectReply() {
    stopRecorder(true);
    V.reply = { before: userRows(), seen: false, said: 0, t0: Date.now(), done: false };
    setState('waiting');
  }

  // A message typed (or a starter picked) while voice is on gets a spoken reply too.
  document.addEventListener('keydown', (e) => {
    if (V.on && !V.sending && e.key === 'Enter' && !e.shiftKey && e.target.closest && e.target.closest('#lm-composer')
        && (V.state === 'listening' || V.state === 'hearing')) expectReply();
  }, true);
  document.addEventListener('click', (e) => {
    const t = e.target.closest ? e.target : null;
    if (!t) return;
    if (t.closest('#lm-chip-voice')) unlockAudio();
    if (!V.on) return;
    if (!V.sending && t.closest('#lm-composer .submit-button, #lm-chatbox .examples button')
        && (V.state === 'listening' || V.state === 'hearing')) expectReply();
    if (t.closest('.lm-conv-row button, #lm-new-chat')) {
      // Another chat: its answer keeps going in the background, but stop reading it out.
      stopSpeaking();
      V.reply = null;
      setTimeout(() => { if (V.on) (busy() ? setState('listening') : listen()); }, 300);
    }
  }, true);

  // ---------------------------------------------------------------- speaking the reply
  const SKIP = 'pre, table, button, svg, img, style, script, .thought-group, .message-buttons, .icon-button-wrapper';
  const BLOCK = /^(P|LI|H[1-6]|DIV|BR|TR|BLOCKQUOTE|UL|OL)$/;

  function spokenText(node) {
    let out = '';
    (function walk(n) {
      if (n.nodeType === 3) { out += n.nodeValue; return; }
      if (n.nodeType !== 1 || n.matches(SKIP)) return;
      for (const child of n.childNodes) walk(child);
      if (BLOCK.test(n.tagName)) out += '\n';
    })(node);
    return out.replace(/[ \t ]+/g, ' ').replace(/ *\n[\s]*/g, '\n');
  }

  function currentReply() {
    // Everything the assistant wrote after your latest message, minus tool and thinking panels,
    // and whether it has used a tool yet (reasoning panels are the ones titled with a thought bubble).
    const rows = Array.from(document.querySelectorAll('#lm-chatbox .message-row'));
    let last = -1;
    rows.forEach((row, i) => { if (row.classList.contains('user-row')) last = i; });
    const mine = rows.slice(last + 1).filter((row) => row.classList.contains('bot-row'));
    const tools = mine.some((row) => {
      const title = row.querySelector('.thought-group .title');
      return !!title && !title.textContent.trim().startsWith('\u{1F4AD}');
    });
    const text = mine
      .filter((row) => !row.querySelector('.thought-group'))
      .map((row) => spokenText(row.querySelector('.message') || row))
      .join('\n');
    return { text, tools };
  }

  function nextChunk(text, final) {
    const reply = V.reply;
    // While streaming, the paragraph being written also ends in a line break (its closing tag),
    // which must not count as the end of a sentence.
    if (!final) text = text.replace(/\s+$/, '');
    if (text.length < reply.said) reply.said = text.length; // re-rendered shorter; don't skip ahead
    const rest = text.slice(reply.said);
    let cut = rest.length;
    if (!final) {
      // Only whole sentences while it's still streaming. The first goes out as soon as it's
      // complete so you hear something quickly; after that, a few sentences at a time.
      const boundary = /[.!?…:;](?=["')\]]*\s)|\n/g;
      cut = -1;
      let m;
      while ((m = boundary.exec(rest))) {
        cut = m.index + m[0].length;
        if ((reply.chunks || 0) === 0 ? cut >= 12 : cut >= 240) break;
      }
      if (cut < 0) return '';
    }
    reply.said += cut;
    reply.chunks = (reply.chunks || 0) + 1;
    return rest.slice(0, cut).trim();
  }

  function followReply() {
    const reply = V.reply;
    if (!reply.seen) {
      if (userRows() > reply.before) reply.seen = true;
      else if (Date.now() - reply.t0 > 15000) { V.reply = null; return listen(); } // never started
      else return;
    }
    if (reply.done) return;
    const final = !busy();
    const { text, tools } = currentReply();
    // An answer written before any tool ran may be a draft: the evidence check can send the model
    // off to search and replace it. Speak those only once the turn is over. An answer that follows
    // tool results is the real one, so it's read out as it streams.
    if (!final && !tools) return;
    let chunk;
    while ((chunk = nextChunk(text, final))) enqueue(chunk);
    if (final) {
      reply.done = true;
      if (!V.playing && !V.queue.length) afterSpeech();
    }
  }

  function enqueue(text) {
    if (!/\w/.test(text)) return;
    const request = fetch(api('speak'), {
      method: 'POST', headers: { ...HEADERS, 'content-type': 'application/json' },
      body: JSON.stringify({ text }), credentials: 'same-origin',
    }).then((r) => {
      if (r.status === 204) return null;
      if (!r.ok) return r.json().catch(() => ({})).then((j) => { throw new Error(j.error || 'error ' + r.status); });
      return r.blob();
    });
    request.catch(() => {}); // handled when its turn to play comes
    V.queue.push(request);
    pump();
  }

  async function pump() {
    if (V.playing) return;
    V.playing = true;
    const gen = V.gen;
    while (V.queue.length && gen === V.gen) {
      let blob = null;
      try { blob = await V.queue.shift(); } catch (e) { setState('error', 'Speech failed: ' + e.message); }
      if (!blob || gen !== V.gen) continue;
      setState('speaking');
      await play(blob);
    }
    // A loop from before an interruption must not touch the flag a newer loop now owns.
    if (gen !== V.gen) return;
    V.playing = false;
    afterSpeech();
  }

  function play(blob) {
    return new Promise((resolve) => {
      const audio = V.audio || (V.audio = new Audio());
      const url = URL.createObjectURL(blob);
      const done = () => {
        audio.onended = audio.onerror = null;
        V.stopAudio = null;
        URL.revokeObjectURL(url);
        resolve();
      };
      V.stopAudio = () => { audio.pause(); done(); };
      audio.onended = done;
      audio.onerror = done;
      audio.src = url;
      audio.play().catch(done);
    });
  }

  function stopSpeaking() {
    V.gen++;
    V.queue = [];
    V.playing = false;
    if (V.stopAudio) V.stopAudio();
  }

  function afterSpeech() {
    if (!V.on) return;
    if (V.reply && V.reply.done) { V.reply = null; return listen(); }
    if (V.reply) setState('waiting'); // spoke what's there so far; more is on its way
  }
