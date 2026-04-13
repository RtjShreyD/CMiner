/**
 * OvaWorkspace – UI for the OVA anime agent.
 *
 * Clean, minimal workspace that exposes the full OVA config.json surface.
 * No clouds, no niche bundles, no reference frames, no section locks.
 * Pipeline: planner → chars → scenes → audio → music → video
 */

import { useState, useEffect, useRef } from 'react';
import { Play, Loader2, StopCircle, RotateCcw } from 'lucide-react';
import axios from 'axios';
import { useNavigate, useParams } from 'react-router-dom';
import SessionTreeView from '../components/SessionTreeView';
import FilePreviewPane from '../components/FilePreviewPane';

const API_BASE = 'http://localhost:8000/api';
const WS_BASE  = 'ws://localhost:8000/api';
const MEDIA_BASE = 'http://localhost:8000/media';

const DEFAULT_LIMITS = {
  maxImageRequests: 36,
  maxCharsPerEpisode: 6,
  maxPanelsPerEpisode: 20,
  maxEpisodeDurationMins: 2,
};

const PIPELINE_STEPS = ['planner', 'chars', 'scenes', 'audio', 'music', 'video'];

function isOvaSessionFolder(name) {
  return typeof name === 'string' && name.trim().toLowerCase() === 'ova';
}

