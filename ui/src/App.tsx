// SPDX-License-Identifier: BUSL-1.1
import React, { useEffect, useState } from 'react'

const API = (import.meta as any).env.VITE_API_URL || 'http://127.0.0.1:8080'

export default function App() {
  const [q, setQ] = useState('What is Oscillink?')
  const [candidates, setCandidates] = useState<any[]>([])
  const [context, setContext] = useState<any|null>(null)
  const [loading, setLoading] = useState(false)
  const [verify, setVerify] = useState<{ok:boolean,msg:string}|null>(null)
  const [license, setLicense] = useState<{mode:string, notice:string}|null>(null)

  useEffect(()=>{
    fetch(`${API}/v1/license/status`).then(r=>r.json()).then(j=>{
      setLicense({mode: String(j.mode||'dev'), notice: String(j.notice||'')})
    }).catch(()=>{})
  }, [])

  async function run() {
    setLoading(true)
    setVerify(null)
    try {
      const r = await fetch(`${API}/v1/latticedb/route`, {
        method: 'POST',
        headers: {'Content-Type':'application/json'},
        body: JSON.stringify({ q, k_lattices: 8 })
      })
      const rr = await r.json()
      setCandidates(rr.candidates || [])
      const sel = (rr.candidates || []).slice(0,3).map((c:any)=>c.lattice_id)
      const c2 = await fetch(`${API}/v1/latticedb/compose`, {
        method: 'POST',
        headers: {'Content-Type':'application/json'},
        body: JSON.stringify({ q, lattice_ids: sel })
      })
      const rc = await c2.json()
      setContext(rc.context_pack)
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

  return (
    <main style={{fontFamily:'Inter,system-ui,Arial', margin:'2rem auto', maxWidth:900}}>
      <h1>Oscillink LatticeDB (Scaffold)</h1>
      <p>Local, verifiable RAG via lattice-of-lattices. Extractive by default.</p>
      <div style={{display:'flex', gap:8}}>
        <input value={q} onChange={e=>setQ(e.target.value)} style={{flex:1, padding:8}} placeholder="Ask a question…" />
        <button onClick={run} disabled={loading} style={{padding:'8px 12px'}}>{loading ? 'Running…' : 'Run'}</button>
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