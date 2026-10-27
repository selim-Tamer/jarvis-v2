const mic = document.getElementById('mic'), send = document.getElementById('send');
const text = document.getElementById('text'), status = document.getElementById('status');
const draftActions = document.getElementById('draft-actions'), speechActions = document.getElementById('speech-actions');
let args = {}, stream = null, recorder = null, context = null, interval = null;
let chunks = [], draft = null, detector = null, starting = false, busy = false, pendingId = '';
let stopPromise = null, resolveStop = null, discardOnStop = false;
let finishing = false;
let previousReset = null;
function post(type, extras = {}) { window.parent.postMessage({isStreamlitMessage:true,type,...extras}, '*'); }
function resize() { post('streamlit:setFrameHeight', {height:document.body.scrollHeight + 8}); }
const speaker = new JarvisSpeaker(document.getElementById('speech-status'), resize);
function notice(message, error = false) {status.textContent = message;status.classList.toggle('error',error);resize();}
function active() { return recorder && recorder.state !== 'inactive'; }
function refresh() {
  mic.disabled = !args.enabled || starting || busy || active() || finishing;
  mic.classList.toggle('recording', !!active());
  mic.setAttribute('aria-label', active() ? 'Recording voice message' : 'Record a voice message');
  send.disabled = busy || starting || (!active() && !draft && !text.value.trim());
  text.disabled = busy || starting || !!active() || !!draft;
  text.placeholder = draft ? 'Recording ready — press Send' : active() ? 'Listening… pause three seconds to finish' : 'Ask Jarvis…';
  draftActions.hidden = !draft || busy;
  speechActions.hidden = !args.reply;
  resize();
}
function release() {
  clearInterval(interval); interval = null;
  if (stream) stream.getTracks().forEach(track => track.stop());
  stream = null;
  if (context) context.close().catch(() => {});
  context = null;
}
function finish(discard = false) {
  discardOnStop = discard;
  if (finishing) return stopPromise;
  if (!active()) {if(discard) draft = null;release();refresh();return Promise.resolve();}
  finishing = true; recorder.stop(); release(); return stopPromise;
}
async function start() {
  if (!args.enabled || busy || active() || starting || finishing) return;
  const startReset = args.reset_token;
  speaker.stop(); draft = null; starting = true; refresh(); notice('Opening microphone…');
  try {
    if (!window.isSecureContext || !navigator.mediaDevices?.getUserMedia || !window.MediaRecorder)
      throw new Error('Recording needs localhost or HTTPS and a browser such as Edge or Chrome.');
    const obtained = await navigator.mediaDevices.getUserMedia({audio:{channelCount:1,echoCancellation:true,noiseSuppression:true}});
    if (!args.enabled || args.reset_token !== startReset) {obtained.getTracks().forEach(track => track.stop());return;}
    stream = obtained;
    context = new (window.AudioContext || window.webkitAudioContext)();
    await context.resume();
    const source = context.createMediaStreamSource(stream), analyser = context.createAnalyser();
    analyser.fftSize = 2048; source.connect(analyser);
    const samples = new Float32Array(analyser.fftSize);
    const mime = ['audio/webm;codecs=opus','audio/webm','audio/ogg;codecs=opus','audio/mp4'].find(type => MediaRecorder.isTypeSupported(type));
    if (!mime) throw new Error('No supported audio recording format. Try Edge or Chrome.');
    recorder = new MediaRecorder(stream, {mimeType:mime,audioBitsPerSecond:64000});
    chunks = []; discardOnStop = false;
    stopPromise = new Promise(resolve => {resolveStop = resolve;});
    recorder.ondataavailable = event => {if(event.data.size) chunks.push(event.data);};
    recorder.onerror = () => {finish(true);notice('Recording failed. Check microphone access and try again.',true);};
    recorder.onstop = () => {
      finishing = false;
      const clip = new Blob(chunks,{type:mime}); chunks = [];
      if (!discardOnStop && clip.size > 0 && clip.size <= 10*1024*1024) {
        draft = clip; notice('Recording ready. Press Send to send your message.');
      } else {draft = null; if(!discardOnStop) notice('Record a shorter message under 10 MB.',true);}
      refresh(); resolveStop?.();
    };
    detector = new SilenceDetector(performance.now());
    recorder.start(250);
    interval = setInterval(() => {
      analyser.getFloatTimeDomainData(samples);
      const rms = Math.sqrt(samples.reduce((sum, value) => sum+value*value,0)/samples.length);
      const reason = detector.update(performance.now(),rms);
      if (reason === 'empty') {finish(true).then(()=>notice('No speech detected. Tap the mic and speak again.',true));}
      else if (reason) finish();
    },100);
    notice('Listening… pause for three seconds to finish, or press Send now.');
  } catch(error) {
    release();notice(error.name === 'NotAllowedError' ? 'Microphone access was denied. Allow it in your browser, then tap the mic again.' : error.message,true);
  } finally {starting = false;refresh();}
}
async function submit() {
  if (busy || starting) return;
  busy = true; refresh();
  if (active()) await finish();
  const typed = text.value.trim();
  if (!draft && !typed) {busy = false;refresh();return;}
  refresh();speaker.stop();
  const id = crypto.randomUUID();pendingId = id;
  try {
    let event;
    if (draft) {
      const audio = await new Promise((resolve,reject) => {
        const reader = new FileReader(); reader.onload = () => resolve(reader.result.split(',')[1]);
        reader.onerror = reject;reader.readAsDataURL(draft);
      });
      event = {id,kind:'audio',audio,mime:draft.type};
    } else event = {id,kind:'text',text:typed};
    notice('Sending… Jarvis is preparing your reply.');
    post('streamlit:setComponentValue',{value:event,dataType:'json'});
  } catch(error) {busy = false;pendingId = '';refresh();notice('Could not prepare this recording. Please try again.',true);}
}
mic.onclick = start;send.onclick = submit;
text.oninput = refresh;
text.onkeydown = event => {if(event.key === 'Enter' && !event.shiftKey){event.preventDefault();submit();}};
document.getElementById('discard').onclick = () => {draft = null;refresh();notice('Recording discarded.');};
document.getElementById('replay').onclick = () => speaker.play(args.reply,args.reply_id,false);
document.getElementById('stop').onclick = () => speaker.stop();
document.addEventListener('keydown',event => {if(event.key === 'Escape') {speaker.stop();finish(true);notice('Recording and speech stopped.');}});
window.addEventListener('pagehide',() => {release();speaker.stop();});
window.addEventListener('message',event => {
  if (event.source !== window.parent || event.data?.type !== 'streamlit:render') return;
  args = event.data.args || {};
  if (previousReset !== null && previousReset !== args.reset_token) {
    finish(true);draft = null;speaker.stop();notice(args.enabled ? 'Tap the mic to record.' : 'Microphone off. Type a message below.');
  }
  previousReset = args.reset_token;
  if (!args.enabled && active()) finish(true);
  if (pendingId && args.ack_id === pendingId) {
    pendingId = '';busy = false;draft = null;text.value = '';notice('Message sent.');
  }
  refresh();
  if(args.reply && args.reply_id && args.autoplay) speaker.play(args.reply,args.reply_id,true);
});
post('streamlit:componentReady',{apiVersion:1});resize();refresh();
