import {useState, useRef, useEffect, useCallback, type FC, type KeyboardEvent} from "react";

type Role = "user" | "jarvis" | "system" | "tool" | "notification";
interface Message { id: number; role: Role; text: string; toolName?: string; streaming?: boolean; }
type StateName = "loading" | "listening" | "hearing" | "thinking" | "speaking" | "muted" | "error" | "textonly" | "confirming" | "stopped";
interface Status {
  state: StateName; detail: string; ready: boolean; busy: boolean; muted: boolean;
  confirming: boolean; voice_ready: boolean; wake_word: string; desktop: boolean; tray_ready: boolean;
}
const INITIAL: Status = {state:"loading", detail:"Connecting to Python assistant...", ready:false, busy:false, muted:false, confirming:false, voice_ready:false, wake_word:"jarvis", desktop:false, tray_ready:false};
const STATE_INFO: Record<StateName, {color:string; glow:string; label:string}> = {
  loading:{color:"#64748b",glow:"rgba(100,116,139,.3)",label:"Starting..."},
  listening:{color:"#38bdf8",glow:"rgba(56,189,248,.4)",label:"Listening for your wake word"},
  hearing:{color:"#4ade80",glow:"rgba(74,222,128,.5)",label:"Hearing you..."},
  thinking:{color:"#fbbf24",glow:"rgba(251,191,36,.4)",label:"Thinking..."},
  speaking:{color:"#8b8cf7",glow:"rgba(139,140,247,.4)",label:"Speaking..."},
  muted:{color:"#475569",glow:"rgba(71,85,105,.2)",label:"Microphone muted"},
  error:{color:"#f87171",glow:"rgba(248,113,113,.3)",label:"Problem"},
  textonly:{color:"#38bdf8",glow:"rgba(56,189,248,.3)",label:"Type below to talk"},
  confirming:{color:"#fbbf24",glow:"rgba(251,191,36,.4)",label:"Email: say yes or no"},
  stopped:{color:"#64748b",glow:"rgba(100,116,139,.2)",label:"Jarvis stopped"},
};

import {requestJson} from "./api";

