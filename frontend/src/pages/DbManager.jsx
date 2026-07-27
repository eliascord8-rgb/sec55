import { useState, useEffect, useCallback } from "react";
import { api, adminApi } from "@/lib/api";
import { toast } from "sonner";
import { Loader2, Database, Trash2, Pencil, Plus, RefreshCw, Search, LogOut, ChevronLeft, ChevronRight } from "lucide-react";

export default function DbManager() {
  const [token, setToken] = useState(localStorage.getItem("bs_admin_token") || "");
  const [authed, setAuthed] = useState(false);
  const [checking, setChecking] = useState(true);
  const [u, setU] = useState("");
  const [p, setP] = useState("");
  const [loggingIn, setLoggingIn] = useState(false);
  const [captcha, setCaptcha] = useState(null); // {id, question}
  const [capAnswer, setCapAnswer] = useState("");

  const loadCaptcha = async () => {
    try {
      const r = await api.get("/auth/captcha");
      setCaptcha(r.data);
      setCapAnswer("");
    } catch { /* silent */ }
  };

  const [collections, setCollections] = useState([]);
  const [selected, setSelected] = useState("");
  const [docs, setDocs] = useState([]);
  const [total, setTotal] = useState(0);
  const [skip, setSkip] = useState(0);
  const [q, setQ] = useState("");
  const [loading, setLoading] = useState(false);
  const [editDoc, setEditDoc] = useState(null); // {id, json, isNew}
  const [saving, setSaving] = useState(false);
  const LIMIT = 25;

  const loadCollections = useCallback(async (tok) => {
    const r = await adminApi(tok || token).get("/dbadmin/collections");
    setCollections(r.data.collections || []);
    return true;
  }, [token]);

  useEffect(() => {
    const tryTokens = async () => {
      // 1) existing admin token
      if (token) {
        try { await loadCollections(token); setAuthed(true); setChecking(false); return; } catch { /* fall through */ }
      }
      // 2) exchange a logged-in owner's user session for an admin token
      const userToken = localStorage.getItem("bs_user_token");
      if (userToken) {
        try {
          const r = await api.post("/admin/session-from-user", null, { headers: { Authorization: `Bearer ${userToken}` } });
          localStorage.setItem("bs_admin_token", r.data.token);
          setToken(r.data.token);
          await loadCollections(r.data.token);
          setAuthed(true);
          setChecking(false);
          return;
        } catch { /* fall through */ }
      }
      setChecking(false);
      loadCaptcha();
    };
    tryTokens();
    // eslint-disable-next-line
  }, []);

  const login = async (e) => {
    e.preventDefault();
    setLoggingIn(true);
    try {
      // Owner dashboard credentials → user JWT → owner admin session
      const lr = await api.post("/auth/login", {
        identifier: u.trim(),
        password: p,
        captcha_id: captcha?.id,
        captcha_answer: capAnswer.trim(),
      });
      const userToken = lr.data.token;
      const r = await api.post("/admin/session-from-user", null, { headers: { Authorization: `Bearer ${userToken}` } });
      localStorage.setItem("bs_admin_token", r.data.token);
      setToken(r.data.token);
      await loadCollections(r.data.token);
      setAuthed(true);
      toast.success("Owner access granted");
    } catch (err) {
      toast.error(err.response?.data?.detail || "Owner login required");
      loadCaptcha();
    } finally { setLoggingIn(false); }
  };

  const loadDocs = useCallback(async (coll, newSkip = 0, query = q) => {
    if (!coll) return;
    setLoading(true);
    try {
      const r = await adminApi(token).get(`/dbadmin/${coll}/docs`, { params: { skip: newSkip, limit: LIMIT, q: query } });
      setDocs(r.data.docs || []);
      setTotal(r.data.total || 0);
      setSkip(newSkip);
    } catch (e) {
      toast.error(e.response?.data?.detail || "Failed to load docs");
    } finally { setLoading(false); }
  }, [token, q]);

  const selectColl = (name) => {
    setSelected(name);
    setQ("");
    loadDocs(name, 0, "");
  };

  const docKey = (d) => d.id || d._id;

  const saveDoc = async () => {
    let parsed;
    try { parsed = JSON.parse(editDoc.json); } catch { toast.error("Invalid JSON"); return; }
    setSaving(true);
    try {
      if (editDoc.isNew) {
        await adminApi(token).post(`/dbadmin/${selected}/doc`, { doc: parsed });
        toast.success("Document inserted");
      } else {
        await adminApi(token).put(`/dbadmin/${selected}/doc/${editDoc.id}`, { doc: parsed });
        toast.success("Document updated");
      }
      setEditDoc(null);
      loadDocs(selected, skip);
      loadCollections();
    } catch (e) {
      toast.error(e.response?.data?.detail || "Save failed");
    } finally { setSaving(false); }
  };

  const deleteDoc = async (d) => {
    if (!window.confirm(`Delete this document from "${selected}"? This cannot be undone.`)) return;
    try {
      await adminApi(token).delete(`/dbadmin/${selected}/doc/${docKey(d)}`);
      toast.success("Deleted");
      loadDocs(selected, skip);
      loadCollections();
    } catch (e) {
      toast.error(e.response?.data?.detail || "Delete failed");
    }
  };

  const deleteAllMatching = async () => {
    const msg = q.trim()
      ? `Delete ALL documents in "${selected}" matching "${q}"? (${total} found)`
      : `Delete ALL ${total} documents in "${selected}"? THIS WIPES THE WHOLE COLLECTION.`;
    if (!window.confirm(msg)) return;
    if (!window.confirm("Are you 100% sure? This is permanent.")) return;
    try {
      const rx = q.trim() ? { $regex: q.trim(), $options: "i" } : null;
      const filter = rx ? { $or: [{ id: rx }, { username: rx }, { email: rx }, { name: rx }, { title: rx }, { status: rx }, { tiktok_username: rx }] } : {};
      const r = await adminApi(token).post(`/dbadmin/${selected}/delete-many`, { filter, confirm_all: !q.trim() });
      toast.success(`Deleted ${r.data.deleted} documents`);
      loadDocs(selected, 0);
      loadCollections();
    } catch (e) {
      toast.error(e.response?.data?.detail || "Bulk delete failed");
    }
  };

  if (checking) {
    return <div className="min-h-screen flex items-center justify-center bg-[#050505] text-white"><Loader2 className="w-5 h-5 animate-spin" /></div>;
  }

  if (!authed) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-[#050505] p-6">
        <form onSubmit={login} data-testid="dbm-login-form" className="w-full max-w-sm bg-[#0d1a0d] border border-emerald-500/30 rounded-md p-8">
          <div className="flex items-center gap-2 mb-6">
            <Database className="w-5 h-5 text-emerald-400" />
            <h1 className="font-black text-lg text-white">DB Manager</h1>
          </div>
          <p className="text-xs text-white/40 mb-6">Owner credentials required. This is a raw database console — full read/write/delete power.</p>
          <input data-testid="dbm-username" value={u} onChange={(e) => setU(e.target.value)} placeholder="Owner username"
                 className="w-full mb-3 bg-black/40 border border-white/10 rounded px-3 py-2 text-sm text-white outline-none focus:border-emerald-400" autoFocus />
          <input data-testid="dbm-password" type="password" value={p} onChange={(e) => setP(e.target.value)} placeholder="Password"
                 className="w-full mb-3 bg-black/40 border border-white/10 rounded px-3 py-2 text-sm text-white outline-none focus:border-emerald-400" />
          <div className="flex items-center gap-2 mb-4">
            <span className="text-xs text-emerald-300 font-mono whitespace-nowrap" data-testid="dbm-captcha-question">{captcha?.question || "…"}</span>
            <input data-testid="dbm-captcha-answer" value={capAnswer} onChange={(e) => setCapAnswer(e.target.value)} placeholder="Answer"
                   className="flex-1 bg-black/40 border border-white/10 rounded px-3 py-2 text-sm text-white outline-none focus:border-emerald-400" />
            <button type="button" onClick={loadCaptcha} className="text-white/40 hover:text-white text-xs">↻</button>
          </div>
          <button type="submit" disabled={loggingIn} data-testid="dbm-login-btn"
                  className="w-full py-2.5 bg-emerald-500 hover:bg-emerald-400 text-black rounded font-bold text-sm disabled:opacity-50">
            {loggingIn ? <Loader2 className="w-4 h-4 animate-spin mx-auto" /> : "Unlock console"}
          </button>
        </form>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-[#070b07] text-white flex flex-col" data-testid="dbm-shell">
      <header className="border-b border-emerald-500/20 bg-[#0a140a] px-4 h-14 flex items-center gap-3 sticky top-0 z-10">
        <Database className="w-5 h-5 text-emerald-400" />
        <span className="font-black">DB Manager</span>
        <span className="text-[10px] uppercase tracking-widest text-red-300 bg-red-950/50 border border-red-800/50 px-2 py-0.5 rounded">Owner only · raw data</span>
        <div className="ml-auto flex items-center gap-2">
          <a href="/admin" className="text-[11px] uppercase tracking-wider text-white/50 hover:text-white">Admin panel</a>
          <button onClick={() => { setAuthed(false); }} data-testid="dbm-logout" className="text-[11px] uppercase tracking-wider text-red-300 hover:text-red-200 flex items-center gap-1"><LogOut className="w-3 h-3" /> Lock</button>
        </div>
      </header>

      <div className="flex flex-1 min-h-0">
        {/* Sidebar */}
        <aside className="w-60 shrink-0 border-r border-emerald-500/15 bg-[#0a120a] overflow-y-auto p-2" data-testid="dbm-collections">
          <div className="flex items-center justify-between px-2 py-1.5">
            <span className="text-[10px] uppercase tracking-widest text-white/40">Collections ({collections.length})</span>
            <button onClick={() => loadCollections()} className="text-white/40 hover:text-white"><RefreshCw className="w-3 h-3" /></button>
          </div>
          {collections.map((c) => (
            <button key={c.name} onClick={() => selectColl(c.name)} data-testid={`dbm-coll-${c.name}`}
                    className={`w-full text-left px-2 py-1.5 rounded text-xs font-mono flex items-center justify-between gap-2 ${selected === c.name ? "bg-emerald-500/20 text-emerald-200" : "text-white/70 hover:bg-white/5"}`}>
              <span className="truncate">{c.name}</span>
              <span className="text-[10px] text-white/35">{c.count}</span>
            </button>
          ))}
        </aside>

        {/* Main */}
        <main className="flex-1 min-w-0 p-4 overflow-y-auto">
          {!selected ? (
            <div className="text-white/40 text-sm mt-20 text-center">Select a collection to browse, edit or delete documents.</div>
          ) : (
            <>
              <div className="flex flex-wrap items-center gap-2 mb-4">
                <h2 className="font-black font-mono text-emerald-300">{selected}</h2>
                <span className="text-xs text-white/40">{total} docs</span>
                <div className="flex items-center gap-1 bg-black/40 border border-white/10 rounded px-2">
                  <Search className="w-3 h-3 text-white/40" />
                  <input value={q} onChange={(e) => setQ(e.target.value)} onKeyDown={(e) => e.key === "Enter" && loadDocs(selected, 0)}
                         placeholder="search id / username / email…" data-testid="dbm-search"
                         className="bg-transparent py-1.5 text-xs text-white outline-none w-52" />
                </div>
                <button onClick={() => loadDocs(selected, 0)} className="px-2 py-1.5 border border-white/10 rounded text-xs hover:bg-white/5">Search</button>
                <button onClick={() => setEditDoc({ isNew: true, json: "{\n  \n}" })} data-testid="dbm-insert-btn"
                        className="px-2 py-1.5 bg-emerald-600 hover:bg-emerald-500 rounded text-xs font-bold flex items-center gap-1"><Plus className="w-3 h-3" /> Insert</button>
                <button onClick={deleteAllMatching} data-testid="dbm-delete-many-btn"
                        className="px-2 py-1.5 bg-red-900/60 border border-red-700/60 hover:bg-red-800 rounded text-xs font-bold text-red-200 flex items-center gap-1">
                  <Trash2 className="w-3 h-3" /> {q.trim() ? "Delete matching" : "Delete ALL"}
                </button>
                <div className="ml-auto flex items-center gap-1 text-xs">
                  <button disabled={skip === 0} onClick={() => loadDocs(selected, Math.max(0, skip - LIMIT))} className="p-1.5 border border-white/10 rounded disabled:opacity-30"><ChevronLeft className="w-3 h-3" /></button>
                  <span className="text-white/50">{skip + 1}–{Math.min(skip + LIMIT, total)}</span>
                  <button disabled={skip + LIMIT >= total} onClick={() => loadDocs(selected, skip + LIMIT)} className="p-1.5 border border-white/10 rounded disabled:opacity-30"><ChevronRight className="w-3 h-3" /></button>
                </div>
              </div>

              {loading ? (
                <Loader2 className="w-5 h-5 animate-spin text-emerald-400 mx-auto mt-10" />
              ) : (
                <div className="space-y-1.5" data-testid="dbm-docs">
                  {docs.map((d) => (
                    <div key={d._id} className="bg-[#0c150c] border border-white/8 rounded px-3 py-2 flex items-start gap-2 group">
                      <pre className="flex-1 min-w-0 text-[11px] font-mono text-white/70 whitespace-pre-wrap break-all max-h-24 overflow-hidden">
                        {JSON.stringify(d, null, 0).slice(0, 400)}
                      </pre>
                      <button onClick={() => setEditDoc({ id: docKey(d), json: JSON.stringify(d, null, 2), isNew: false })}
                              data-testid={`dbm-edit-${docKey(d)}`}
                              className="p-1.5 text-emerald-300 hover:bg-emerald-500/15 rounded" title="Edit"><Pencil className="w-3.5 h-3.5" /></button>
                      <button onClick={() => deleteDoc(d)} data-testid={`dbm-delete-${docKey(d)}`}
                              className="p-1.5 text-red-300 hover:bg-red-500/15 rounded" title="Delete"><Trash2 className="w-3.5 h-3.5" /></button>
                    </div>
                  ))}
                  {docs.length === 0 && <div className="text-white/40 text-sm mt-8 text-center">No documents.</div>}
                </div>
              )}
            </>
          )}
        </main>
      </div>

      {/* Edit / Insert modal */}
      {editDoc && (
        <div className="fixed inset-0 z-50 bg-black/80 backdrop-blur-sm flex items-center justify-center p-4" onClick={() => !saving && setEditDoc(null)}>
          <div onClick={(e) => e.stopPropagation()} className="bg-[#0d1a0d] border border-emerald-500/30 rounded-md p-5 w-full max-w-2xl">
            <h3 className="font-bold text-sm mb-3">{editDoc.isNew ? `Insert into ${selected}` : `Edit document (${editDoc.id})`}</h3>
            <textarea value={editDoc.json} onChange={(e) => setEditDoc({ ...editDoc, json: e.target.value })}
                      data-testid="dbm-doc-editor" spellCheck={false}
                      className="w-full h-80 bg-black/50 border border-white/10 rounded p-3 font-mono text-xs text-emerald-100 outline-none focus:border-emerald-400 resize-y" />
            <p className="text-[10px] text-white/40 mt-1">Note: the <code>_id</code> field is ignored on save. Editing sets every field you leave in the JSON.</p>
            <div className="flex justify-end gap-2 mt-3">
              <button onClick={() => setEditDoc(null)} disabled={saving} className="px-4 py-2 border border-white/10 rounded text-xs uppercase tracking-wider hover:bg-white/5">Cancel</button>
              <button onClick={saveDoc} disabled={saving} data-testid="dbm-doc-save"
                      className="px-4 py-2 bg-emerald-500 hover:bg-emerald-400 text-black rounded text-xs font-bold uppercase tracking-wider disabled:opacity-50 flex items-center gap-2">
                {saving && <Loader2 className="w-3 h-3 animate-spin" />} {editDoc.isNew ? "Insert" : "Save"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
