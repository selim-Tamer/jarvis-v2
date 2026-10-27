// Pure timer logic, shared by the real recorder and its deterministic tests.
class SilenceDetector {
  constructor(start, silenceMs = 3000, noSpeechMs = 10000, maxMs = 120000) {
    this.start = start; this.lastVoice = start; this.heardVoice = false;
    this.silenceMs = silenceMs; this.noSpeechMs = noSpeechMs; this.maxMs = maxMs;
  }
  update(now, rms) {
    if (rms >= 0.015) { this.heardVoice = true; this.lastVoice = now; }
    if (now - this.start >= this.maxMs) return 'limit';
    if (!this.heardVoice && now - this.start >= this.noSpeechMs) return 'empty';
    if (this.heardVoice && now - this.lastVoice >= this.silenceMs) return 'silence';
    return null;
  }
}
if (typeof module !== 'undefined') module.exports = {SilenceDetector};
