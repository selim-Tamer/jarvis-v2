const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const {SilenceDetector} = vm.runInNewContext(fs.readFileSync(path.join(__dirname,'voice_composer/silence.js'),'utf8')+'\nmodule.exports;', {module:{exports:{}}});
const source = fs.readFileSync(path.join(__dirname,'voice_composer/composer.js'),'utf8');

test('three seconds of silence stops only after speech; pauses restart the timer', () => {
 const detector = new SilenceDetector(0);
 assert.equal(detector.update(4000,0),null);
 assert.equal(detector.update(4100,.03),null);
 assert.equal(detector.update(7000,0),null);
 assert.equal(detector.update(7050,.04),null);
 assert.equal(detector.update(10049,0),null);
 assert.equal(detector.update(10050,0),'silence');
 assert.equal(new SilenceDetector(0).update(10000,0),'empty');
 assert.equal(new SilenceDetector(0).update(120000,.1),'limit');
});

function environment({denied = false} = {}) {
 const elements = Object.fromEntries(['mic','send','text','status','draft-actions','speech-actions','speech-status','discard','replay','stop'].map(id=>[id,{value:'',textContent:'',classList:{toggle(){}},setAttribute(){}}]));
 const posted = [], intervals = new Map(), listeners = {}, utterances = [];
 let now = 0, rms = .04, stopped = 0, spoken = 0;
 const synth = {cancel(){},speak(utterance){utterances.push(utterance);spoken++;utterance.onstart();}};
 const parent = {postMessage(message){posted.push(message);}};
 class MediaRecorder {
  static isTypeSupported(type){return type.startsWith('audio/webm');}
  constructor(){this.state='inactive';}
  start(){this.state='recording';}
  stop(){this.state='inactive';queueMicrotask(()=>{this.ondataavailable({data:new Blob(['fake recording'])});this.onstop();});}
 }
 const sandbox = {console,Blob,MediaRecorder,SilenceDetector,performance:{now:()=>now},crypto:{randomUUID:()=> 'event-'+posted.length},queueMicrotask,
  navigator:{mediaDevices:{getUserMedia:async()=>{if(denied)throw Object.assign(new Error('denied'),{name:'NotAllowedError'});return {getTracks:()=>[{stop(){stopped++;}}]};}}},
  document:{body:{scrollHeight:160},getElementById:id=>elements[id],addEventListener(){}},
  setInterval(callback){intervals.set(1,callback);return 1;},clearInterval(id){intervals.delete(id);},setTimeout(){return 2;},clearTimeout(){},
  FileReader:class {async readAsDataURL(blob){this.result='data:audio/webm;base64,'+Buffer.from(await blob.arrayBuffer()).toString('base64');this.onload();}},
  SpeechSynthesisUtterance:class {constructor(text){this.text=text;}},
  window:{parent,isSecureContext:true,MediaRecorder,speechSynthesis:synth,sessionStorage:new Map(),addEventListener(type,callback){listeners[type]=callback;},AudioContext:class {
    resume(){return Promise.resolve();}close(){return Promise.resolve();}createMediaStreamSource(){return {connect(){}};}
    createAnalyser(){return {fftSize:2048,getFloatTimeDomainData(samples){samples.fill(rms);}};}
  }}
 };
 sandbox.window.sessionStorage.getItem = sandbox.window.sessionStorage.get.bind(sandbox.window.sessionStorage);
 sandbox.window.sessionStorage.setItem = sandbox.window.sessionStorage.set.bind(sandbox.window.sessionStorage);
 // The speaker is loaded in this same browser-like context, as on the real page.
 vm.createContext(sandbox);
 vm.runInContext(fs.readFileSync(path.join(__dirname,'voice_composer/speech.js'),'utf8'),sandbox);
 vm.runInContext(source,sandbox);
 const render = args => listeners.message({source:parent,data:{type:'streamlit:render',args:{enabled:true,reset_token:0,...args}}});
 render({});
 return {elements,posted,utterances,render,remountSpeech(){vm.runInContext("new JarvisSpeaker(document.getElementById('speech-status')).play('Answer','reply-1',true)",sandbox);},async tick(time,level){now=time;rms=level;for(const fn of intervals.values())fn();await new Promise(setImmediate);},tracksStopped:()=>stopped,spoken:()=>spoken};
}

test('tap records, silence finishes, Send submits once without a review step',async()=>{
 const env=environment();await env.elements.mic.onclick();
 await env.tick(100,.03);await env.tick(3099,0);
 assert.equal(env.tracksStopped(),0);
 await env.tick(3100,0);
 assert.equal(env.tracksStopped(),1);
 assert.match(env.elements.status.textContent,/Recording ready/);
 assert.equal(env.posted.filter(e=>e.type==='streamlit:setComponentValue').length,0);
 await Promise.all([env.elements.send.onclick(),env.elements.send.onclick()]);
 const events=env.posted.filter(e=>e.type==='streamlit:setComponentValue');
 assert.equal(events.length,1);assert.equal(events[0].value.kind,'audio');
 env.render({ack_id:events[0].value.id,reply:'Spoken answer.',reply_id:'reply-1',autoplay:true});
 assert.equal(env.spoken(),1);
 env.remountSpeech();assert.equal(env.spoken(),1);
 assert.match(env.elements['speech-status'].textContent,/speaking/);
 env.render({ack_id:events[0].value.id,reply:'Spoken answer.',reply_id:'reply-1',autoplay:true});
 assert.equal(env.spoken(),1);
});

test('Send during recording finishes and sends the final clip once',async()=>{
 const env=environment();await env.elements.mic.onclick();
 await Promise.all([env.elements.send.onclick(),env.elements.send.onclick()]);
 assert.equal(env.tracksStopped(),1);
 assert.equal(env.posted.filter(e=>e.type==='streamlit:setComponentValue').length,1);
});

test('microphone off discards a clip and releases the hardware',async()=>{
 const env=environment();await env.elements.mic.onclick();
 env.render({enabled:false,reset_token:1});await new Promise(setImmediate);
 assert.equal(env.tracksStopped(),1);assert.equal(env.elements.mic.disabled,true);
 assert.equal(env.elements.send.disabled,true);
 assert.equal(env.posted.filter(e=>e.type==='streamlit:setComponentValue').length,0);
});

test('permission denial is visible and never sends audio',async()=>{
 const env=environment({denied:true});await env.elements.mic.onclick();
 assert.match(env.elements.status.textContent,/access was denied/);
 assert.equal(env.posted.filter(e=>e.type==='streamlit:setComponentValue').length,0);
 assert.equal(env.elements.mic.disabled,false);
});

test('speech errors offer Replay instead of claiming successful playback',()=>{
 const env=environment();env.render({reply:'Answer',reply_id:'reply-error',autoplay:true});
 env.utterances[0].onerror({error:'not-allowed'});
 assert.match(env.elements['speech-status'].textContent,/blocked.*Replay/);
 env.elements.replay.onclick();assert.equal(env.spoken(),2);
 env.elements.stop.onclick();assert.match(env.elements['speech-status'].textContent,/stopped/);
});