export default function OvaWorkspace({ onBack }) {
  const navigate = useNavigate();
  const { sessionId } = useParams();

  // ── Session state ────────────────────────────────────────
  const [sessionMode, setSessionMode]   = useState('new');
  const [sessionPath, setSessionPath]   = useState('');
  const [availableSessions, setAvailableSessions] = useState([]);

  // ── Pipeline state ────────────────────────────────────────
  const [running, setRunning]     = useState(false);
  const [stepBusy, setStepBusy]   = useState('');
  const [jobId, setJobId]         = useState(null);
  const [logs, setLogs]           = useState([]);
  const [toasts, setToasts]       = useState([]);
  const [treeRefreshToken, setTreeRefreshToken] = useState(0);
  const [workflowHashes, setWorkflowHashes] = useState({});

  // ── Config options from server ────────────────────────────
  const [plannerThemes, setPlannerThemes]   = useState({});
  const [plannerArtStyles, setPlannerArtStyles] = useState({});
  const [outputPresets, setOutputPresets]   = useState({});
  const [modelsConfig, setModelsConfig]     = useState({});

  // ── Step 1: Story ─────────────────────────────────────────
  const [narrativePrompt, setNarrativePrompt] = useState('A dramatic anime story with vivid characters.');
  const [theme, setTheme]     = useState('auto-select');
  const [preset, setPreset]   = useState('auto-select');
  const [episodesMode, setEpisodesMode] = useState('new');
  const [episodeMode, setEpisodeMode]   = useState(false);
  const [targetEpisode, setTargetEpisode] = useState('');
  const [develop, setDevelop] = useState(true);

  // ── Step 0: Format ────────────────────────────────────────
  const [format, setFormat] = useState('youtube_widescreen');

  // ── Step 0: Styles ───────────────────────────────────────
  const [fontStyle, setFontStyle]         = useState('font-geist-sans');
  const [subtitleStyle, setSubtitleStyle] = useState('sub-clean-bottom');

  // ── Step 6: Music ─────────────────────────────────────────
  const [enableMusic, setEnableMusic]     = useState(false);
  const [musicProvider, setMusicProvider] = useState('lyria');
  const [lyriaModel, setLyriaModel]       = useState('lyria-3-clip-preview');

  // ── Audio ─────────────────────────────────────────────────
  const [ttsProvider, setTtsProvider]     = useState('edge');
  const [geminiTtsModel, setGeminiTtsModel] = useState('models/gemini-2.5-flash-tts');

  // ── Model limits ──────────────────────────────────────────
  const [maxImageRequests, setMaxImageRequests]       = useState(DEFAULT_LIMITS.maxImageRequests);
  const [maxCharsPerEpisode, setMaxCharsPerEpisode]   = useState(DEFAULT_LIMITS.maxCharsPerEpisode);
  const [maxPanelsPerEpisode, setMaxPanelsPerEpisode] = useState(DEFAULT_LIMITS.maxPanelsPerEpisode);
  const [maxEpisodeDurationMins, setMaxEpisodeDurationMins] = useState(DEFAULT_LIMITS.maxEpisodeDurationMins);

  // ── Model overrides ───────────────────────────────────────
  const [plannerModel, setPlannerModel]   = useState('models/gemini-flash-latest');
  const [charsModel, setCharsModel]       = useState('models/gemini-2.5-flash-image');
  const [scenesModel, setScenesModel]     = useState('models/gemini-2.5-flash-image');

  // ── File tree ─────────────────────────────────────────────
  const [selectedFile, setSelectedFile] = useState(null);

  const ws = useRef(null);
  const wsIntentionalCloseRef = useRef(false);
  const sessionPathRef = useRef('');
  const scrollRef = useRef(null);

  useEffect(() => { sessionPathRef.current = sessionPath || ''; }, [sessionPath]);

  // ── Load planner options from OVA config ─────────────────
  useEffect(() => {
    const load = async () => {
      try {
        const res = await axios.get(`${API_BASE}/agents/ova/planner-options`);
        const d = res.data || {};
        setPlannerThemes(d.themes || {});
        setPlannerArtStyles(d.art_styles || {});
        setOutputPresets(d.output_presets || {});
        setModelsConfig(d.models || {});
        // Apply defaults from config
        const defaults = d.defaults || {};
        if (defaults.font_style)    setFontStyle(defaults.font_style);
        if (defaults.subtitle_style) setSubtitleStyle(defaults.subtitle_style);
        // Apply models defaults
        const mc = d.models || {};
        if (mc.planner_model)      setPlannerModel(mc.planner_model);
        if (mc.character_image_model) setCharsModel(mc.character_image_model);
        if (mc.scene_image_model)  setScenesModel(mc.scene_image_model);
        if (mc.music_provider)     setMusicProvider(mc.music_provider);
        if (mc.lyria_model)        setLyriaModel(mc.lyria_model);
        if (mc.tts_provider)       setTtsProvider(mc.tts_provider);
        if (mc.gemini_tts_model)   setGeminiTtsModel(mc.gemini_tts_model);
        if (mc.max_image_requests)       setMaxImageRequests(mc.max_image_requests);
        if (mc.max_chars_per_episode)    setMaxCharsPerEpisode(mc.max_chars_per_episode);
        if (mc.max_panels_per_episode)   setMaxPanelsPerEpisode(mc.max_panels_per_episode);
        if (mc.max_episode_duration_mins) setMaxEpisodeDurationMins(mc.max_episode_duration_mins);
      } catch {
        // Keep built-in defaults on failure.
      }
    };
    load();
  }, []);

  // ── Load available sessions ───────────────────────────────
  useEffect(() => {
    const load = async () => {
      try {
        const root = await axios.get(`${API_BASE}/sessions/tree`);
        const roots = (root.data || []).filter((i) => i.is_dir);
        const options = [];
        for (const r of roots) {
          try {
            const sub = await axios.get(`${API_BASE}/sessions/tree`, { params: { path: r.path } });
            const match = (sub.data || []).find((i) => i.is_dir && isOvaSessionFolder(i.name));
            if (match) options.push(match.path);
          } catch { /* skip */ }
        }
        setAvailableSessions(options);
        if (sessionMode === 'existing') {
          const fromUrl = sessionId ? (options.find((p) => p.startsWith(`${sessionId}/`)) || '') : '';
          const nextPath = sessionPath || fromUrl || options[0] || '';
          if (nextPath && nextPath !== sessionPath) setSessionPath(nextPath);
        }
      } catch { /* ignore */ }
    };
    load();
  }, [treeRefreshToken]);

  // ── Load session state when path changes ─────────────────
  useEffect(() => {
    if (sessionMode !== 'existing' || !sessionPath) return;
    const load = async () => {
      try {
        const res = await axios.get(`${API_BASE}/sessions/file`, {
          params: { path: `${sessionPath}/session_state.json` },
        });
        const settings = JSON.parse(res.data?.content || '{}')?.settings || {};
        if (settings.prompt)       setNarrativePrompt(settings.prompt);
        if (settings.theme)        setTheme(settings.theme);
        if (settings.preset)       setPreset(settings.preset);
        if (settings.format)       setFormat(settings.format);
        if (settings.font_style)   setFontStyle(settings.font_style);
        if (settings.subtitle_style) setSubtitleStyle(settings.subtitle_style);
        if (typeof settings.enable_music === 'boolean') setEnableMusic(settings.enable_music);
        if (settings.music_provider) setMusicProvider(settings.music_provider);
        if (settings.lyria_model)  setLyriaModel(settings.lyria_model);
        if (settings.tts_provider) setTtsProvider(settings.tts_provider);
        if (settings.gemini_tts_model) setGeminiTtsModel(settings.gemini_tts_model);
        if (typeof settings.max_image_requests === 'number') setMaxImageRequests(settings.max_image_requests);
        if (typeof settings.max_chars_per_episode === 'number') setMaxCharsPerEpisode(settings.max_chars_per_episode);
        if (typeof settings.max_panels_per_episode === 'number') setMaxPanelsPerEpisode(settings.max_panels_per_episode);
        if (typeof settings.max_episode_duration_mins === 'number') setMaxEpisodeDurationMins(settings.max_episode_duration_mins);
        if (settings.planner_model) setPlannerModel(settings.planner_model);
        if (settings.character_image_model) setCharsModel(settings.character_image_model);
        if (settings.scene_image_model) setScenesModel(settings.scene_image_model);
        if (typeof settings.episode_mode === 'boolean') setEpisodeMode(settings.episode_mode);
        if (settings.episodes_mode) setEpisodesMode(settings.episodes_mode);
      } catch { /* keep current state */ }
    };
    load();
  }, [sessionPath, sessionMode]);

  // ── Switch to continue mode when picking existing session ─
  useEffect(() => {
    if (sessionMode !== 'existing') {
      setEpisodesMode('new');
      return;
    }
    setEpisodesMode((prev) => (prev === 'new' ? 'continue' : prev));
  }, [sessionMode]);

  // ── Refresh workflow hashes ───────────────────────────────
  const refreshHashes = async (path) => {
    if (!path) { setWorkflowHashes({}); return; }
    try {
      const res = await axios.get(`${API_BASE}/agents/ova/checkpoints`, { params: { session_path: path } });
      setWorkflowHashes(res.data?.hashes || {});
    } catch {
      setWorkflowHashes({});
    }
  };

  useEffect(() => {
    refreshHashes(sessionPath);
  }, [sessionPath]);

  // ── Periodic refresh while session is active ──────────────
  useEffect(() => {
    if (sessionMode !== 'existing' || !sessionPath) return;
    const id = setInterval(() => {
      setTreeRefreshToken((p) => p + 1);
      refreshHashes(sessionPath);
    }, 30000);
    return () => clearInterval(id);
  }, [sessionMode, sessionPath]);

  // ── Toast helper ──────────────────────────────────────────
  const pushToast = (type, message) => {
    const id = `${Date.now()}-${Math.random().toString(36).slice(2, 6)}`;
    setToasts((prev) => [...prev, { id, type, message }]);
    setTimeout(() => setToasts((prev) => prev.filter((t) => t.id !== id)), 3200);
  };

  // ── Sync settings to server before a run ─────────────────
  const syncSettings = async (activePath) => {
    if (!activePath) return;
    const snapshot = {
      prompt: narrativePrompt,
      theme,
      preset,
      format,
      enable_music: enableMusic,
      music_provider: musicProvider,
      lyria_model: lyriaModel,
      tts_provider: ttsProvider,
      gemini_tts_model: geminiTtsModel,
      font_style: fontStyle,
      subtitle_style: subtitleStyle,
      max_image_requests: maxImageRequests,
      max_chars_per_episode: maxCharsPerEpisode,
      max_panels_per_episode: maxPanelsPerEpisode,
      max_episode_duration_mins: maxEpisodeDurationMins,
      planner_model: plannerModel,
      character_image_model: charsModel,
      scene_image_model: scenesModel,
      episodes_mode: episodesMode,
      episode_mode: episodeMode,
    };
    try {
      await axios.post(`${API_BASE}/agents/ova/session-sync`, {
        session_path: activePath,
        settings: snapshot,
      });
    } catch { /* Non-fatal */ }
  };

  // ── Build resolution from format ─────────────────────────
  const resolutionFromFormat = (fmt) => {
    const map = {
      youtube_widescreen: 'youtube_video',
      youtube_shorts:     'youtube_shorts',
      tiktok:             'youtube_shorts',
      instagram_reels:    'insta_reels',
    };
    return map[fmt] || 'youtube_video';
  };

  // ── Run a pipeline step ───────────────────────────────────
  const runStep = async (step, opts = {}) => {
    setStepBusy(step);
    if (opts.resetConsole) setLogs([]);

    try {
      let activePath = sessionPath;

      // Bootstrap session for planner/all if none exists
      if (!activePath && (step === 'all' || step === 'planner')) {
        const boot = await axios.post(`${API_BASE}/agents/ova/bootstrap-session`);
        activePath = boot.data?.session_path || '';
        if (activePath) {
          setSessionPath(activePath);
          setSessionMode('existing');
          setTreeRefreshToken((p) => p + 1);
          const sid = boot.data?.session_id || activePath.split('/')[0] || '';
          if (sid) {
            navigate(`/agents/ova/existing/${encodeURIComponent(sid)}`, { replace: true });
          }
        }
      }

      if (activePath) await syncSettings(activePath);

      const payload = {
        session_mode: activePath ? 'existing' : 'new',
        session_path: activePath || null,
        step,
        reset: Boolean(opts.redo),
        prompt: narrativePrompt,
        episodes: episodesMode,
        develop: episodesMode === 'continue' ? develop : true,
        episode: targetEpisode ? parseInt(targetEpisode, 10) : null,
        episode_mode: episodeMode,
        theme: theme !== 'auto-select' ? theme : null,
        preset: preset !== 'auto-select' ? preset : null,
        format,
        buildpack_resolution: resolutionFromFormat(format),
        enable_music: enableMusic,
        music_provider: musicProvider,
        lyria_model: lyriaModel,
        tts_provider: ttsProvider,
        gemini_tts_model: geminiTtsModel,
        font_style: fontStyle,
        subtitle_style: subtitleStyle,
        planner_model: plannerModel,
        chars_model: charsModel,
        scenes_model: scenesModel,
        max_image_requests: maxImageRequests,
        max_chars_per_episode: maxCharsPerEpisode,
        max_panels_per_episode: maxPanelsPerEpisode,
        max_episode_duration_mins: maxEpisodeDurationMins,
      };

      const start = await axios.post(`${API_BASE}/agents/ova/run-step-live`, payload);

      const startedPath = start.data?.session_path;
      if (startedPath && startedPath !== sessionPath) {
        setSessionPath(startedPath);
        setSessionMode('existing');
        setTreeRefreshToken((p) => p + 1);
        const sid = start.data?.session_id || startedPath.split('/')[0] || '';
        if (sid) navigate(`/agents/ova/existing/${encodeURIComponent(sid)}`, { replace: true });
      }

      if (start.data?.done && start.data?.result) {
        const r = start.data.result;
        setLogs((p) => [...p, { type: r.status === 'error' ? 'error' : 'info', msg: r.reason || `Step '${step}' ${r.status}.` }]);
        return;
      }

      const currentJobId = start.data?.job_id;
      if (!currentJobId) {
        setLogs((p) => [...p, { type: 'error', msg: `Step '${step}' did not return a job id.` }]);
        return;
      }

      setJobId(currentJobId);
      setLogs((p) => [...p, { type: 'info', msg: `Step '${step}' started (job: ${currentJobId})` }]);

      let finalRes = null;
      for (;;) {
        await new Promise((r) => setTimeout(r, 500));
        const poll = await axios.get(`${API_BASE}/agents/ova/job/${currentJobId}`);
        if (poll.data?.done) { finalRes = poll.data?.result || {}; break; }
      }

      setJobId(null);
      const nextPath = finalRes?.session_path || startedPath || sessionPath;
      if (nextPath && nextPath !== sessionPath) setSessionPath(nextPath);
      if (finalRes?.hashes) setWorkflowHashes(finalRes.hashes);
      else if (nextPath) await refreshHashes(nextPath);

      const status = finalRes?.status || 'success';
      setLogs((p) => [...p, {
        type: status === 'error' ? 'error' : 'success',
        msg: status === 'error' ? (finalRes?.stderr?.slice(-300) || 'Step failed') : `Step '${step}' completed`,
      }]);
      pushToast(status === 'error' ? 'error' : 'success',
        status === 'error' ? `Step ${step} failed.` : `Step ${step} completed.`);

      if (nextPath) {
        setTreeRefreshToken((p) => p + 1);
        const sid = nextPath.split('/')[0];
        if (sid) navigate(`/agents/ova/existing/${encodeURIComponent(sid)}`, { replace: true });
      }
    } catch (e) {
      setLogs((p) => [...p, { type: 'error', msg: `Step '${step}' failed: ${e.message}` }]);
      pushToast('error', `Step ${step} failed.`);
    } finally {
      setJobId(null);
      setStepBusy('');
      setRunning(false);
    }
  };

  const startFullPipeline = () => {
    setRunning(true);
    setLogs([{ type: 'system', msg: 'Running full OVA pipeline...' }]);
    runStep('all', { resetConsole: false });
  };

  const abortJob = async () => {
    if (!jobId) return;
    try {
      await axios.post(`${API_BASE}/agents/ova/job/${jobId}/abort`);
      pushToast('success', 'Abort requested.');
    } catch (e) {
      pushToast('error', `Abort failed: ${e.message}`);
    }
  };

  // ── WebSocket live log streaming ──────────────────────────
  useEffect(() => {
    if (!jobId) return;
    wsIntentionalCloseRef.current = false;
    ws.current = new WebSocket(`${WS_BASE}/agents/stream/${jobId}`);

    ws.current.onmessage = (event) => {
      const data = JSON.parse(event.data);
      setLogs((prev) => [...prev, data]);
      if (typeof data?.msg === 'string') {
        if (data.msg.includes('New session directory:')) {
          const marker = 'New session directory:';
          const idx = data.msg.indexOf(marker);
          const absPath = idx >= 0 ? data.msg.slice(idx + marker.length).trim() : '';
          const outIdx = absPath.indexOf('/outputs/');
          if (outIdx >= 0) {
            const rel = absPath.slice(outIdx + '/outputs/'.length);
            if (rel) { setSessionPath(rel); setTreeRefreshToken((p) => p + 1); }
          }
        }
        if (data.msg.includes("step '") && data.msg.includes('finished with status')) {
          setTreeRefreshToken((p) => p + 1);
          const ap = sessionPathRef.current;
          if (ap) refreshHashes(ap);
        }
      }
      if (data.type === 'success' || data.type === 'error') setRunning(false);
    };
    ws.current.onerror = () => { if (!wsIntentionalCloseRef.current) pushToast('error', 'WebSocket error.'); setRunning(false); };
    ws.current.onclose = () => { if (!wsIntentionalCloseRef.current) setLogs((p) => [...p, { type: 'info', msg: 'Log stream closed.' }]); };

    return () => {
      wsIntentionalCloseRef.current = true;
      if (ws.current && ws.current.readyState < 2) ws.current.close();
    };
  }, [jobId]);

  useEffect(() => {
    if (scrollRef.current) scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
  }, [logs]);

  // ── Helpers ───────────────────────────────────────────────
  const stepDone    = (s) => Boolean(workflowHashes?.[s]);
  const stepRunning = (s) => stepBusy === s || stepBusy === 'all';
  const startNewSession = () => {
    setSessionMode('new');
    setSessionPath('');
    setEpisodesMode('new');
    setEpisodeMode(false);
    setTargetEpisode('');
    setWorkflowHashes({});
    navigate('/agents/ova/new');
  };

  // ── Render ────────────────────────────────────────────────
  return (
    <div className="agents-layout" style={{ display: 'flex', gap: '1rem', height: '100%', position: 'relative' }}>
      {/* Toast stack */}
      <div style={{ position: 'fixed', top: 18, right: 22, zIndex: 9999, display: 'flex', flexDirection: 'column', gap: 8 }}>
        {toasts.map((t) => (
          <div key={t.id} style={{
            minWidth: 220, maxWidth: 360, padding: '0.55rem 0.75rem', borderRadius: 8,
            border: '1px solid var(--border-color)', fontSize: '0.86rem',
            background: t.type === 'error' ? '#4a1f1f' : '#1f3f2f', color: '#f4f8ff',
            boxShadow: '0 8px 24px rgba(0,0,0,0.35)',
          }}>{t.message}</div>
        ))}
      </div>

      {/* ── Left sidebar ── */}
      <aside className="glass-panel agents-sidebar" style={{ width: 390, display: 'flex', flexDirection: 'column', overflowY: 'auto' }}>
        <section style={{ padding: '1rem', borderBottom: '1px solid var(--border-color)', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <div>
            <h2 style={{ margin: 0, display: 'flex', alignItems: 'center', gap: 8, color: 'var(--text-accent)' }}>
              <Play size={20} /> OVA Agent
            </h2>
            <p style={{ marginTop: '0.3rem', color: 'var(--text-muted)', fontSize: '0.85rem', margin: '0.3rem 0 0' }}>
              Anime OVA pipeline – subtitles-only, cinematic output.
            </p>
          </div>
          <div style={{ display: 'flex', gap: '0.5rem' }}>
            <button className="btn" type="button" onClick={startNewSession} style={{ height: '2rem' }}>New Session</button>
            <button className="btn" type="button" onClick={onBack} style={{ height: '2rem' }}>Back</button>
          </div>
        </section>

        <div style={{ padding: '1rem', overflowY: 'auto', flex: 1, display: 'flex', flexDirection: 'column', gap: '0.9rem' }}>

          {/* Session selector */}
          <details open>
            <summary style={{ cursor: 'pointer', color: 'var(--text-accent)', marginBottom: '0.45rem', fontWeight: 600 }}>
              Session
            </summary>
            <label style={{ display: 'block', marginBottom: 6, fontSize: '0.85rem' }}>
              Mode
              <select value={sessionMode} onChange={(e) => setSessionMode(e.target.value)} style={{ marginLeft: 8 }}>
                <option value="new">New session</option>
                <option value="existing">Existing session</option>
              </select>
            </label>
            {sessionMode === 'existing' && (
              <label style={{ display: 'block', fontSize: '0.85rem' }}>
                Session path
                <select value={sessionPath} onChange={(e) => setSessionPath(e.target.value)} style={{ width: '100%', marginTop: 4 }}>
                  {availableSessions.map((s) => <option key={s} value={s}>{s}</option>)}
                </select>
              </label>
            )}
            {sessionMode === 'existing' && sessionPath && (
              <div style={{ marginTop: 8, display: 'flex', gap: 6, flexWrap: 'wrap' }}>
                <label style={{ fontSize: '0.83rem' }}>
                  <input type="checkbox" checked={episodeMode} onChange={(e) => setEpisodeMode(e.target.checked)} style={{ marginRight: 4 }} />
                  Episode continuity mode
                </label>
                <label style={{ fontSize: '0.83rem' }}>
                  Episodes:&nbsp;
                  <select value={episodesMode} onChange={(e) => setEpisodesMode(e.target.value)}>
                    <option value="new">New episode</option>
                    <option value="continue">Continue series</option>
                  </select>
                </label>
                {episodesMode === 'continue' && (
                  <label style={{ fontSize: '0.83rem' }}>
                    Also generate assets&nbsp;
                    <input type="checkbox" checked={develop} onChange={(e) => setDevelop(e.target.checked)} />
                  </label>
                )}
                <label style={{ fontSize: '0.83rem' }}>
                  Target episode:&nbsp;
                  <input type="number" min={1} value={targetEpisode} onChange={(e) => setTargetEpisode(e.target.value)}
                    placeholder="auto" style={{ width: 60 }} />
                </label>
              </div>
            )}
          </details>

          {/* Story prompt */}
          <details open>
            <summary style={{ cursor: 'pointer', color: 'var(--text-accent)', marginBottom: '0.45rem', fontWeight: 600 }}>
              Story Prompt
            </summary>
            <textarea
              value={narrativePrompt}
              onChange={(e) => setNarrativePrompt(e.target.value)}
              rows={4}
              placeholder="Describe your OVA universe, characters and first episode premise..."
              style={{ width: '100%', resize: 'vertical', fontSize: '0.88rem', boxSizing: 'border-box' }}
            />
          </details>

          {/* Theme & Art Style */}
          <details open>
            <summary style={{ cursor: 'pointer', color: 'var(--text-accent)', marginBottom: '0.45rem', fontWeight: 600 }}>
              Theme &amp; Art Style
            </summary>
            <div style={{ display: 'grid', gap: '0.5rem' }}>
              <label style={{ fontSize: '0.85rem' }}>
                Theme
                <select value={theme} onChange={(e) => setTheme(e.target.value)} style={{ width: '100%', marginTop: 3 }}>
                  <option value="auto-select">Auto-select</option>
                  {Object.keys(plannerThemes).map((k) => <option key={k} value={k}>{k.replace(/_/g, ' ')}</option>)}
                </select>
              </label>
              <label style={{ fontSize: '0.85rem' }}>
                Art style
                <select value={preset} onChange={(e) => setPreset(e.target.value)} style={{ width: '100%', marginTop: 3 }}>
                  <option value="auto-select">Auto-select</option>
                  {Object.keys(plannerArtStyles).map((k) => <option key={k} value={k}>{k.replace(/_/g, ' ')}</option>)}
                </select>
              </label>
            </div>
          </details>

          {/* Output format */}
          <details open>
            <summary style={{ cursor: 'pointer', color: 'var(--text-accent)', marginBottom: '0.45rem', fontWeight: 600 }}>
              Output Format
            </summary>
            <select value={format} onChange={(e) => setFormat(e.target.value)} style={{ width: '100%' }}>
              {Object.keys(outputPresets).length > 0
                ? Object.entries(outputPresets).map(([k, v]) => (
                    <option key={k} value={k}>{k.replace(/_/g, ' ')} — {v.resolution?.[0]}×{v.resolution?.[1]} {v.fps}fps</option>
                  ))
                : <>
                    <option value="youtube_widescreen">YouTube widescreen — 1920×1080 30fps</option>
                    <option value="youtube_shorts">YouTube shorts — 1080×1920 30fps</option>
                    <option value="tiktok">TikTok — 1080×1920 30fps</option>
                    <option value="instagram_reels">Instagram Reels — 1080×1920 30fps</option>
                  </>
              }
            </select>
          </details>

          {/* Subtitle & Font */}
          <details open>
            <summary style={{ cursor: 'pointer', color: 'var(--text-accent)', marginBottom: '0.45rem', fontWeight: 600 }}>
              Subtitles &amp; Typography
            </summary>
            <div style={{ display: 'grid', gap: '0.5rem' }}>
              <label style={{ fontSize: '0.85rem' }}>
                Font style
                <input type="text" value={fontStyle} onChange={(e) => setFontStyle(e.target.value)}
                  style={{ width: '100%', marginTop: 3 }} placeholder="font-geist-sans" />
              </label>
              <label style={{ fontSize: '0.85rem' }}>
                Subtitle style
                <input type="text" value={subtitleStyle} onChange={(e) => setSubtitleStyle(e.target.value)}
                  style={{ width: '100%', marginTop: 3 }} placeholder="sub-clean-bottom" />
              </label>
            </div>
          </details>

          {/* Audio & TTS */}
          <details>
            <summary style={{ cursor: 'pointer', color: 'var(--text-accent)', marginBottom: '0.45rem', fontWeight: 600 }}>
              Audio / TTS
            </summary>
            <div style={{ display: 'grid', gap: '0.5rem' }}>
              <label style={{ fontSize: '0.85rem' }}>
                TTS provider
                <select value={ttsProvider} onChange={(e) => setTtsProvider(e.target.value)} style={{ width: '100%', marginTop: 3 }}>
                  <option value="edge">Edge TTS (free)</option>
                  <option value="gemini">Gemini TTS</option>
                </select>
              </label>
              {ttsProvider === 'gemini' && (
                <label style={{ fontSize: '0.85rem' }}>
                  Gemini TTS model
                  <input type="text" value={geminiTtsModel} onChange={(e) => setGeminiTtsModel(e.target.value)}
                    style={{ width: '100%', marginTop: 3 }} />
                </label>
              )}
            </div>
          </details>

          {/* Music */}
          <details>
            <summary style={{ cursor: 'pointer', color: 'var(--text-accent)', marginBottom: '0.45rem', fontWeight: 600 }}>
              Background Music
            </summary>
            <div style={{ display: 'grid', gap: '0.5rem' }}>
              <label style={{ fontSize: '0.85rem', display: 'flex', alignItems: 'center', gap: 6 }}>
                <input type="checkbox" checked={enableMusic} onChange={(e) => setEnableMusic(e.target.checked)} />
                Enable background music generation
              </label>
              {enableMusic && (
                <>
                  <label style={{ fontSize: '0.85rem' }}>
                    Music provider
                    <select value={musicProvider} onChange={(e) => setMusicProvider(e.target.value)} style={{ width: '100%', marginTop: 3 }}>
                      <option value="lyria">Lyria (Google)</option>
                      <option value="strudel">Strudel</option>
                    </select>
                  </label>
                  {musicProvider === 'lyria' && (
                    <label style={{ fontSize: '0.85rem' }}>
                      Lyria model
                      <input type="text" value={lyriaModel} onChange={(e) => setLyriaModel(e.target.value)}
                        style={{ width: '100%', marginTop: 3 }} />
                    </label>
                  )}
                </>
              )}
            </div>
          </details>

          {/* Generation limits */}
          <details>
            <summary style={{ cursor: 'pointer', color: 'var(--text-accent)', marginBottom: '0.45rem', fontWeight: 600 }}>
              Generation Limits
            </summary>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.5rem' }}>
              {[
                ['Max images', maxImageRequests, setMaxImageRequests],
                ['Max chars', maxCharsPerEpisode, setMaxCharsPerEpisode],
                ['Max panels', maxPanelsPerEpisode, setMaxPanelsPerEpisode],
                ['Duration (mins)', maxEpisodeDurationMins, setMaxEpisodeDurationMins],
              ].map(([label, val, setter]) => (
                <label key={label} style={{ fontSize: '0.83rem' }}>
                  {label}
                  <input type="number" min={1} value={val}
                    onChange={(e) => setter(parseInt(e.target.value, 10) || 1)}
                    style={{ width: '100%', marginTop: 2 }} />
                </label>
              ))}
            </div>
          </details>

          {/* Model overrides */}
          <details>
            <summary style={{ cursor: 'pointer', color: 'var(--text-accent)', marginBottom: '0.45rem', fontWeight: 600 }}>
              Model Overrides
            </summary>
            <div style={{ display: 'grid', gap: '0.5rem' }}>
              {[
                ['Planner model', plannerModel, setPlannerModel],
                ['Character image model', charsModel, setCharsModel],
                ['Scene image model', scenesModel, setScenesModel],
              ].map(([label, val, setter]) => (
                <label key={label} style={{ fontSize: '0.83rem' }}>
                  {label}
                  <input type="text" value={val} onChange={(e) => setter(e.target.value)}
                    style={{ width: '100%', marginTop: 2 }} />
                </label>
              ))}
            </div>
          </details>

          {/* Run controls */}
          <div style={{ marginTop: '0.5rem', display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
            <button
              className="btn btn-primary"
              type="button"
              disabled={running || Boolean(stepBusy)}
              onClick={startFullPipeline}
              style={{ display: 'flex', alignItems: 'center', gap: 6, justifyContent: 'center' }}
            >
              {(running || stepBusy === 'all') ? <Loader2 size={16} className="spin" /> : <Play size={16} />}
              Run Full Pipeline
            </button>
            {(running || Boolean(stepBusy)) && (
              <button className="btn" type="button" onClick={abortJob}
                style={{ display: 'flex', alignItems: 'center', gap: 6, justifyContent: 'center' }}>
                <StopCircle size={16} /> Abort
              </button>
            )}
          </div>

          {/* Individual step buttons */}
          <details>
            <summary style={{ cursor: 'pointer', color: 'var(--text-accent)', fontWeight: 600, marginBottom: '0.45rem' }}>
              Run Individual Steps
            </summary>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.4rem' }}>
              {PIPELINE_STEPS.map((s) => (
                <button
                  key={s}
                  className="btn"
                  type="button"
                  disabled={Boolean(stepBusy) || running}
                  onClick={() => runStep(s)}
                  style={{
                    fontSize: '0.82rem',
                    borderLeft: stepDone(s) ? '3px solid #4caf50' : '3px solid transparent',
                    display: 'flex', alignItems: 'center', gap: 4,
                  }}
                >
                  {stepRunning(s) ? <Loader2 size={12} className="spin" /> : <RotateCcw size={12} />}
                  {s}
                </button>
              ))}
            </div>
          </details>

        </div>
      </aside>

      {/* ── Main content ── */}
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minWidth: 0, gap: '0.75rem' }}>
        {/* Log console */}
        <div className="glass-panel" style={{ flex: '0 0 220px', padding: '0.75rem', overflowY: 'auto' }} ref={scrollRef}>
          <div style={{ fontSize: '0.78rem', color: 'var(--text-muted)', marginBottom: 4 }}>Pipeline log</div>
          {logs.length === 0 && (
            <div style={{ color: 'var(--text-muted)', fontSize: '0.82rem' }}>No output yet. Run a step or the full pipeline.</div>
          )}
          {logs.map((l, i) => (
            <div key={i} style={{
              fontSize: '0.8rem', fontFamily: 'monospace', lineHeight: 1.5,
              color: l.type === 'error' ? '#ff8080' : l.type === 'success' ? '#80ff80' : l.type === 'system' ? '#8ab4f8' : 'var(--text-primary)',
            }}>{l.msg}</div>
          ))}
        </div>

        {/* File tree + preview */}
        <div style={{ flex: 1, minHeight: 0, display: 'flex', gap: '0.75rem' }}>
          <div className="glass-panel" style={{ width: 260, overflowY: 'auto' }}>
            {sessionPath ? (
              <SessionTreeView
                sessionPath={sessionPath}
                mediaBase={MEDIA_BASE}
                refreshToken={treeRefreshToken}
                onFileClick={(item) => {
                  if (!item.is_dir) setSelectedFile(item);
                }}
              />
            ) : (
              <div style={{ padding: '1rem', color: 'var(--text-muted)', fontSize: '0.85rem' }}>
                No active session. Start a new session to see files here.
              </div>
            )}
          </div>
          <div className="glass-panel" style={{ flex: 1, overflowY: 'auto', padding: '0.75rem' }}>
            {selectedFile ? (
              <FilePreviewPane file={selectedFile} mediaBase={MEDIA_BASE} />
            ) : (
              <div style={{ color: 'var(--text-muted)', fontSize: '0.85rem' }}>
                Select a file in the tree to preview it here.
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
