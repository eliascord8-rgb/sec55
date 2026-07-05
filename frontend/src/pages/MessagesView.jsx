import { useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import { Loader2, Search, Send, Phone, PhoneOff, Video, Mic, MicOff, Paperclip, Ban, X, Play, Pause, Flag, Check, CheckCheck } from "lucide-react";

// Format a UTC ISO date as Europe/Berlin time for last-seen display
const fmtLastSeen = (iso) => {
  if (!iso) return "never";
  try {
    const d = new Date(iso);
    const diffMin = (Date.now() - d.getTime()) / 60000;
    if (diffMin < 1) return "online now";
    if (diffMin < 60) return `${Math.floor(diffMin)} min ago`;
    return d.toLocaleString("en-GB", {
      timeZone: "Europe/Berlin",
      dateStyle: "medium",
      timeStyle: "short",
    });
  } catch {
    return "unknown";
  }
};

/**
 * MessagesView — 1-on-1 DMs between registered users + WebRTC voice/video calls.
 * Uses polling (2s) for message + call signal delivery.
 */
export default function MessagesView({ authedApi, me, onReadMessages }) {
  const [threads, setThreads] = useState([]);
  const [activeUser, setActiveUser] = useState(null); // {id, username}
  const [messages, setMessages] = useState([]);
  const [text, setText] = useState("");
  const [sending, setSending] = useState(false);
  const [searchQ, setSearchQ] = useState("");
  const [searchResults, setSearchResults] = useState([]);
  const [activeUserInfo, setActiveUserInfo] = useState(null); // full info with last_seen + i_blocked
  const [recording, setRecording] = useState(false);
  const recorderRef = useRef(null);
  const audioChunksRef = useRef([]);
  const fileInputRef = useRef(null);
  const chatEndRef = useRef(null);
  const [call, setCall] = useState(null); // {peerId, incoming, video, active, callId}
  const [callStats, setCallStats] = useState({ conn: "", ice: "", gather: "" }); // debug overlay
  const [peerTyping, setPeerTyping] = useState(false); // is the OTHER user typing to me
  const [reportOpen, setReportOpen] = useState(false);
  const [reportReason, setReportReason] = useState("");
  const [reportSubmitting, setReportSubmitting] = useState(false);
  const typingSentAtRef = useRef(0); // throttle outbound typing signals
  const pcRef = useRef(null);
  const localStreamRef = useRef(null);
  const remoteStreamRef = useRef(null);
  const isVideoCallRef = useRef(false); // stable across renders for ontrack callbacks
  const iceServersRef = useRef(null); // fetched from /api/calls/ice-config
  const remoteAudioRef = useRef(null);
  const localVideoRef = useRef(null);
  const remoteVideoRef = useRef(null);

  // Attach the remote stream to the playback elements whenever they mount.
  // Fixes "can't hear the other person" — pc.ontrack fires BEFORE the modal renders,
  // so we cache the stream and (re)attach when refs become available.
  const attachRemoteStream = () => {
    const s = remoteStreamRef.current;
    if (!s) return;
    const videoMode = isVideoCallRef.current;
    if (videoMode && remoteVideoRef.current && remoteVideoRef.current.srcObject !== s) {
      remoteVideoRef.current.srcObject = s;
      remoteVideoRef.current.play?.().catch(() => {});
    }
    // Always attach to the audio element too — the video element occasionally
    // fails to route audio through the default output on some browsers.
    if (!videoMode && remoteAudioRef.current && remoteAudioRef.current.srcObject !== s) {
      remoteAudioRef.current.srcObject = s;
      remoteAudioRef.current.play?.().catch(() => {});
    }
  };
  useEffect(() => { attachRemoteStream(); }, [call?.active, call?.video]);

  const loadThreads = async () => {
    try {
      const r = await authedApi().get("/messages/threads");
      setThreads(r.data.threads || []);
    } catch {}
  };

  useEffect(() => {
    loadThreads();
    const t = setInterval(loadThreads, 5000);
    return () => clearInterval(t);
  }, []);

  // Poll messages for active thread + call signals every 2s
  useEffect(() => {
    let running = true;
    let lastSince = "";
    const poll = async () => {
      // 1) call signals (always)
      try {
        const s = await authedApi().get("/calls/poll");
        for (const sig of s.data.signals || []) {
          await handleIncomingSignal(sig);
        }
      } catch {}
      // 2) active thread messages
      if (activeUser && running) {
        try {
          const path = lastSince ? `/messages/thread/${activeUser.id}?since=${encodeURIComponent(lastSince)}` : `/messages/thread/${activeUser.id}`;
          const r = await authedApi().get(path);
          if (r.data.messages?.length) {
            setMessages((m) => {
              const raw = lastSince ? [...m, ...r.data.messages] : r.data.messages;
              // De-duplicate by id — the /since delta can overlap with the initial load
              // and cause React "duplicate key" warnings otherwise. Later entries win,
              // so read-state updates on previously delivered messages take effect.
              const combined = Array.from(new Map(raw.map((x) => [x.id, x])).values());
              // Advance the cursor past BOTH created_at AND read_at so we don't
              // re-fetch the same read-flip forever.
              const latest = r.data.messages.reduce((acc, x) => {
                const ts = x.read_at && x.read_at > x.created_at ? x.read_at : x.created_at;
                return ts > acc ? ts : acc;
              }, lastSince || "");
              lastSince = latest || lastSince;
              return combined;
            });
            onReadMessages && onReadMessages();
          }
        } catch {}
      }
    };
    // Initial load full thread
    if (activeUser) {
      lastSince = "";
      setMessages([]);
      poll();
    }
    const t = setInterval(poll, 2000);
    return () => { running = false; clearInterval(t); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeUser?.id]);

  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const openUserByName = async (username) => {
    const uname = username.trim().toLowerCase();
    if (!uname) return;
    try {
      const r = await authedApi().get(`/messages/user/${uname}`);
      setActiveUser({ id: r.data.id, username: r.data.username });
      setSearchQ("");
      setSearchResults([]);
    } catch (e) {
      toast.error(e.response?.data?.detail || "User not found");
    }
  };

  const searchUsers = async (q) => {
    setSearchQ(q);
    if (q.trim().length < 1) {
      setSearchResults([]);
      return;
    }
    try {
      const r = await authedApi().get(`/messages/search?q=${encodeURIComponent(q)}`);
      setSearchResults(r.data.users || []);
    } catch {}
  };

  // Load full active user info (last seen, block state)
  useEffect(() => {
    if (!activeUser) { setActiveUserInfo(null); return; }
    authedApi()
      .get(`/messages/user/${activeUser.username}`)
      .then((r) => setActiveUserInfo(r.data))
      .catch(() => setActiveUserInfo(null));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeUser?.id]);

  const toggleBlock = async () => {
    if (!activeUserInfo) return;
    try {
      if (activeUserInfo.i_blocked) {
        await authedApi().post("/messages/unblock", { user_id: activeUserInfo.id });
        toast.success(`Unblocked @${activeUserInfo.username}`);
      } else {
        if (!window.confirm(`Block @${activeUserInfo.username}? They won't be able to message you.`)) return;
        await authedApi().post("/messages/block", { user_id: activeUserInfo.id });
        toast.success(`Blocked @${activeUserInfo.username}`);
      }
      const r = await authedApi().get(`/messages/user/${activeUserInfo.username}`);
      setActiveUserInfo(r.data);
    } catch (e) {
      toast.error(e.response?.data?.detail || "Failed");
    }
  };

  // Voice recorder — click to start, click again to stop & send
  const startRecording = async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      // Pick a mimeType this browser actually supports (Safari/iOS need mp4)
      const candidates = [
        "audio/webm;codecs=opus",
        "audio/webm",
        "audio/mp4",
        "audio/ogg;codecs=opus",
        "",
      ];
      let mimeType = "";
      for (const c of candidates) {
        if (!c) { mimeType = ""; break; }
        if (typeof MediaRecorder !== "undefined" && MediaRecorder.isTypeSupported && MediaRecorder.isTypeSupported(c)) {
          mimeType = c; break;
        }
      }
      const rec = mimeType ? new MediaRecorder(stream, { mimeType }) : new MediaRecorder(stream);
      audioChunksRef.current = [];
      rec.ondataavailable = (e) => { if (e.data && e.data.size > 0) audioChunksRef.current.push(e.data); };
      rec.onstop = async () => {
        stream.getTracks().forEach((t) => t.stop());
        if (audioChunksRef.current.length === 0) {
          toast.error("No audio captured — try again");
          return;
        }
        const type = rec.mimeType || "audio/webm";
        const ext = type.includes("mp4") ? "m4a" : type.includes("ogg") ? "ogg" : "webm";
        const blob = new Blob(audioChunksRef.current, { type });
        const file = new File([blob], `voice-${Date.now()}.${ext}`, { type });
        await uploadAndSend(file, "voice");
      };
      rec.onerror = (ev) => {
        toast.error("Recording error: " + (ev.error?.message || "unknown"));
      };
      rec.start();
      recorderRef.current = rec;
      setRecording(true);
    } catch (e) {
      const msg = e?.name === "NotAllowedError"
        ? "Microphone access denied — allow it in your browser settings."
        : e?.name === "NotFoundError"
        ? "No microphone found."
        : "Can't access microphone: " + (e?.message || "unknown");
      toast.error(msg);
      setRecording(false);
    }
  };

  const stopRecording = () => {
    try {
      if (recorderRef.current && recorderRef.current.state !== "inactive") {
        recorderRef.current.stop();
      }
    } catch (e) {
      toast.error("Failed to stop recording");
    }
    setRecording(false);
  };

  const toggleRecording = () => {
    if (recording) stopRecording();
    else startRecording();
  };

  const uploadAndSend = async (file, kind = "file") => {
    if (!activeUser) return;
    try {
      const fd = new FormData();
      fd.append("file", file);
      fd.append("kind", kind);
      const up = await authedApi().post("/messages/upload", fd, { headers: { "Content-Type": "multipart/form-data" } });
      const r = await authedApi().post("/messages/send", {
        to_id: activeUser.id,
        text: "",
        attachment_url: up.data.url,
        attachment_kind: up.data.kind,
        attachment_name: up.data.name,
        attachment_size: up.data.size,
      });
      setMessages((m) => [...m, r.data]);
      loadThreads();
    } catch (e) {
      toast.error(e.response?.data?.detail || "Upload failed");
    }
  };

  const onFilePick = (e) => {
    const f = e.target.files?.[0];
    if (!f) return;
    const kind = f.type.startsWith("image/") ? "image" : "file";
    uploadAndSend(f, kind);
    e.target.value = "";
  };

  const send = async (e) => {
    e.preventDefault();
    if (!text.trim() || !activeUser) return;
    setSending(true);
    try {
      const r = await authedApi().post("/messages/send", { to_id: activeUser.id, text: text.trim() });
      setMessages((m) => [...m, r.data]);
      setText("");
      // Stop the typing indicator on the other side
      authedApi().post("/messages/typing", { to_id: activeUser.id, typing: false }).catch(() => {});
      loadThreads();
    } catch (e) {
      toast.error(e.response?.data?.detail || "Failed to send");
    } finally {
      setSending(false);
    }
  };

  // ============ Typing indicator ============
  const onTextChange = (e) => {
    const v = e.target.value;
    setText(v);
    if (!activeUser) return;
    // Throttle to 1 signal every 2s
    const now = Date.now();
    if (v.trim().length > 0 && now - typingSentAtRef.current > 2000) {
      typingSentAtRef.current = now;
      authedApi().post("/messages/typing", { to_id: activeUser.id, typing: true }).catch(() => {});
    }
  };

  // Poll if the other user is typing (every 1.5s)
  useEffect(() => {
    if (!activeUser) { setPeerTyping(false); return; }
    let running = true;
    const check = async () => {
      try {
        const r = await authedApi().get(`/messages/typing/${activeUser.id}`);
        if (running) setPeerTyping(!!r.data.typing);
      } catch {}
    };
    check();
    const t = setInterval(check, 1500);
    return () => { running = false; clearInterval(t); setPeerTyping(false); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeUser?.id]);

  // ============ Report ============
  const submitReport = async () => {
    if (!activeUser) return;
    setReportSubmitting(true);
    try {
      await authedApi().post("/messages/report", { reported_user_id: activeUser.id, reason: reportReason });
      toast.success("Report submitted — an admin will review this chat.");
      setReportOpen(false);
      setReportReason("");
    } catch (e) {
      toast.error(e.response?.data?.detail || "Failed to send report");
    } finally {
      setReportSubmitting(false);
    }
  };

  // ============ WebRTC ============
  // ICE servers are fetched from the backend so an admin can override with a
  // private TURN provider (Twilio / Metered.ca / Xirsys) without a frontend rebuild.
  // Public OpenRelay + Google STUN are used as the fallback.
  const DEFAULT_RTC_CONFIG = {
    iceServers: [
      { urls: "stun:stun.l.google.com:19302" },
      { urls: "stun:stun1.l.google.com:19302" },
      { urls: "turn:openrelay.metered.ca:80", username: "openrelayproject", credential: "openrelayproject" },
      { urls: "turn:openrelay.metered.ca:443", username: "openrelayproject", credential: "openrelayproject" },
      { urls: "turn:openrelay.metered.ca:443?transport=tcp", username: "openrelayproject", credential: "openrelayproject" },
    ],
    iceCandidatePoolSize: 4,
  };

  const getRtcConfig = async () => {
    if (iceServersRef.current) return { iceServers: iceServersRef.current, iceCandidatePoolSize: 4 };
    try {
      const r = await authedApi().get("/calls/ice-config");
      if (r.data?.iceServers?.length) {
        iceServersRef.current = r.data.iceServers;
        return { iceServers: r.data.iceServers, iceCandidatePoolSize: 4 };
      }
    } catch {}
    return DEFAULT_RTC_CONFIG;
  };

  // Attach the LOCAL preview stream when the <video> mounts. Without this,
  // the ref could still be null when startCall/acceptCall assigns srcObject,
  // leaving the user staring at a black tile.
  useEffect(() => {
    if (call?.video && localVideoRef.current && localStreamRef.current && localVideoRef.current.srcObject !== localStreamRef.current) {
      localVideoRef.current.srcObject = localStreamRef.current;
      localVideoRef.current.play?.().catch(() => {});
    }
  }, [call?.video, call?.active, call?.incoming]);

  const startCall = async (video = false) => {
    if (!activeUser) return toast.error("Open a chat first");
    const callId = crypto.randomUUID();
    isVideoCallRef.current = !!video;
    setCallStats({ conn: "", ice: "", gather: "" });
    setCall({ peerId: activeUser.id, incoming: false, video, active: false, callId });
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true, video });
      localStreamRef.current = stream;
      if (video && localVideoRef.current) localVideoRef.current.srcObject = stream;
      const rtcConfig = await getRtcConfig();
      const pc = new RTCPeerConnection(rtcConfig);
      pcRef.current = pc;
      pc.onconnectionstatechange = () => { console.log("[call] connectionState:", pc.connectionState); setCallStats((s) => ({ ...s, conn: pc.connectionState })); };
      pc.oniceconnectionstatechange = () => { console.log("[call] iceConnectionState:", pc.iceConnectionState); setCallStats((s) => ({ ...s, ice: pc.iceConnectionState })); };
      pc.onicegatheringstatechange = () => { console.log("[call] iceGatheringState:", pc.iceGatheringState); setCallStats((s) => ({ ...s, gather: pc.iceGatheringState })); };
      stream.getTracks().forEach((t) => pc.addTrack(t, stream));
      pc.ontrack = (ev) => {
        console.log("[call] ontrack fired — tracks:", ev.streams[0]?.getTracks().map(t=>t.kind));
        // Cache the remote stream — refs may not exist yet.
        remoteStreamRef.current = ev.streams[0];
        attachRemoteStream();
      };
      pc.onicecandidate = (ev) => {
        if (ev.candidate) sendSignal(callId, activeUser.id, "ice", { candidate: ev.candidate });
      };
      // Ring first
      await sendSignal(callId, activeUser.id, "ring", { video });
      const offer = await pc.createOffer();
      await pc.setLocalDescription(offer);
      await sendSignal(callId, activeUser.id, "offer", { sdp: offer });
      setCall((c) => ({ ...c, active: true }));
    } catch (e) {
      toast.error("Can't access mic/cam: " + e.message);
      endCall();
    }
  };

  const acceptCall = async () => {
    if (!call || !call.incoming) return;
    isVideoCallRef.current = !!call.video;
    setCallStats({ conn: "", ice: "", gather: "" });
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true, video: call.video });
      localStreamRef.current = stream;
      if (call.video && localVideoRef.current) localVideoRef.current.srcObject = stream;
      const rtcConfig = await getRtcConfig();
      const pc = new RTCPeerConnection(rtcConfig);
      pcRef.current = pc;
      pc.onconnectionstatechange = () => { console.log("[call] connectionState:", pc.connectionState); setCallStats((s) => ({ ...s, conn: pc.connectionState })); };
      pc.oniceconnectionstatechange = () => { console.log("[call] iceConnectionState:", pc.iceConnectionState); setCallStats((s) => ({ ...s, ice: pc.iceConnectionState })); };
      pc.onicegatheringstatechange = () => { console.log("[call] iceGatheringState:", pc.iceGatheringState); setCallStats((s) => ({ ...s, gather: pc.iceGatheringState })); };
      pc.onconnectionstatechange = () => console.log("[call] connectionState:", pc.connectionState);
      pc.oniceconnectionstatechange = () => console.log("[call] iceConnectionState:", pc.iceConnectionState);
      pc.onicegatheringstatechange = () => console.log("[call] iceGatheringState:", pc.iceGatheringState);
      stream.getTracks().forEach((t) => pc.addTrack(t, stream));
      pc.ontrack = (ev) => {
        console.log("[call] ontrack fired — tracks:", ev.streams[0]?.getTracks().map(t=>t.kind));
        remoteStreamRef.current = ev.streams[0];
        attachRemoteStream();
      };
      pc.onicecandidate = (ev) => {
        if (ev.candidate) sendSignal(call.callId, call.peerId, "ice", { candidate: ev.candidate });
      };
      // Attach saved offer
      if (call.pendingOffer) {
        await pc.setRemoteDescription(new RTCSessionDescription(call.pendingOffer));
        const answer = await pc.createAnswer();
        await pc.setLocalDescription(answer);
        await sendSignal(call.callId, call.peerId, "answer", { sdp: answer });
      }
      // Apply queued ICE
      if (call.pendingIce) {
        for (const cand of call.pendingIce) {
          try { await pc.addIceCandidate(new RTCIceCandidate(cand)); } catch {}
        }
      }
      setCall((c) => ({ ...c, active: true, incoming: false }));
    } catch (e) {
      toast.error("Can't join call: " + e.message);
      endCall();
    }
  };

  const endCall = () => {
    if (call?.peerId && call?.callId) {
      sendSignal(call.callId, call.peerId, "end").catch(() => {});
    }
    try { pcRef.current?.close(); } catch {}
    localStreamRef.current?.getTracks().forEach((t) => t.stop());
    pcRef.current = null;
    localStreamRef.current = null;
    remoteStreamRef.current = null;
    isVideoCallRef.current = false;
    setCall(null);
  };

  const sendSignal = (callId, toId, kind, payload) =>
    authedApi().post("/calls/signal", { call_id: callId, to_id: toId, kind, payload });

  const handleIncomingSignal = async (sig) => {
    const { call_id, from_id, from_username, kind, payload } = sig;
    if (kind === "ring") {
      // Show incoming call UI
      isVideoCallRef.current = !!payload?.video;
      setCall({
        peerId: from_id,
        peerName: from_username,
        incoming: true,
        video: payload?.video || false,
        active: false,
        callId: call_id,
        pendingIce: [],
      });
    } else if (kind === "offer") {
      // Store SDP for accept. If ring state hasn't been committed yet, upsert a call
      // record so the offer isn't lost.
      setCall((c) => {
        if (c && c.callId === call_id) return { ...c, pendingOffer: payload?.sdp };
        // Ring signal likely still in-flight — seed the incoming call now.
        return {
          peerId: from_id,
          peerName: from_username,
          incoming: true,
          video: false,
          active: false,
          callId: call_id,
          pendingIce: [],
          pendingOffer: payload?.sdp,
        };
      });
    } else if (kind === "answer" && pcRef.current) {
      await pcRef.current.setRemoteDescription(new RTCSessionDescription(payload.sdp));
      // Flush any ICE candidates that arrived before the answer
      setCall((c) => {
        if (!c) return c;
        (c.pendingIce || []).forEach(async (cand) => {
          try { await pcRef.current.addIceCandidate(new RTCIceCandidate(cand)); } catch {}
        });
        return { ...c, pendingIce: [] };
      });
    } else if (kind === "ice") {
      if (pcRef.current && pcRef.current.remoteDescription) {
        try { await pcRef.current.addIceCandidate(new RTCIceCandidate(payload.candidate)); } catch {}
      } else {
        // Queue ICE until we set remote description
        setCall((c) => (c ? { ...c, pendingIce: [...(c.pendingIce || []), payload.candidate] } : c));
      }
    } else if (kind === "end") {
      endCall();
    }
  };

  return (
    <div className="space-y-4">
      <div>
        <h1 className="font-display text-3xl md:text-4xl font-black tracking-tight">Messages</h1>
        <p className="text-white/50 text-sm mt-2">Chat and call other Better Social members. Enter their username to open the chat instantly.</p>
      </div>

      {/* Search bar */}
      <div className="relative">
        <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-white/40" />
        <input
          data-testid="messages-user-search"
          type="text"
          value={searchQ}
          onChange={(e) => searchUsers(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && openUserByName(searchQ)}
          placeholder="Enter the exact username to open their chat (privacy: partial names are hidden)"
          className="w-full bg-[#13091a] border border-white/10 rounded-md pl-10 pr-4 py-3 text-sm outline-none focus:border-[#3b82f6]"
        />
        {searchResults.length > 0 && (
          <div className="absolute top-full left-0 right-0 mt-1 bg-[#1a1525] border border-white/10 rounded-md shadow-2xl z-10 max-h-72 overflow-y-auto">
            {searchResults.map((u) => (
              <button
                key={u.id}
                onClick={() => { setActiveUser(u); setSearchQ(""); setSearchResults([]); }}
                data-testid={`search-user-${u.username}`}
                className="w-full text-left px-4 py-2.5 hover:bg-white/5 text-sm flex items-center gap-3 border-b border-white/5 last:border-0"
              >
                <div className="w-8 h-8 rounded-full bg-[#3b82f6] flex items-center justify-center text-xs font-bold">{u.username.slice(0,2).toUpperCase()}</div>
                <span className="font-medium">{u.username}</span>
                <span className="ml-auto text-[10px] uppercase text-white/40">{u.role}</span>
              </button>
            ))}
          </div>
        )}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-[280px_1fr] gap-4">
        {/* Thread list */}
        <div className="bg-[#0d0a14] border border-white/5 rounded-lg overflow-hidden">
          <div className="px-4 py-3 border-b border-white/5 text-[10px] uppercase tracking-wider text-white/40 font-bold">Recent</div>
          <div className="max-h-[500px] overflow-y-auto">
            {threads.length === 0 && <div className="p-6 text-center text-xs text-white/40">No conversations yet.<br/>Search a username above.</div>}
            {threads.map((t) => (
              <button
                key={t.other_id}
                onClick={() => setActiveUser({ id: t.other_id, username: t.other_username })}
                data-testid={`thread-${t.other_username}`}
                className={`w-full text-left px-4 py-3 flex items-start gap-3 hover:bg-white/5 transition border-b border-white/5 ${activeUser?.id === t.other_id ? "bg-[#3b82f6]/10" : ""}`}
              >
                <div className="w-9 h-9 rounded-full bg-gradient-to-br from-[#3b82f6] to-[#7c3aed] flex items-center justify-center text-xs font-bold shrink-0">{t.other_username.slice(0,2).toUpperCase()}</div>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center justify-between">
                    <div className="font-bold text-sm truncate">{t.other_username}</div>
                    {t.unread > 0 && <span className="w-5 h-5 rounded-full bg-red-500 text-white text-[10px] flex items-center justify-center font-bold">{t.unread}</span>}
                  </div>
                  <div className="text-[11px] text-white/50 truncate">{t.last_from_me && "You: "}{t.last_text}</div>
                </div>
              </button>
            ))}
          </div>
        </div>

        {/* Chat area */}
        <div className="bg-[#0d0a14] border border-white/5 rounded-lg flex flex-col h-[500px]">
          {!activeUser ? (
            <div className="flex-1 flex items-center justify-center text-white/40 text-sm">
              Select a conversation or search a username to start chatting.
            </div>
          ) : (
            <>
              <div className="px-4 py-3 border-b border-white/5 flex items-center gap-3">
                <div className="w-9 h-9 rounded-full bg-gradient-to-br from-[#3b82f6] to-[#7c3aed] flex items-center justify-center text-xs font-bold">{activeUser.username.slice(0,2).toUpperCase()}</div>
                <div className="flex-1">
                  <div className="font-bold text-sm">@{activeUser.username}</div>
                  <div className="text-[10px] uppercase tracking-wider text-white/50" data-testid="last-seen">
                    Last seen · {fmtLastSeen(activeUserInfo?.last_seen)}
                  </div>
                </div>
                <button onClick={() => startCall(false)} data-testid="call-audio-btn" className="w-9 h-9 rounded-md hover:bg-emerald-500/20 flex items-center justify-center text-emerald-400" title="Voice call">
                  <Phone className="w-4 h-4" />
                </button>
                <button onClick={() => startCall(true)} data-testid="call-video-btn" className="w-9 h-9 rounded-md hover:bg-blue-500/20 flex items-center justify-center text-blue-400" title="Video call">
                  <Video className="w-4 h-4" />
                </button>
                <button onClick={toggleBlock} data-testid="block-btn" className={`w-9 h-9 rounded-md flex items-center justify-center ${activeUserInfo?.i_blocked ? "bg-red-500/20 text-red-400" : "hover:bg-red-500/20 text-white/50"}`} title={activeUserInfo?.i_blocked ? "Unblock user" : "Block user"}>
                  <Ban className="w-4 h-4" />
                </button>
                <button onClick={() => setReportOpen(true)} data-testid="report-btn" className="w-9 h-9 rounded-md hover:bg-amber-500/20 flex items-center justify-center text-amber-400" title="Report this chat to admins">
                  <Flag className="w-4 h-4" />
                </button>
              </div>
              <div className="flex-1 overflow-y-auto p-4 space-y-2">
                {messages.length === 0 && <div className="text-center text-white/30 text-xs py-8">Start the conversation…</div>}
                {messages.map((m) => (
                  <div key={m.id} className={`flex ${m.from_id === me.id ? "justify-end" : "justify-start"}`}>
                    <div className={`max-w-[70%] px-3 py-2 rounded-lg text-sm ${m.from_id === me.id ? "bg-[#3b82f6] text-white" : "bg-white/10 text-white"}`}>
                      {m.attachment_url && m.attachment_kind === "voice" && (
                        <audio src={m.attachment_url} controls preload="metadata" className="max-w-[240px] mb-1" data-testid="voice-msg" />
                      )}
                      {m.attachment_url && m.attachment_kind === "image" && (
                        <a href={m.attachment_url} target="_blank" rel="noreferrer"><img src={m.attachment_url} alt={m.attachment_name} className="max-w-full rounded-md" /></a>
                      )}
                      {m.attachment_url && m.attachment_kind === "file" && (
                        <a href={m.attachment_url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-2 underline">
                          <Paperclip className="w-3 h-3" /> {m.attachment_name}
                        </a>
                      )}
                      {m.text && <div>{m.text}</div>}
                      <div className="text-[9px] opacity-60 mt-0.5 flex items-center gap-1 justify-end">
                        <span>{new Date(m.created_at).toLocaleTimeString("en-GB", {hour:'2-digit', minute:'2-digit', timeZone:'Europe/Berlin'})}</span>
                        {m.from_id === me.id && (
                          m.read
                            ? <CheckCheck className="w-3 h-3 text-sky-300" title="Read" data-testid="msg-read" />
                            : <Check className="w-3 h-3 text-white/60" title="Sent" data-testid="msg-sent" />
                        )}
                      </div>
                    </div>
                  </div>
                ))}
                {peerTyping && (
                  <div className="flex justify-start" data-testid="typing-indicator">
                    <div className="bg-white/10 text-white rounded-full px-4 py-2.5 inline-flex items-center gap-1">
                      <span className="w-1.5 h-1.5 rounded-full bg-white/70 animate-bounce" style={{ animationDelay: "0ms" }} />
                      <span className="w-1.5 h-1.5 rounded-full bg-white/70 animate-bounce" style={{ animationDelay: "150ms" }} />
                      <span className="w-1.5 h-1.5 rounded-full bg-white/70 animate-bounce" style={{ animationDelay: "300ms" }} />
                    </div>
                  </div>
                )}
                <div ref={chatEndRef} />
              </div>
              <form onSubmit={send} className="border-t border-white/5 p-3 flex gap-2 items-center">
                <input type="file" ref={fileInputRef} onChange={onFilePick} className="hidden" data-testid="file-input" />
                <button type="button" onClick={() => fileInputRef.current?.click()} data-testid="attach-btn" className="w-9 h-9 rounded-md hover:bg-white/10 flex items-center justify-center text-white/60" title="Attach file">
                  <Paperclip className="w-4 h-4" />
                </button>
                <button type="button" onClick={toggleRecording} data-testid="voice-btn" className={`w-9 h-9 rounded-md flex items-center justify-center ${recording ? "bg-red-500 text-white animate-pulse" : "hover:bg-white/10 text-white/60"}`} title={recording ? "Click to stop & send" : "Click to record voice message"}>
                  {recording ? <MicOff className="w-4 h-4" /> : <Mic className="w-4 h-4" />}
                </button>
                <input
                  data-testid="dm-input"
                  value={text}
                  onChange={onTextChange}
                  placeholder={recording ? "🔴 Recording… click mic again to send" : "Type a message…"}
                  disabled={recording}
                  className="flex-1 bg-[#1a1525] border border-white/10 rounded-md px-3 py-2 text-sm outline-none focus:border-[#3b82f6]"
                />
                <button type="submit" disabled={sending || !text.trim()} data-testid="dm-send" className="px-4 bg-[#3b82f6] hover:bg-[#2563eb] rounded-md disabled:opacity-40 inline-flex items-center">
                  {sending ? <Loader2 className="w-4 h-4 animate-spin" /> : <Send className="w-4 h-4" />}
                </button>
              </form>
            </>
          )}
        </div>
      </div>

      <audio ref={remoteAudioRef} autoPlay style={{ display: "none" }} />

      {/* Call modal */}
      {call && (
        <div className="fixed inset-0 z-[90] bg-black/90 backdrop-blur-md flex items-center justify-center p-4">
          <div className="bg-[#0d0a14] border border-white/10 rounded-2xl p-6 max-w-md w-full text-center shadow-2xl">
            <div className="w-20 h-20 rounded-full bg-gradient-to-br from-[#3b82f6] to-[#7c3aed] mx-auto flex items-center justify-center text-2xl font-black animate-pulse">
              {(call.peerName || activeUser?.username || "?").slice(0,2).toUpperCase()}
            </div>
            <h3 className="font-display font-black text-xl mt-4">
              {call.incoming ? "Incoming call" : call.active ? "In call" : "Calling…"}
            </h3>
            <div className="text-sm text-white/60 mt-1">@{call.peerName || activeUser?.username}</div>
            {(callStats.conn || callStats.ice || callStats.gather) && (
              <div className="mt-3 mx-auto text-[10px] font-mono text-white/50 bg-white/5 rounded-md px-3 py-1.5 inline-flex gap-3" data-testid="call-debug-overlay">
                <span>conn:{callStats.conn || "–"}</span>
                <span>ice:{callStats.ice || "–"}</span>
                <span>gather:{callStats.gather || "–"}</span>
              </div>
            )}
            {call.video && (
              <div className="grid grid-cols-2 gap-2 mt-4">
                <video ref={remoteVideoRef} autoPlay playsInline className="w-full aspect-video bg-black rounded-md" />
                <video ref={localVideoRef} autoPlay playsInline muted className="w-full aspect-video bg-black rounded-md" />
              </div>
            )}
            <div className="flex gap-3 justify-center mt-6">
              {call.incoming && !call.active && (
                <button onClick={acceptCall} data-testid="accept-call-btn" className="px-6 py-3 rounded-full bg-emerald-500 text-black font-bold uppercase text-xs tracking-wider inline-flex items-center gap-2 hover:bg-emerald-400">
                  <Phone className="w-4 h-4" /> Accept
                </button>
              )}
              <button onClick={endCall} data-testid="end-call-btn" className="px-6 py-3 rounded-full bg-red-500 text-white font-bold uppercase text-xs tracking-wider inline-flex items-center gap-2 hover:bg-red-400">
                <PhoneOff className="w-4 h-4" /> {call.active ? "Hang up" : call.incoming ? "Decline" : "Cancel"}
              </button>
            </div>
          </div>
        </div>
      )}
      {/* Report dialog */}
      {reportOpen && (
        <div className="fixed inset-0 z-[95] bg-black/80 backdrop-blur-sm flex items-center justify-center p-4" onClick={() => setReportOpen(false)}>
          <div className="bg-[#0d0a14] border border-white/10 rounded-2xl p-6 max-w-md w-full shadow-2xl" onClick={(e) => e.stopPropagation()} data-testid="report-dialog">
            <div className="flex items-center gap-3 mb-3">
              <div className="w-10 h-10 rounded-full bg-amber-500/20 flex items-center justify-center text-amber-400">
                <Flag className="w-5 h-5" />
              </div>
              <div>
                <h3 className="font-display font-black text-lg">Report chat with @{activeUser?.username}</h3>
                <p className="text-xs text-white/50">An admin will be able to review your conversation with this user.</p>
              </div>
            </div>
            <textarea
              data-testid="report-reason"
              value={reportReason}
              onChange={(e) => setReportReason(e.target.value)}
              placeholder="What happened? (harassment, scam, spam, other — optional but helpful)"
              className="w-full bg-[#1a1525] border border-white/10 rounded-md px-3 py-2 text-sm outline-none focus:border-amber-500 min-h-[100px] resize-y"
              maxLength={1000}
            />
            <div className="flex gap-2 justify-end mt-4">
              <button onClick={() => { setReportOpen(false); setReportReason(""); }} data-testid="report-cancel" className="px-4 py-2 rounded-md hover:bg-white/5 text-sm text-white/70">Cancel</button>
              <button onClick={submitReport} disabled={reportSubmitting} data-testid="report-submit" className="px-4 py-2 rounded-md bg-amber-500 hover:bg-amber-400 text-black font-bold text-sm inline-flex items-center gap-2 disabled:opacity-50">
                {reportSubmitting ? <Loader2 className="w-4 h-4 animate-spin" /> : <Flag className="w-4 h-4" />}
                Submit report
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
