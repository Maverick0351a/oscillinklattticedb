// SPDX-License-Identifier: BUSL-1.1
import React, { useEffect, useState } from 'react'

const API = (import.meta as any).env.VITE_API_URL || 'http://127.0.0.1:8080'

export default function App() {
  const [q, setQ] = useState('What is Oscillink?')
  const [candidates, setCandidates] = useState<any[]>([])
  const [context, setContext] = useState<any|null>(null)
  const [answer, setAnswer] = useState<string>('')
  const [loading, setLoading] = useState(false)
  const [verify, setVerify] = useState<{ok:boolean,msg:string}|null>(null)
  const [license, setLicense] = useState<{mode:string, notice:string}|null>(null)

  // Admin panel state
  const [dbPath, setDbPath] = useState<string>('latticedb')
  const [inputDir, setInputDir] = useState<string>('sample_data/assets_txt')
  const [scanLoading, setScanLoading] = useState(false)
  const [scanMsg, setScanMsg] = useState<string>('')
  const [ready, setReady] = useState<any|null>(null)
  const [manifest, setManifest] = useState<any[]|null>(null)
  const [nameLatticeId, setNameLatticeId] = useState<string>("")
  const [nameDisplay, setNameDisplay] = useState<string>("")
  const [manLimit, setManLimit] = useState<number>(20)
  const [manOffset, setManOffset] = useState<number>(0)
  const [manSortBy, setManSortBy] = useState<string>(()=>{
    try { return localStorage.getItem('manSortBy') || 'deltaH_total' } catch { return 'deltaH_total' }
  })
  const [manSortOrder, setManSortOrder] = useState<'asc'|'desc'>(()=>{
    try { return (localStorage.getItem('manSortOrder') as 'asc'|'desc') || 'desc' } catch { return 'desc' }
  })
  const [searchQ, setSearchQ] = useState<string>('')
  const [searchItems, setSearchItems] = useState<any[]|null>(null)
  const [dbReceipt, setDbReceipt] = useState<any|null>(null)
  // Admin: LLM model (Ollama model name or other backend-defined name)
  const [llmModel, setLlmModel] = useState<string>('mistral')
  const [llmInfo, setLlmInfo] = useState<any|null>(null)
    const [toast, setToast] = useState<string>('')

  useEffect(()=>{
    fetch(`${API}/v1/license/status`).then(r=>r.json()).then(j=>{
      setLicense({mode: String(j.mode||'dev'), notice: String(j.notice||'')})
    }).catch(()=>{})
  }, [])

  // Load persisted admin preferences
  useEffect(()=>{
    try {
      const m = localStorage.getItem('llmModel')
      if (m) setLlmModel(m)
      const dp = localStorage.getItem('dbPath')
      if (dp) setDbPath(dp)
      const id = localStorage.getItem('inputDir')
      if (id) setInputDir(id)
    } catch {}
  }, [])

  async function run() {
    setLoading(true)
    setVerify(null)
    try {
      const r = await fetch(`${API}/v1/latticedb/route`, {
        method: 'POST',
        headers: {'Content-Type':'application/json'},
        body: JSON.stringify({ db_path: dbPath, q, k_lattices: 8 })
      })
      const rr = await r.json()
      setCandidates(rr.candidates || [])
      const sel = (rr.candidates || []).slice(0,3).map((c:any)=>c.lattice_id)
      const c2 = await fetch(`${API}/v1/latticedb/compose`, {
        method: 'POST',
        headers: {'Content-Type':'application/json'},
        body: JSON.stringify({ db_path: dbPath, q, lattice_ids: sel })
      })
      const rc = await c2.json()
      setContext(rc.context_pack)
      setAnswer('')
      setLlmInfo(null)
    } finally {
      setLoading(false)
    }
  }

  async function runChat() {
    setLoading(true)
    setVerify(null)
    try {
      const r = await fetch(`${API}/v1/latticedb/chat`, {
        method: 'POST',
        headers: {'Content-Type':'application/json'},
        body: JSON.stringify({ db_path: dbPath, q, k_lattices: 8, select: 6, model: llmModel })
      })
      if (!r.ok) {
        const msg = await r.text()
        setAnswer(`Chat failed: ${r.status} ${msg}`)
        return
      }
      const j = await r.json()
      const chat = j.chat || {}
      setAnswer(String(chat.answer||''))
      const pack = chat.context_pack || null
      setContext(pack)
      setLlmInfo(chat.llm || null)
    } catch (e:any) {
      setAnswer(`Chat error: ${e?.message || String(e)}`)
    } finally {
      setLoading(false)
    }
  }

  async function verifyAgainstDbRoot() {
    try {
      setVerify(null)
      if (!context?.receipts?.composite) {
        setVerify({ok:false,msg:'No composite receipt to verify'})
        return
      }
  const r = await fetch(`${API}/v1/db/receipt`)
      if (!r.ok) { setVerify({ok:false,msg:'Failed to fetch DB receipt'}); return }
      const db = await r.json()
      const comp = context.receipts.composite
      const ok = !!db && db.db_root && comp.db_root && (db.db_root === comp.db_root)
      setVerify({ok, msg: ok ? 'Composite matches DB root ✔' : 'Composite does not match DB root ✖'})
    } catch (e:any) {
      setVerify({ok:false,msg:e?.message || 'Verify failed'})
    }
  }

  // Admin actions
  async function runScan() {
    setScanMsg('')
    setScanLoading(true)
    try {
      const r = await fetch(`${API}/v1/db/scan`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ input_dir: inputDir, out_dir: dbPath })
      })
      if (!r.ok) {
        setScanMsg(`Scan failed: ${r.status}`)
        return
      }
      const j = await r.json()
      setScanMsg(`Scan ok: ${JSON.stringify(j)}`)
    } catch (e:any) {
      setScanMsg(`Scan error: ${e?.message || e}`)
    } finally {
      setScanLoading(false)
    }
  }

  async function checkReady() {
    try {
      const r = await fetch(`${API}/readyz?db_path=${encodeURIComponent(dbPath)}`)
      const j = await r.json()
      setReady(j)
    } catch {
      setReady({ ok: false })
    }
  }

  async function loadManifest() {
    try {
      const r = await fetch(`${API}/v1/latticedb/manifest?db_path=${encodeURIComponent(dbPath)}&limit=${manLimit}&offset=${manOffset}&sort_by=${encodeURIComponent(manSortBy)}&sort_order=${encodeURIComponent(manSortOrder)}`)
      const j = await r.json()
      setManifest(j.items || [])
    } catch {
      setManifest([])
    }
  }

  async function doSearch() {
    try {
      const r = await fetch(`${API}/v1/latticedb/search?db_path=${encodeURIComponent(dbPath)}&q=${encodeURIComponent(searchQ)}&limit=50`)
      const j = await r.json()
      setSearchItems(j.items || [])
    } catch {
      setSearchItems([])
    }
  }

  async function setLatticeDisplayName() {
    if (!nameLatticeId || !nameDisplay) return
    try {
      const r = await fetch(`${API}/v1/latticedb/lattice/${encodeURIComponent(nameLatticeId)}/metadata`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ db_path: dbPath, display_name: nameDisplay })
      })
      if (!r.ok) {
        const t = await r.text()
        alert(`Failed to set name: ${t}`)
        return
      }
      await loadManifest()
      setNameLatticeId("")
      setNameDisplay("")
    } catch (e:any) {
      alert(`Error: ${e?.message||e}`)
    }
  }

  async function loadDbReceipt() {
    try {
      const r = await fetch(`${API}/v1/db/receipt?db_path=${encodeURIComponent(dbPath)}`)
      const j = await r.json()
      setDbReceipt(j)
    } catch {
      setDbReceipt({ error: 'failed to load db receipt' })
    }
  }

  return (
    <main style={{fontFamily:'Inter,system-ui,Arial', margin:'2rem auto', maxWidth:900}}>
      <h1>Oscillink LatticeDB (Scaffold)</h1>
      <p>Local, verifiable RAG via lattice-of-lattices. Extractive by default.</p>
      {/* Admin Panel */}
      <section style={{margin:'16px 0', padding:'12px', border:'1px solid #ddd', borderRadius:8}}>
        <h3>Admin • Database setup & inspect</h3>
        <div style={{display:'grid', gridTemplateColumns:'1fr 1fr', gap:8}}>
          <label style={{display:'flex', flexDirection:'column'}}>
            <span>DB Path</span>
            <input value={dbPath} onChange={e=>{ setDbPath(e.target.value); try{ localStorage.setItem('dbPath', e.target.value)}catch{} }} placeholder="latticedb" />
          </label>
          <label style={{display:'flex', flexDirection:'column'}}>
            <span>Input Dir</span>
            <input value={inputDir} onChange={e=>{ setInputDir(e.target.value); try{ localStorage.setItem('inputDir', e.target.value)}catch{} }} placeholder="sample_data/assets_txt" />
          </label>
        </div>
        <div style={{marginTop:8, display:'grid', gridTemplateColumns:'1fr 1fr auto', gap:8}}>
          <input placeholder="Lattice ID" value={nameLatticeId} onChange={e=>setNameLatticeId(e.target.value)} />
          <input placeholder="Display name" value={nameDisplay} onChange={e=>setNameDisplay(e.target.value)} />
          <button onClick={setLatticeDisplayName}>Set name</button>
        </div>
        <div style={{display:'grid', gridTemplateColumns:'1fr 1fr', gap:8, marginTop:8}}>
          <label style={{display:'flex', flexDirection:'column'}}>
            <span>LLM Model (admin-defined)</span>
            <input value={llmModel} onChange={e=>{ setLlmModel(e.target.value); try{ localStorage.setItem('llmModel', e.target.value)}catch{} }} placeholder="mistral or your-ollama-model" />
          </label>
          <div style={{display:'flex', flexDirection:'column', justifyContent:'flex-end'}}>
            <small>Tip: Create an Ollama model name that wraps your adapter (e.g., mistral-lattice) and enter it here.</small>
          </div>
        </div>
        <div style={{display:'flex', gap:8, marginTop:8, flexWrap:'wrap'}}>
          <button onClick={runScan} disabled={scanLoading}>{scanLoading ? 'Scanning…' : 'Run single scan'}</button>
          <button onClick={checkReady}>Check readiness</button>
          <button onClick={loadManifest}>List manifest</button>
          <button onClick={loadDbReceipt}>Load DB receipt</button>
        </div>
        {scanMsg && (<div style={{marginTop:8, fontFamily:'monospace'}}>{scanMsg}</div>)}
        {ready && (
          <details style={{marginTop:8}} open>
            <summary>Readiness</summary>
            <pre style={{background:'#f7f7f7', padding:8, borderRadius:6}}>{JSON.stringify(ready, null, 2)}</pre>
          </details>
        )}
        <div style={{marginTop:8, display:'flex', gap:8, alignItems:'center'}}>
          <input value={searchQ} onChange={e=>setSearchQ(e.target.value)} placeholder="Search manifest…" style={{flex:1, padding:8}} />
          <button onClick={doSearch}>Search</button>
        </div>
        {searchItems && (
          <details style={{marginTop:8}} open>
            <summary>Search results ({searchItems.length})</summary>
            <ul>
              {searchItems.map((it:any)=> (
                <li key={it.lattice_id}>{it.lattice_id} • {it.source_file} • ΔH {it.deltaH_total}</li>
              ))}
            </ul>
          </details>
        )}
        {manifest && (
          <details style={{marginTop:8}} open>
            <summary>Manifest items ({manifest.length})</summary>
            <div style={{display:'flex', gap:8, alignItems:'center', marginTop:4}}>
              <label>Limit <input type="number" value={manLimit} onChange={e=>setManLimit(parseInt(e.target.value||'0')||0)} style={{width:80}} /></label>
              <label>Offset <input type="number" value={manOffset} onChange={e=>setManOffset(parseInt(e.target.value||'0')||0)} style={{width:80}} /></label>
              <label>Sort by
                <select value={manSortBy} onChange={e=>{ setManSortBy(e.target.value); try{ localStorage.setItem('manSortBy', e.target.value)}catch{} }} style={{marginLeft:6}}>
                  <option value="group_id">group_id</option>
                  <option value="lattice_id">lattice_id</option>
                  <option value="deltaH_total">deltaH_total</option>
                  <option value="display_name">display_name</option>
                </select>
              </label>
              <label>Order
                <select value={manSortOrder} onChange={e=>{ const v = (e.target.value as 'asc'|'desc'); setManSortOrder(v); try{ localStorage.setItem('manSortOrder', v)}catch{} }} style={{marginLeft:6}}>
                  <option value="asc">asc</option>
                  <option value="desc">desc</option>
                </select>
              </label>
              <button onClick={loadManifest}>Reload</button>
            </div>
            <ul>
              {manifest.map((it:any)=> (
                <li key={it.lattice_id} data-testid="manifest-row" style={{display:'flex', alignItems:'center', gap:8, flexWrap:'wrap'}}>
                  <span style={{minWidth:240}}>{it.group_id}/{it.lattice_id} {it.display_name ? `— ${it.display_name}` : ''}</span>
                  <span>• {it.source_file} • ΔH {it.deltaH_total}</span>
                  <InlineRename latticeId={it.lattice_id} currentName={it.display_name||''} dbPath={dbPath} onSaved={()=>{ loadManifest(); setToast('Rename Complete'); setTimeout(()=>setToast(''), 1500) }} />
                </li>
              ))}
            </ul>
          </details>
        )}
        {dbReceipt && (
          <details style={{marginTop:8}} open>
            <summary>DB Receipt</summary>
            <pre style={{background:'#f7f7f7', padding:8, borderRadius:6}}>{JSON.stringify(dbReceipt, null, 2)}</pre>
          </details>
        )}
      </section>
      {toast && (
        <div role="status" aria-live="polite" data-testid="toast" style={{position:'fixed', bottom:16, right:16, background:'#222', color:'#fff', padding:'8px 12px', borderRadius:6}}>
          {toast}
        </div>
      )}
      <div style={{display:'flex', gap:8}}>
        <input value={q} onChange={e=>setQ(e.target.value)} style={{flex:1, padding:8}} placeholder="Ask a question…" />
  <button onClick={run} disabled={loading} style={{padding:'8px 12px'}}>{loading ? 'Running…' : 'Run'}</button>
        <button onClick={runChat} disabled={loading} style={{padding:'8px 12px'}}>{loading ? 'Asking…' : 'Ask with LLM'}</button>
      </div>
      {candidates.length>0 && (
        <section style={{marginTop:16}}>
          <h3>Candidate lattices</h3>
          <ul>{candidates.map(c=>(<li key={c.lattice_id}>{c.lattice_id} • score {c.score.toFixed(3)}</li>))}</ul>
        </section>
      )}
      {context && (
        <section style={{marginTop:16}}>
          <h3>Context Pack</h3>
          <pre style={{background:'#111', color:'#0f0', padding:12, borderRadius:6, overflow:'auto', maxHeight:300}}>{JSON.stringify(context, null, 2)}</pre>
          <div style={{marginTop:8, display:'flex', gap:8}}>
            <button onClick={verifyAgainstDbRoot}>Verify against DB root</button>
            {verify && (<span style={{color: verify.ok ? '#0a0' : '#a00'}}>{verify.msg}</span>)}
          </div>
          {answer && (
            <div style={{marginTop:12}}>
              <h4>LLM Answer</h4>
              <div style={{whiteSpace:'pre-wrap', background:'#f7f7f7', padding:8, borderRadius:6}}>{answer}</div>
            </div>
          )}
          {llmInfo && (
            <div style={{marginTop:8}}>
              <small>LLM: {llmInfo.model} • backend {llmInfo.backend} • max_tokens {llmInfo.max_tokens} • seed {llmInfo.seed}</small>
            </div>
          )}
        </section>
      )}
      <footer style={{marginTop:24, opacity:0.8, fontSize:12}}>
        <span>Powered by Oscillink</span>
        {license && (
          <span style={{marginLeft:8}}>• License: {license.mode} — {license.notice}</span>
        )}
      </footer>
    </main>
  )
}

