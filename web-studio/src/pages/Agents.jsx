import { useState, useEffect, useRef } from 'react';
import { Play, SquareTerminal, Loader2, StopCircle } from 'lucide-react';
import axios from 'axios';

const API_BASE = 'http://localhost:8000/api';
const WS_BASE = 'ws://localhost:8000/api';

export default function Agents() {
  const [running, setRunning] = useState(false);
  const [logs, setLogs] = useState([]);
  const [jobId, setJobId] = useState(null);
  const ws = useRef(null);
  const scrollRef = useRef(null);

  const startAgent = async (agentName) => {
    try {
      setRunning(true);
      setLogs([{ type: 'system', msg: `Triggering ${agentName}...` }]);
      
      const res = await axios.post(`${API_BASE}/agents/run`, {
        agent_name: agentName
      });
      
      setJobId(res.data.job_id);
    } catch (err) {
      setLogs(prev => [...prev, { type: 'error', msg: `Failed to start: ${err.message}` }]);
      setRunning(false);
    }
  };

  useEffect(() => {
    if (!jobId) return;

    // Connect to WebSocket stream for real-time logs
    ws.current = new WebSocket(`${WS_BASE}/agents/stream/${jobId}`);
    
    ws.current.onmessage = (event) => {
      const data = JSON.parse(event.data);
      setLogs(prev => [...prev, data]);
      if (data.type === 'success' || data.type === 'error') {
        setRunning(false);
      }
    };

    ws.current.onerror = () => {
      setLogs(prev => [...prev, { type: 'error', msg: 'WebSocket disconnected abnormally.' }]);
      setRunning(false);
    };

    return () => {
      if (ws.current) ws.current.close();
    };
  }, [jobId]);

  // Auto-scroll terminal
  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [logs]);

  const agentsList = [
    { id: 'narrativeManga', name: 'Narrative Manga (Episode 2)', desc: 'Generates animated manga episodes with TTS and Chronos.' },
    { id: 'newsDesk', name: 'AI News Anchor', desc: 'Synthesizes daily news into a video broadcast.' },
    { id: 'brandAds', name: 'Brand Storyteller', desc: 'Creates short 15s commercial reels.' }
  ];

  return (
    <div style={{ display: 'flex', gap: '1.5rem', height: '100%' }}>
      {/* Settings / Executors */}
      <div className="glass-panel" style={{ width: '400px', display: 'flex', flexDirection: 'column' }}>
        <div style={{ padding: '1.25rem', borderBottom: '1px solid var(--border-color)' }}>
          <h2 style={{ margin: 0, display: 'flex', alignItems: 'center', gap: '8px' }}>
            <Play size={20} className="text-accent" /> Available Agents
          </h2>
        </div>
        <div style={{ padding: '1rem', flex: 1, overflowY: 'auto' }}>
           {agentsList.map(agt => (
             <div key={agt.id} style={{ 
               background: 'var(--bg-surface)', 
               border: '1px solid var(--border-color)', 
               borderRadius: '8px', 
               padding: '1rem', 
               marginBottom: '1rem' 
             }}>
               <h3 style={{ margin: 0, fontSize: '1rem', color: 'var(--text-main)' }}>{agt.name}</h3>
               <p style={{ fontSize: '0.85rem', color: 'var(--text-muted)', margin: '0.5rem 0 1rem' }}>{agt.desc}</p>
               
               <button 
                 className={`btn ${running ? 'btn-default' : 'btn-primary'}`} 
                 onClick={() => startAgent(agt.id)}
                 disabled={running}
                 style={{ width: '100%', justifyContent: 'center' }}
               >
                 {running ? <Loader2 size={16} className="animate-spin" /> : <Play size={16} />}
                 {running ? 'Running...' : 'Execute Workflow'}
               </button>
             </div>
           ))}
        </div>
      </div>

      {/* Terminal Output */}
      <div className="glass-panel animate-fade-in" style={{ flex: 1, display: 'flex', flexDirection: 'column', background: '#0a0a0f' }}>
        <div style={{ 
          padding: '0.75rem 1rem', 
          borderBottom: '1px solid var(--border-color)', 
          display: 'flex', 
          alignItems: 'center', 
          justifyContent: 'space-between',
          background: 'var(--bg-surface)' 
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '0.85rem', color: 'var(--text-muted)' }}>
            <SquareTerminal size={16} /> Console Output
            {jobId && <span style={{ marginLeft: '8px', color: 'var(--text-accent)' }}>Job ID: {jobId}</span>}
          </div>
          
          {running && (
             <button className="btn" style={{ color: 'var(--danger)', padding: '0.25rem 0.5rem' }}>
               <StopCircle size={14} /> Abort
             </button>
          )}
        </div>
        
        <div ref={scrollRef} style={{ 
          flex: 1, 
          padding: '1rem', 
          overflowY: 'auto', 
          fontFamily: 'monospace', 
          fontSize: '0.85rem',
          lineHeight: '1.6'
        }}>
          {logs.map((log, i) => (
             <div key={i} style={{ 
               color: log.type === 'error' ? 'var(--danger)' : 
                      log.type === 'success' ? '#55efc4' : 
                      log.type === 'system' ? 'var(--text-muted)' : '#00cec9',
               marginBottom: '0.25rem'
             }}>
               <span style={{ opacity: 0.5, marginRight: '8px' }}>[{new Date().toLocaleTimeString()}]</span>
               {log.msg}
             </div>
          ))}
          {!running && logs.length === 0 && (
             <div style={{ opacity: 0.3, textAlign: 'center', marginTop: '20%' }}>
               Awaiting execution command...
             </div>
          )}
        </div>
      </div>
    </div>
  );
}
