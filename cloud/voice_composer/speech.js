class JarvisSpeaker {
  constructor(status, onActivity = () => {}) {
    this.status = status; this.onActivity = onActivity; this.lastAttempt = '';
    this.current = null; this.timer = null; this.generation = 0;
  }
  stop() {
    this.generation++; clearTimeout(this.timer);
    if ('speechSynthesis' in window) window.speechSynthesis.cancel();
    this.current = null; this.status.textContent = 'Speech stopped.'; this.onActivity();
  }
  play(text, id, automatic = false) {
    if (automatic && id === this.lastAttempt) return;
    if (automatic) {
      try {
        const key = 'jarvis-spoken-' + id;
        if (window.sessionStorage.getItem(key)) return;
        window.sessionStorage.setItem(key, 'attempted');
      } catch (_) { /* Private browsing can deny session storage; the in-frame guard still works. */ }
    }
    this.lastAttempt = id;
    if (!('speechSynthesis' in window)) {
      this.status.textContent = 'Speech is unavailable in this browser. Open the voice reply transcript.';
      this.onActivity(); return;
    }
    this.stop(); const generation = this.generation;
    const chunks = text.match(/[\s\S]{1,220}(?:\s|$)|[\s\S]{1,220}/g) || [];
    let index = 0;
    const next = () => {
      if (generation !== this.generation) return;
      if (index >= chunks.length) {this.status.textContent = 'Reply finished.'; this.onActivity(); return;}
      const utterance = new SpeechSynthesisUtterance(chunks[index++]);
      this.current = utterance; // Keep the utterance alive until its end event.
      utterance.onstart = () => {
        if (generation !== this.generation) return;
        clearTimeout(this.timer); this.status.textContent = 'Jarvis is speaking…'; this.onActivity();
      };
      utterance.onend = next;
      utterance.onerror = event => {
        if (generation !== this.generation) return;
        clearTimeout(this.timer);
        this.status.textContent = event.error === 'not-allowed'
          ? 'Playback was blocked. Press Replay reply to hear Jarvis.'
          : 'Speech could not play. Press Replay reply or open the transcript.';
        this.onActivity();
      };
      this.status.textContent = 'Starting spoken reply…';
      this.timer = setTimeout(() => {
        if (generation === this.generation) {
          this.status.textContent = 'No speech started. Press Replay reply to hear Jarvis.';
          this.onActivity();
        }
      }, 7000);
      window.speechSynthesis.speak(utterance);
    };
    next(); this.onActivity();
  }
}
if (typeof module !== 'undefined') module.exports = {JarvisSpeaker};