function InlineRename({ latticeId, currentName, dbPath, onSaved }: { latticeId: string, currentName: string, dbPath: string, onSaved: ()=>void }) {
  const [open, setOpen] = useState(false)
  const [val, setVal] = useState<string>(currentName)
  const [saving, setSaving] = useState(false)

  useEffect(()=>{ setVal(currentName) }, [currentName])

  async function save() {
    if (!val) return
    setSaving(true)
    try {
      const r = await fetch(`${API}/v1/latticedb/lattice/${encodeURIComponent(latticeId)}/metadata`, {
        method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ db_path: dbPath, display_name: val })
      })
      if (!r.ok) {
        const t = await r.text(); alert(`Rename failed: ${r.status} ${t}`); return
      }
      onSaved()
      setOpen(false)
    } catch (e:any) {
      alert(`Rename error: ${e?.message||e}`)
    } finally {
      setSaving(false)
    }
  }

  if (!open) return (<button data-testid="rename-open" onClick={()=>setOpen(true)} style={{marginLeft:8}}>Rename</button>)
  return (
    <span style={{display:'inline-flex', gap:6, alignItems:'center'}}>
      <input data-testid="rename-input" value={val} onChange={e=>setVal(e.target.value)} onKeyDown={e=>{ if (e.key==='Enter') save() }} placeholder="New display name" />
      <button data-testid="rename-save" onClick={save} disabled={saving}>{saving ? 'Saving…' : 'Save'}</button>
      <button data-testid="rename-cancel" onClick={()=>{ setOpen(false); setVal(currentName) }} disabled={saving}>Cancel</button>
    </span>
  )
}