const App: FC = () => {
  const [messages,setMessages] = useState<Message[]>([]);
  const [input,setInput] = useState("");
  const [status,setStatus] = useState<Status>(INITIAL);
  const [heard,setHeard] = useState("");
  const [connected,setConnected] = useState(false);
  const [connectionError,setConnectionError] = useState("");
  const [actionError,setActionError] = useState("");
  const [posting,setPosting] = useState(false);
  const chatRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const followRef = useRef(true);
  const stoppedRef = useRef(false);
  const sendingRef = useRef(false);
  const statusRef = useRef(status);
  statusRef.current = status;

  useEffect(() => {
    let disposed = false;
    let source: EventSource | null = null;
    let retry: ReturnType<typeof setTimeout> | undefined;
    const controller = new AbortController();
    const reconnect = () => {
      source?.close();
      if (disposed || stoppedRef.current) return;
      setConnected(false);
      setConnectionError("Disconnected from Python. Reconnecting... Check the launch.py console if this continues.");
      retry = setTimeout(connect,2000);
    };
    const connect = async () => {
      try {
        const health = await requestJson("/api/health", {signal:AbortSignal.any([controller.signal,AbortSignal.timeout(8000)])});
        if(health.app !== "jarvis-v2") throw new Error("Port 8000 is serving a different application.");
        if (disposed || stoppedRef.current) return;
        setStatus(health);
        source = new EventSource("/api/events");
        source.onopen = () => { if(!disposed) {setConnected(true);setConnectionError("");} };
        source.onmessage = (event) => {
          if(disposed) return;
          try {
            const data = JSON.parse(event.data);
            if(data.status) setStatus(data.status);
            if(typeof data.heard === "string") setHeard(data.heard);
            if(data.type === "snapshot") setMessages(data.messages);
            else if(data.type === "message") setMessages(m => [...m.slice(-199),data.message]);
            else if(data.type === "clear") {setMessages([]);setHeard("");followRef.current=true;}
            if(data.status?.state === "stopped") {
              setConnected(false);
              if(stoppedRef.current) source?.close();
              else reconnect();
            }
          } catch {setActionError("Received an invalid event from Python. Restart Jarvis.");}
        };
        source.onerror = reconnect;
      } catch { if(!disposed) reconnect(); }
    };
    connect();
    inputRef.current?.focus();
    return () => {disposed=true;controller.abort();source?.close();if(retry)clearTimeout(retry);};
  }, []);

  useEffect(() => {
    if(followRef.current && chatRef.current) chatRef.current.scrollTop=chatRef.current.scrollHeight;
  },[messages]);

  const control = useCallback(async (action:string) => {
    setActionError("");
    try {
      await requestJson("/api/control",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({action})});
      if(action === "quit") {
        stoppedRef.current=true;
        setConnected(false);
        setConnectionError("");
        setStatus(s => ({...s,state:"stopped",ready:false,detail:"Jarvis has stopped. You can close this window."}));
      }
    } catch(error) {setActionError(error instanceof Error ? error.message : "Control failed.");}
  },[]);
  const stopSpeaking = useCallback(() => {void control("interrupt");},[control]);
  useEffect(() => {
    const escape = (event:globalThis.KeyboardEvent) => {if(event.key === "Escape") {event.preventDefault();stopSpeaking();}};
    window.addEventListener("keydown",escape);
    return () => window.removeEventListener("keydown",escape);
  },[stopSpeaking]);

  const handleSend = useCallback(async () => {
    const text = input.trim();
    if(!text || sendingRef.current) return;
    sendingRef.current=true;
    setPosting(true);
    setActionError("");
    try {
      await requestJson("/api/chat",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({message:text})});
      setInput("");
      followRef.current=true;
      if(inputRef.current) inputRef.current.style.height="auto";
    } catch(error) {setActionError(error instanceof Error ? error.message : "Message could not be sent.");}
    finally {sendingRef.current=false;setPosting(false);inputRef.current?.focus();}
  },[input]);
  const handleKeyDown = (event:KeyboardEvent<HTMLTextAreaElement>) => {
    if(event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {event.preventDefault();void handleSend();}
  };
  const muted = status.muted;
  const isSpeaking = status.state === "speaking" || status.confirming;
  const isListening = status.voice_ready && !muted;
  const voiceSupported = true;
  const toggleMute = () => {void control(muted ? "unmute" : "mute");};
  const startListening = () => {void control("unmute");};
  const stopListening = () => {void control("mute");};
  const clearChat = async () => {
    setActionError("");
    try {await requestJson("/api/clear",{method:"POST"});}
    catch(error) {setActionError(error instanceof Error ? error.message : "Could not clear chat.");}
  };
  const state:StateName = connectionError && !stoppedRef.current ? "error" : status.state;
  const si = {...(STATE_INFO[state] ?? STATE_INFO.error),detail:connectionError || status.detail};
  return (
    <div className="app">
      {/* header */}
      <div className="header">
        <div>
          <h1>JARVIS</h1>
          <div className="sub">voice assistant</div>
        </div>
        <div className="spacer" />
        <button
          className={`icon-btn ${muted ? "active" : ""}`}
          onClick={toggleMute}
          disabled={!connected}
          title={muted ? "Unmute mic" : "Mute mic"}
        >
          {muted ? "🔇" : "🎙️"}
        </button>
        <button
          className="icon-btn"
          onClick={clearChat}
          disabled={!connected || status.busy}
          title="Clear chat"
        >
          🗑️
        </button>
      </div>

      {/* orb */}
      <div className="orb-section">
        <div className="orb-container">
          <div
            className="orb-glow"
            style={{ background: si.glow }}
          />
          {/* expanding rings when speaking/thinking */}
          {(state === "speaking" || state === "thinking" || state === "hearing") && (
            <>
              <div
                className="orb-ring"
                style={{
                  width: "100px",
                  height: "100px",
                  borderColor: si.color,
                  animationDelay: "0s",
                }}
              />
              <div
                className="orb-ring"
                style={{
                  width: "100px",
                  height: "100px",
                  borderColor: si.color,
                  animationDelay: "0.7s",
                }}
              />
            </>
          )}
          <div
            className="orb-core"
            style={{
              background: `radial-gradient(circle at 35% 30%, ${si.color}, ${si.color}88 60%, ${si.color}44)`,
              boxShadow: `0 0 40px ${si.glow}, inset 0 0 20px rgba(255,255,255,0.1)`,
              color: si.color,
            }}
          >
            <div className="orb-shimmer" />
            {state === "thinking" && (
              <div
                className="orbit-dot"
                style={{ background: si.color, boxShadow: `0 0 10px ${si.color}` }}
              />
            )}
            {state === "hearing" && (
              <div className="wave-bars" style={{ color: si.color }}>
                <span /><span /><span /><span /><span />
              </div>
            )}
          </div>
        </div>
      </div>

      {/* status bar */}
      <div className="status-bar">
        <div
          className="status-dot"
          style={{
            background: si.color,
            boxShadow: `0 0 8px ${si.glow}`,
          }}
        />
        <div className="status-text">
          <div className="status-caption" aria-live="polite">{state === "listening" ? `Say "${status.wake_word}"` : si.label}</div>
          <div className="status-detail">{si.detail}</div>
        </div>
      </div>

      {/* chat */}
      {actionError && <div className="error-banner" role="alert">{actionError}</div>}
      <div className="chat-container" ref={chatRef} role="log" aria-label="Conversation" onScroll={() => {const el=chatRef.current;if(el)followRef.current=el.scrollHeight-el.scrollTop-el.clientHeight<50;}}>
        {messages.length === 0 && (
          <div className="msg system">
            Say "{status.wake_word}" followed by your request, or type below. I can search the
            web, send emails, set reminders, open apps, and more.
          </div>
        )}
        {messages.map((msg) => (
          <MessageBubble key={msg.id} msg={msg} />
        ))}
      </div>

      {/* heard line */}
      <div className="heard-line">{heard}</div>

      {/* input */}
      <div className="input-area">
        <div className="input-row">
          {voiceSupported && (
            <button
              className={`mic-btn ${isListening ? "listening" : ""} ${muted ? "muted" : ""}`}
              onClick={isListening ? stopListening : startListening}
              disabled={!connected || !status.voice_ready}
              title={isListening ? "Mute microphone" : "Unmute microphone"} aria-label={isListening ? "Mute microphone" : "Unmute microphone"}
            >
              {isListening ? "⏹" : "🎙"}
            </button>
          )}
          <textarea
            ref={inputRef}
            className="text-input"
            aria-label="Message to Jarvis" placeholder={status.confirming ? "Say yes or no aloud; typing cannot confirm" : "Type a message…"}
            value={input}
            onChange={(e) => {
              setInput(e.target.value);
              // auto-resize
              e.target.style.height = "auto";
              e.target.style.height = Math.min(e.target.scrollHeight, 120) + "px";
            }}
            onKeyDown={handleKeyDown}
            rows={1}
          />
          {isSpeaking ? (
            <button className="stop-btn" onClick={stopSpeaking} title="Stop speaking">
              ⏹
            </button>
          ) : (
            <button
              className="send-btn"
              onClick={handleSend}
              disabled={!input.trim() || !connected || !status.ready || status.busy || posting}
              title="Send"
            >
              ➤
            </button>
          )}
        </div>
      </div>

      {/* bottom bar */}
      <div className="bottom-bar">
        <button onClick={toggleMute} disabled={!connected}>
          {muted ? "Unmute mic" : "Mute mic"}
        </button>
        <button onClick={clearChat} disabled={!connected || status.busy}>Clear chat</button>
        <button onClick={() => control("hide")} disabled={!connected || !status.tray_ready}>Hide to tray</button>
        <button className="danger" onClick={() => control("quit")} disabled={!connected}>
          Quit
        </button>
      </div>
    </div>
  );
};

// ---- message bubble ----
const MessageBubble: FC<{ msg: Message }> = ({ msg }) => {
  if (msg.role === "tool") {
    return (
      <div className="msg tool">
        <span className="tool-name">{msg.toolName}</span>: {msg.text}
      </div>
    );
  }
  if (msg.role === "system" || msg.role === "notification") {
    return <div className="msg system">{msg.text}</div>;
  }
  const label =
    msg.role === "user" ? "YOU" : msg.role === "jarvis" ? "JARVIS" : "";
  return (
    <div className={`msg ${msg.role}`}>
      {label && <div className="role-label">{label}</div>}
      {msg.streaming && !msg.text ? (
        <div className="typing-dots">
          <span /><span /><span />
        </div>
      ) : (
        msg.text
      )}
    </div>
  );
};

export default App;
