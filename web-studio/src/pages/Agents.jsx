import { useState, useEffect, useRef } from 'react';
import { Play, SquareTerminal, Loader2, StopCircle, Lock, Unlock } from 'lucide-react';
import axios from 'axios';
import { useNavigate, useParams } from 'react-router-dom';
import SessionTreeView from '../components/SessionTreeView';
import FilePreviewPane from '../components/FilePreviewPane';

const API_BASE = 'http://localhost:8000/api';
const WS_BASE = 'ws://localhost:8000/api';
const MEDIA_BASE = 'http://localhost:8000/media';
const LIBRARY_MEDIA_BASE = 'http://localhost:8000/library-media';
const AGENTS_LIST = [
  { id: 'autoAnimator', name: 'AutoAnimator', desc: 'Focused preview-driven animator powered by Narrative Manga backend.' },
];
const EXECUTION_AGENT_BY_UI_AGENT = {
  autoAnimator: 'narrativeManga',
};
const VALID_AGENT_IDS = new Set(AGENTS_LIST.map((a) => a.id));

function stylePreviewBackground(cloudStyle) {
  if (cloudStyle?.includes('storm') || cloudStyle?.includes('neo')) {
    return 'linear-gradient(135deg, #1f2d4a, #3f5f89)';
  }
  if (cloudStyle?.includes('sun')) {
    return 'linear-gradient(135deg, #cf9f2f, #f1d39a)';
  }
  return 'linear-gradient(135deg, #445ec5, #7ea6f0)';
}

function sanitizeImagePath(path) {
  if (typeof path !== 'string') return '';
  const trimmed = path.trim();
  return trimmed.length > 0 ? trimmed : '';
}

function packPreviewImage(pack) {
  const fromPack = sanitizeImagePath(pack?.preview_assets?.thumbnail);
  if (fromPack) return fromPack;

  const fromCharacter = (pack?.characters || [])
    .flatMap((ch) => ch?.anchor_images || [])
    .map(sanitizeImagePath)
    .find(Boolean);

  return fromCharacter || '';
}

function mediaUrl(path) {
  const safe = sanitizeImagePath(path);
  if (!safe) return '';
  const encoded = safe.split('/').map(encodeURIComponent).join('/');
  if (safe.startsWith('library/')) {
    return `${LIBRARY_MEDIA_BASE}/${encoded.slice('library/'.length)}`;
  }
  return `${MEDIA_BASE}/${encoded}`;
}

export default function Agents() {
  const navigate = useNavigate();
  const { agentId, sessionMode: modeParam, sessionId } = useParams();

  const [page, setPage] = useState('selector');
  const [running, setRunning] = useState(false);
  const [logs, setLogs] = useState([]);
  const [jobId, setJobId] = useState(null);
  const [selectedAgent, setSelectedAgent] = useState('autoAnimator');
  const [sessionMode, setSessionMode] = useState('new');
  const [sessionPath, setSessionPath] = useState('');
  const [availableSessions, setAvailableSessions] = useState([]);
  const [styleProfiles, setStyleProfiles] = useState([]);
  const [characterPacks, setCharacterPacks] = useState([]);
  const [sessionChars, setSessionChars] = useState([]);

  const [narrativePrompt, setNarrativePrompt] = useState('A sci-fi detective embarks on a neon city mystery.');
  const [preset, setPreset] = useState('cinematic_anime');
  const [format, setFormat] = useState('tiktok');
  const [cloudStyle, setCloudStyle] = useState('cloud-fluffy-default');
  const [fontStyle, setFontStyle] = useState('font-inter-clean');
  const [subtitleStyle, setSubtitleStyle] = useState('subtitle-neon-clean');
  const [narrationMode, setNarrationMode] = useState('hybrid_subtitles_clouds');
  const [characterPackId, setCharacterPackId] = useState('');
  const [reuseSessionChars, setReuseSessionChars] = useState(false);
  const [selectedSessionCharacter, setSelectedSessionCharacter] = useState('');
  const [enableMusic, setEnableMusic] = useState(false);
  const [maxImageRequests, setMaxImageRequests] = useState(50);
  const [maxCharsPerEpisode, setMaxCharsPerEpisode] = useState(5);
  const [maxPanelsPerEpisode, setMaxPanelsPerEpisode] = useState(50);
  const [maxEpisodeDurationMins, setMaxEpisodeDurationMins] = useState(5);
  const [treeRefreshToken, setTreeRefreshToken] = useState(0);

  const [selectedFile, setSelectedFile] = useState(null);
  const [configPreview, setConfigPreview] = useState(null);
  const [buildpackOptions, setBuildpackOptions] = useState(null);
  const [buildpackResolution, setBuildpackResolution] = useState('youtube_video');
  const [buildpackCharacterId, setBuildpackCharacterId] = useState('');
  const [buildpackSceneId, setBuildpackSceneId] = useState('');
  const [buildpackFontStyle, setBuildpackFontStyle] = useState('font-ubuntu-mono');
  const [buildpackSubtitleStyle, setBuildpackSubtitleStyle] = useState('sub-neon-pop');
  const [buildpackCloudStyle, setBuildpackCloudStyle] = useState('cloud-none');
  const [buildpackSampleText, setBuildpackSampleText] = useState('The city whispered: move now.');
  const [buildpackSampleSize, setBuildpackSampleSize] = useState(48);
  const [buildpackPreviewBlobUrl, setBuildpackPreviewBlobUrl] = useState('');
  const [buildpackPreviewLoading, setBuildpackPreviewLoading] = useState(false);
  const [buildpackPreviewError, setBuildpackPreviewError] = useState('');
  const [subtitleX, setSubtitleX] = useState(0.03958333333333333);
  const [subtitleY, setSubtitleY] = useState(0.8787037037037037);
  const [subtitleScale, setSubtitleScale] = useState(1.25);
  const [cloudX, setCloudX] = useState(0.3796875);
  const [cloudY, setCloudY] = useState(0.17962962962962964);
  const [cloudW, setCloudW] = useState(0.55);
  const [cloudH, setCloudH] = useState(0.17962962962962964);
  const [savingLayout, setSavingLayout] = useState(false);
  const [buildpackSaveMessage, setBuildpackSaveMessage] = useState('');
  const [workflowHashes, setWorkflowHashes] = useState({});
  const [stepBusy, setStepBusy] = useState('');
  const [stepReset, setStepReset] = useState({ planner: false, chars: false, scenes: false, audio: false, texts: false, video: false });
  const [episodesMode, setEpisodesMode] = useState('new');
  const [episodeMode, setEpisodeMode] = useState(true);
  const [targetEpisode, setTargetEpisode] = useState('');
  const [sourceCharSession, setSourceCharSession] = useState('');
  const [sourceCharPath, setSourceCharPath] = useState('');
  const [sectionLocks, setSectionLocks] = useState({
    step0: false,
    planner: false,
    chars: false,
    scenes: false,
    audio: false,
    texts: false,
    video: false,
  });

  const ws = useRef(null);
  const scrollRef = useRef(null);
  const buildpackRequestSeq = useRef(0);

  const goToAgentWorkspace = (agent, mode, path = '') => {
    const safeMode = mode === 'existing' ? 'existing' : 'new';
    if (safeMode === 'existing') {
      const derivedSessionId = (path || '').split('/')[0];
      if (derivedSessionId) {
        navigate(`/agents/${encodeURIComponent(agent)}/${safeMode}/${encodeURIComponent(derivedSessionId)}`);
        return;
      }
    }
    navigate(`/agents/${encodeURIComponent(agent)}/${safeMode}`);
  };

  const startAgent = async (agentName) => {
    try {
      setRunning(true);
      setLogs((prev) => [...prev, { type: 'system', msg: `Running full pipeline via ${agentName}...` }]);
      await runNarrativeStep('all');
    } catch (err) {
      setLogs((prev) => [...prev, { type: 'error', msg: `Failed to start: ${err.message}` }]);
      setRunning(false);
      return;
    }
    setRunning(false);
  };

  const handleTreeItemClick = (item) => {
    if (item.is_dir) {
      setSelectedFile(null);
      return;
    }
    setSelectedFile(item);
    setConfigPreview(null);
  };

  const nudge = (value, delta, min = 0, max = 0.95) => Math.max(min, Math.min(max, Number((value + delta).toFixed(4))));

  const refreshWorkflowHashes = async (path) => {
    if (!path) {
      setWorkflowHashes({});
      return;
    }
    try {
      const res = await axios.get(`${API_BASE}/agents/narrative/checkpoints`, { params: { session_path: path } });
      setWorkflowHashes(res.data?.hashes || {});
    } catch {
      setWorkflowHashes({});
    }
  };

  const runNarrativeStep = async (step, opts = {}) => {
    setStepBusy(step);
    setBuildpackSaveMessage('');
    try {
      const isExisting = sessionMode === 'existing' || Boolean(sessionPath);
      const effectiveEpisodesMode = isExisting ? episodesMode : 'new';
      const effectiveEpisodeMode = isExisting ? episodeMode : true;
      const payload = {
        session_mode: isExisting ? 'existing' : 'new',
        session_path: isExisting ? sessionPath : null,
        step,
        reset: Boolean(stepReset[step]),
        prompt: narrativePrompt,
        episodes: effectiveEpisodesMode,
        episode: targetEpisode ? parseInt(targetEpisode, 10) : null,
        preset,
        format,
        enable_music: enableMusic,
        narration_mode: buildpackCloudStyle === 'cloud-none' ? 'subtitles_only' : 'hybrid_subtitles_clouds',
        buildpack_resolution: buildpackResolution,
        cloud_style: buildpackCloudStyle,
        font_style: buildpackFontStyle,
        subtitle_style: buildpackSubtitleStyle,
        subtitle_scale: subtitleScale,
        episode_mode: effectiveEpisodeMode,
        max_image_requests: maxImageRequests,
        max_chars_per_episode: maxCharsPerEpisode,
        max_panels_per_episode: maxPanelsPerEpisode,
        max_episode_duration_mins: maxEpisodeDurationMins,
      };

      const res = await axios.post(`${API_BASE}/agents/narrative/run-step`, payload);
      const nextPath = res.data?.session_path || sessionPath;
      if (nextPath && nextPath !== sessionPath) {
        setSessionPath(nextPath);
      }
      if (res.data?.hashes) {
        setWorkflowHashes(res.data.hashes);
      } else if (nextPath) {
        await refreshWorkflowHashes(nextPath);
      }

      const status = res.data?.status || 'success';
      const note = status === 'error' ? (res.data?.stderr || 'Step failed') : `Step '${step}' completed`;
      setLogs((prev) => [...prev, { type: status === 'error' ? 'error' : 'success', msg: note }]);

      if (nextPath) {
        const sid = nextPath.split('/')[0];
        goToAgentWorkspace(selectedAgent, 'existing', nextPath);
        if (sid) {
          navigate(`/agents/${encodeURIComponent(selectedAgent)}/existing/${encodeURIComponent(sid)}`, { replace: true });
        }
      }
    } catch (e) {
      setLogs((prev) => [...prev, { type: 'error', msg: `Step '${step}' failed: ${e.message}` }]);
    } finally {
      setStepBusy('');
    }
  };

  const copyCharacterToSession = async () => {
    if (!sourceCharPath) return;
    try {
      const target = sessionPath || null;
      const res = await axios.post(`${API_BASE}/agents/narrative/copy-character`, {
        source_path: sourceCharPath,
        target_session_path: target,
      });
      const nextPath = res.data?.target_session_path || sessionPath;
      if (nextPath && nextPath !== sessionPath) {
        setSessionPath(nextPath);
      }
      setBuildpackSaveMessage(`Character copied: ${res.data?.copied_to || ''}`);
      if (nextPath) {
        await refreshWorkflowHashes(nextPath);
      }
    } catch (e) {
      setBuildpackSaveMessage(`Character copy failed: ${e.message}`);
    }
  };

  const saveBuildpackToSession = async () => {
    setSavingLayout(true);
    setBuildpackSaveMessage('');
    try {
      const res = await axios.post(`${API_BASE}/overlay-samples/save`, {
        session_mode: sessionMode,
        session_path: sessionPath || null,
        resolution: buildpackResolution,
        character_id: buildpackCharacterId || null,
        scene_id: buildpackSceneId || null,
        fontstyle: buildpackFontStyle,
        subtitle_style: buildpackSubtitleStyle,
        cloud_style: buildpackCloudStyle,
        sample_text: buildpackSampleText,
        sample_size: Number(buildpackSampleSize) || 48,
        subtitle_x: subtitleX,
        subtitle_y: subtitleY,
        subtitle_scale: subtitleScale,
        cloud_x: cloudX,
        cloud_y: cloudY,
        cloud_w: cloudW,
        cloud_h: cloudH,
      });

      const saved = res.data?.saved_path;
      const sid = res.data?.session_id;
      setBuildpackSaveMessage(saved ? `Saved to session ${sid}: ${saved}` : 'Saved.');
    } catch (e) {
      setBuildpackSaveMessage(`Save failed: ${e.message}`);
    } finally {
      setSavingLayout(false);
    }
  };

  useEffect(() => {
    if (!jobId) return;

    ws.current = new WebSocket(`${WS_BASE}/agents/stream/${jobId}`);

    ws.current.onmessage = (event) => {
      const data = JSON.parse(event.data);
      setLogs((prev) => [...prev, data]);
      if (data.type === 'success' || data.type === 'error') {
        setRunning(false);
      }
    };

    ws.current.onerror = () => {
      setLogs((prev) => [...prev, { type: 'error', msg: 'WebSocket disconnected abnormally.' }]);
      setRunning(false);
    };

    return () => {
      if (ws.current) ws.current.close();
    };
  }, [jobId]);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [logs]);

  useEffect(() => {
    const hasWorkspaceRoute = Boolean(agentId && modeParam);
    if (!hasWorkspaceRoute) {
      setPage('selector');
      return;
    }

    if (!VALID_AGENT_IDS.has(agentId)) {
      setPage('selector');
      return;
    }

    const normalizedMode = modeParam === 'existing' ? 'existing' : 'new';
    const runtimeAgent = EXECUTION_AGENT_BY_UI_AGENT[agentId] || agentId;
    setPage('workspace');
    setSelectedAgent(agentId);
    setSessionMode(normalizedMode);
    if (normalizedMode === 'existing' && sessionId) {
      setSessionPath(`${sessionId}/${runtimeAgent}`);
    } else {
      setSessionPath('');
    }
  }, [agentId, modeParam, sessionId]);

  useEffect(() => {
    setSelectedFile(null);
  }, [sessionMode, sessionPath]);

  useEffect(() => {
    if (sessionPath) {
      refreshWorkflowHashes(sessionPath);
    } else {
      setWorkflowHashes({});
      setSectionLocks({ step0: false, planner: false, chars: false, scenes: false, audio: false, texts: false, video: false });
    }
  }, [sessionPath]);

  useEffect(() => {
    if (sessionMode !== 'existing') {
      setEpisodesMode('new');
      setEpisodeMode(true);
      setTargetEpisode('');
    }
  }, [sessionMode]);

  useEffect(() => {
    const loadLocks = async () => {
      if (!sessionPath) return;
      try {
        const res = await axios.get(`${API_BASE}/agents/narrative/locks`, { params: { session_path: sessionPath } });
        const incoming = res.data?.locks || {};
        setSectionLocks((prev) => ({ ...prev, ...incoming }));
      } catch {
        setSectionLocks((prev) => ({ ...prev }));
      }
    };
    loadLocks();
  }, [sessionPath]);

  const toggleSectionLock = async (sectionKey) => {
    const next = { ...sectionLocks, [sectionKey]: !sectionLocks[sectionKey] };
    setSectionLocks(next);
    if (!sessionPath) return;
    try {
      await axios.post(`${API_BASE}/agents/narrative/locks`, {
        session_path: sessionPath,
        locks: next,
      });
    } catch {
      // Keep local lock state even if persistence fails.
    }
  };

  useEffect(() => {
    if (!running || page !== 'workspace' || sessionMode !== 'existing' || !sessionPath) {
      return;
    }

    const intervalId = setInterval(() => {
      setTreeRefreshToken((prev) => prev + 1);
    }, 3000);

    return () => clearInterval(intervalId);
  }, [running, page, sessionMode, sessionPath]);

  useEffect(() => {
    const loadSessions = async () => {
      try {
        const root = await axios.get(`${API_BASE}/sessions/tree`);
        const roots = root.data.filter((item) => item.is_dir);
        const sessionOptions = [];

        for (const r of roots) {
          try {
            const sub = await axios.get(`${API_BASE}/sessions/tree`, { params: { path: r.path } });
            const runtimeAgent = EXECUTION_AGENT_BY_UI_AGENT[selectedAgent] || selectedAgent;
            const match = sub.data.find((item) => item.is_dir && item.name === runtimeAgent);
            if (match) {
              sessionOptions.push(match.path);
            }
          } catch {
            // ignore missing session folders
          }
        }

        setAvailableSessions(sessionOptions);
        if (sessionMode === 'existing') {
          const runtimeAgent = EXECUTION_AGENT_BY_UI_AGENT[selectedAgent] || selectedAgent;
          const urlDerivedPath = sessionId ? `${sessionId}/${runtimeAgent}` : '';
          const nextPath = sessionOptions.includes(urlDerivedPath)
            ? urlDerivedPath
            : (sessionOptions[0] || '');

          setSessionPath(nextPath);

          if (nextPath) {
            const nextSessionId = nextPath.split('/')[0];
            if (nextSessionId !== sessionId) {
              navigate(`/agents/${encodeURIComponent(selectedAgent)}/existing/${encodeURIComponent(nextSessionId)}`, { replace: true });
            }
          }
        }
      } catch {
        setAvailableSessions([]);
      }
    };

    if (page === 'workspace') {
      loadSessions();
    }
  }, [navigate, page, selectedAgent, sessionId, sessionMode]);

  useEffect(() => {
    const loadLibraryOptions = async () => {
      try {
        const [profilesRes, packsRes] = await Promise.all([
          axios.get(`${API_BASE}/styles/profiles`),
          axios.get(`${API_BASE}/characters/packs`),
        ]);

        const profiles = profilesRes.data || [];
        const packs = packsRes.data || [];
        setStyleProfiles(profiles);
        setCharacterPacks(packs);
      } catch {
        setStyleProfiles([]);
        setCharacterPacks([]);
      }
    };

    if (page === 'workspace') {
      loadLibraryOptions();
    }
  }, [page]);

  useEffect(() => {
    const loadBuildpackOptions = async () => {
      try {
        const res = await axios.get(`${API_BASE}/overlay-samples/buildpacks/options`);
        const options = res.data || null;
        setBuildpackOptions(options);

        if (options?.resolutions?.length && !options.resolutions.some((r) => r.key === buildpackResolution)) {
          setBuildpackResolution(options.resolutions[0].key);
        }
        if (options?.fontstyles?.length && !options.fontstyles.some((f) => f.id === buildpackFontStyle)) {
          setBuildpackFontStyle(options.fontstyles[0].id);
        }
        if (options?.subtitle_styles?.length && !options.subtitle_styles.some((s) => s.id === buildpackSubtitleStyle)) {
          setBuildpackSubtitleStyle(options.subtitle_styles[0].id);
        }
        if (options?.cloud_styles?.length && !options.cloud_styles.some((c) => c.id === buildpackCloudStyle)) {
          setBuildpackCloudStyle(options.cloud_styles[0].id);
        }
      } catch {
        setBuildpackOptions(null);
      }
    };

    if (page === 'workspace') {
      loadBuildpackOptions();
    }
  }, [page]);

  useEffect(() => {
    if (page !== 'workspace') return;
    if (sessionMode !== 'new') {
      setBuildpackPreviewBlobUrl('');
      setBuildpackPreviewError('');
      return;
    }

    const timerId = setTimeout(async () => {
      const reqId = ++buildpackRequestSeq.current;
      try {
        setBuildpackPreviewLoading(true);
        setBuildpackPreviewError('');
        const res = await axios.post(`${API_BASE}/overlay-samples/`, {
          session_mode: sessionMode,
          session_path: sessionPath || null,
          resolution: buildpackResolution,
          character_id: buildpackCharacterId || null,
          scene_id: buildpackSceneId || null,
          fontstyle: buildpackFontStyle,
          subtitle_style: buildpackSubtitleStyle,
          cloud_style: buildpackCloudStyle,
          sample_text: buildpackSampleText,
          sample_size: Number(buildpackSampleSize) || 48,
          subtitle_x: subtitleX,
          subtitle_y: subtitleY,
          subtitle_scale: subtitleScale,
          cloud_x: cloudX,
          cloud_y: cloudY,
          cloud_w: cloudW,
          cloud_h: cloudH,
        });

        if (res.data?.skipped) {
          if (reqId !== buildpackRequestSeq.current) return;
          setBuildpackPreviewBlobUrl('');
          return;
        }

        if (reqId !== buildpackRequestSeq.current) return;
        const blob = res.data?.preview_blob || '';
        const mime = res.data?.preview_mime || 'image/png';
        const dataUrl = blob ? `data:${mime};base64,${blob}` : '';
        setBuildpackPreviewBlobUrl(dataUrl);
        if (dataUrl) {
          setSelectedFile(null);
          setConfigPreview(null);
        }
      } catch (e) {
        if (reqId !== buildpackRequestSeq.current) return;
        setBuildpackPreviewError(`BuildPack preview failed: ${e.message}`);
      } finally {
        if (reqId !== buildpackRequestSeq.current) return;
        setBuildpackPreviewLoading(false);
      }
    }, 320);

    return () => clearTimeout(timerId);
  }, [
    buildpackCharacterId,
    buildpackCloudStyle,
    buildpackFontStyle,
    buildpackResolution,
    buildpackSampleSize,
    buildpackSampleText,
    buildpackSceneId,
    buildpackSubtitleStyle,
    cloudH,
    cloudW,
    cloudX,
    cloudY,
    page,
    sessionMode,
    sessionPath,
    subtitleScale,
    subtitleX,
    subtitleY,
  ]);

  useEffect(() => {
    const loadSessionChars = async () => {
      if (sessionMode !== 'existing' || !sessionPath) {
        setSessionChars([]);
        return;
      }

      try {
        const res = await axios.get(`${API_BASE}/characters/session-images`, { params: { session_path: sessionPath } });
        const data = res.data || [];
        setSessionChars(data);

        if (data.length > 0 && !selectedSessionCharacter) {
          setSelectedSessionCharacter(data[0].path);
        }
      } catch {
        setSessionChars([]);
      }
    };

    loadSessionChars();
  }, [sessionMode, sessionPath, selectedSessionCharacter]);

  const fontProfiles = styleProfiles.filter((p) => p.category === 'font');
  const cloudProfiles = styleProfiles.filter((p) => p.category === 'cloud');
  const subtitleProfiles = styleProfiles.filter((p) => p.category === 'subtitle');

  const selectedCloudProfile = cloudProfiles.find((profile) => profile.id === cloudStyle) || null;
  const selectedFontProfile = fontProfiles.find((profile) => profile.id === fontStyle) || null;
  const selectedSubtitleProfile = subtitleProfiles.find((profile) => profile.id === subtitleStyle) || null;
  const previewableCharacterPacks = characterPacks.filter((pack) => Boolean(packPreviewImage(pack)));
  const sourceCharOptions = (buildpackOptions?.characters || []);
  const sourceCharSessions = Array.from(new Set(sourceCharOptions.map((item) => {
    const p = (item.path || '').split('/');
    return p.length > 1 ? p[1] : '';
  }).filter(Boolean)));
  const filteredSourceChars = sourceCharSession
    ? sourceCharOptions.filter((item) => (item.path || '').split('/')[1] === sourceCharSession)
    : sourceCharOptions;

  useEffect(() => {
    if (!sourceCharSession && sourceCharSessions.length > 0) {
      setSourceCharSession(sourceCharSessions[0]);
    }
  }, [sourceCharSession, sourceCharSessions]);

  useEffect(() => {
    if (!characterPackId) return;
    if (!previewableCharacterPacks.some((pack) => pack.id === characterPackId)) {
      setCharacterPackId('');
    }
  }, [characterPackId, previewableCharacterPacks]);

  if (page === 'selector') {
    return (
      <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: '100%', padding: '1.5rem' }}>
        <div className="glass-panel" style={{ width: '520px', padding: '1.5rem' }}>
          <h2 style={{ margin: 0, marginBottom: '1rem', color: 'var(--text-accent)' }}>Select an Agent</h2>
          <div style={{ display: 'grid', gap: '0.75rem' }}>
            {AGENTS_LIST.map((agt) => (
              <button
                key={agt.id}
                className="btn btn-primary"
                style={{ width: '100%', textAlign: 'left', padding: '0.8rem' }}
                onClick={() => goToAgentWorkspace(agt.id, 'new')}
              >
                <strong>{agt.name}</strong>
                <div style={{ marginTop: '0.25rem', fontSize: '0.85rem', color: 'var(--text-muted)' }}>{agt.desc}</div>
              </button>
            ))}
          </div>
        </div>
      </div>
    );
  }

  return (
    <div style={{ display: 'flex', gap: '1rem', height: '100%' }}>
      <aside className="glass-panel" style={{ width: 390, display: 'flex', flexDirection: 'column' }}>
        <section style={{ padding: '1rem', borderBottom: '1px solid var(--border-color)', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <div>
            <h2 style={{ margin: 0, display: 'flex', alignItems: 'center', gap: '8px' }}>
              <Play size={20} className="text-accent" /> {AGENTS_LIST.find((a) => a.id === selectedAgent)?.name}
            </h2>
            <p style={{ marginTop: '0.45rem', color: 'var(--text-muted)', fontSize: '0.9rem' }}>
              Preview-first configuration for higher quality narration and character consistency.
            </p>
          </div>
          <button className="btn" onClick={() => navigate('/agents')} style={{ height: '2rem' }}>
            Back
          </button>
        </section>

        <section style={{ padding: '1rem', overflowY: 'auto', flex: 1 }}>
          <details open style={{ marginBottom: '0.8rem' }}>
            <summary style={{ cursor: 'pointer', color: 'var(--text-accent)', marginBottom: '0.55rem', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
              <span>Step 0 - Run Setup + BuildPack</span>
              <button className="btn" type="button" onClick={(e) => { e.preventDefault(); e.stopPropagation(); toggleSectionLock('step0'); }} style={{ padding: '0.2rem 0.35rem' }}>
                {sectionLocks.step0 ? <Lock size={14} /> : <Unlock size={14} />}
              </button>
            </summary>
            <fieldset disabled={sectionLocks.step0} style={{ border: 'none', padding: 0, margin: 0 }}>
            <div className="config-grid" style={{ marginBottom: '0.8rem' }}>
              <div className="config-control">
                <label>Session Mode</label>
                <select
                  value={sessionMode}
                  onChange={(e) => {
                    const nextMode = e.target.value;
                    if (nextMode === 'existing') {
                      goToAgentWorkspace(selectedAgent, 'existing', availableSessions[0] || '');
                    } else {
                      goToAgentWorkspace(selectedAgent, 'new');
                    }
                  }}
                >
                  <option value="new">New Session</option>
                  <option value="existing">Use Existing Session</option>
                </select>
              </div>
              {sessionMode === 'existing' && (
                <div className="config-control">
                  <label>Existing Session</label>
                  <select
                    value={sessionPath}
                    onChange={(e) => {
                      const nextPath = e.target.value;
                      setSessionPath(nextPath);
                      goToAgentWorkspace(selectedAgent, 'existing', nextPath);
                    }}
                  >
                    {availableSessions.length === 0 && <option value="">No sessions found</option>}
                    {availableSessions.map((s) => (
                      <option key={s} value={s}>{s}</option>
                    ))}
                  </select>
                </div>
              )}
            </div>

            {sessionMode === 'existing' ? (
              <div style={{ color: 'var(--text-muted)', fontSize: '0.85rem' }}>
                BuildPack preview is available only for New Session mode. Existing sessions continue using direct file preview flow.
              </div>
            ) : (
              <>
                <div className="config-grid">
                  <div className="config-control">
                    <label>Resolution</label>
                    <select value={buildpackResolution} onChange={(e) => setBuildpackResolution(e.target.value)}>
                      {(buildpackOptions?.resolutions || []).map((res) => (
                        <option key={res.key} value={res.key}>{res.label}</option>
                      ))}
                    </select>
                  </div>
                </div>

                <div className="config-grid" style={{ marginTop: '0.75rem' }}>
                  <div className="config-control">
                    <label>Scene</label>
                    <select value={buildpackSceneId} onChange={(e) => setBuildpackSceneId(e.target.value)}>
                      <option value="">Auto Background</option>
                      {(buildpackOptions?.scenes || []).map((opt) => (
                        <option key={opt.id} value={opt.id}>{opt.name}</option>
                      ))}
                    </select>
                  </div>
                  <div className="config-control">
                    <label>Font Style</label>
                    <select value={buildpackFontStyle} onChange={(e) => setBuildpackFontStyle(e.target.value)}>
                      {(buildpackOptions?.fontstyles || []).map((opt) => (
                        <option key={opt.id} value={opt.id}>{opt.name}</option>
                      ))}
                    </select>
                  </div>
                </div>

                <div className="config-grid" style={{ marginTop: '0.75rem' }}>
                  <div className="config-control">
                    <label>Subtitle Style</label>
                    <select value={buildpackSubtitleStyle} onChange={(e) => setBuildpackSubtitleStyle(e.target.value)}>
                      {(buildpackOptions?.subtitle_styles || []).map((opt) => (
                        <option key={opt.id} value={opt.id}>{opt.name}</option>
                      ))}
                    </select>
                  </div>
                  <div className="config-control">
                    <label>Cloud Style</label>
                    <select value={buildpackCloudStyle} onChange={(e) => setBuildpackCloudStyle(e.target.value)}>
                      {(buildpackOptions?.cloud_styles || []).map((opt) => (
                        <option key={opt.id} value={opt.id}>{opt.name}</option>
                      ))}
                    </select>
                  </div>
                </div>

                <div className="config-grid" style={{ marginTop: '0.75rem' }}>
                  <div className="config-control">
                    <label>Sample Text</label>
                    <input value={buildpackSampleText} onChange={(e) => setBuildpackSampleText(e.target.value)} />
                  </div>
                  <div className="config-control">
                    <label>Text Size</label>
                    <input type="number" min="14" max="120" value={buildpackSampleSize} onChange={(e) => setBuildpackSampleSize(parseInt(e.target.value, 10) || 48)} />
                  </div>
                </div>

                <div className="config-grid" style={{ marginTop: '0.75rem' }}>
                  <div className="config-control">
                    <label>Subtitle Scale</label>
                    <input type="range" min="0.5" max="2.2" step="0.05" value={subtitleScale} onChange={(e) => setSubtitleScale(parseFloat(e.target.value))} />
                  </div>
                  <div className="config-control">
                    <label>Cloud Width</label>
                    <input type="range" min="0.12" max="0.9" step="0.01" value={cloudW} onChange={(e) => setCloudW(parseFloat(e.target.value))} />
                  </div>
                </div>

                <div className="config-grid" style={{ marginTop: '0.75rem' }}>
                  <div className="config-control">
                    <label>Cloud Height</label>
                    <input type="range" min="0.08" max="0.75" step="0.01" value={cloudH} onChange={(e) => setCloudH(parseFloat(e.target.value))} />
                  </div>
                  <div className="config-control">
                    <label>Position Controls</label>
                    <div style={{ display: 'flex', gap: '0.35rem', flexWrap: 'wrap' }}>
                      <button className="btn" type="button" onClick={() => setSubtitleX((v) => nudge(v, -0.01))}>Subtitle -x</button>
                      <button className="btn" type="button" onClick={() => setSubtitleX((v) => nudge(v, 0.01))}>Subtitle +x</button>
                      <button className="btn" type="button" onClick={() => setSubtitleY((v) => nudge(v, -0.01))}>Subtitle -y</button>
                      <button className="btn" type="button" onClick={() => setSubtitleY((v) => nudge(v, 0.01))}>Subtitle +y</button>
                      <button className="btn" type="button" onClick={() => setCloudX((v) => nudge(v, -0.01))}>Cloud -x</button>
                      <button className="btn" type="button" onClick={() => setCloudX((v) => nudge(v, 0.01))}>Cloud +x</button>
                      <button className="btn" type="button" onClick={() => setCloudY((v) => nudge(v, -0.01))}>Cloud -y</button>
                      <button className="btn" type="button" onClick={() => setCloudY((v) => nudge(v, 0.01))}>Cloud +y</button>
                    </div>
                  </div>
                </div>

                <div style={{ display: 'flex', gap: '0.5rem', marginTop: '0.75rem', flexWrap: 'wrap' }}>
                  <button className="btn" type="button" onClick={saveBuildpackToSession} disabled={savingLayout || buildpackPreviewLoading}>
                    {savingLayout ? 'Saving...' : 'Save As Session Image'}
                  </button>
                </div>

                {buildpackSaveMessage && (
                  <div style={{ marginTop: '0.5rem', color: buildpackSaveMessage.startsWith('Save failed') ? 'var(--danger)' : 'var(--text-accent)', fontSize: '0.8rem' }}>
                    {buildpackSaveMessage}
                  </div>
                )}

                <div style={{ marginTop: '0.6rem', color: 'var(--text-muted)', fontSize: '0.8rem' }}>
                  {buildpackPreviewLoading && 'Generating BuildPack overlay preview...'}
                  {!buildpackPreviewLoading && buildpackPreviewBlobUrl && 'Preview ready'}
                  {!buildpackPreviewLoading && buildpackPreviewError && <span style={{ color: 'var(--danger)' }}>{buildpackPreviewError}</span>}
                </div>
              </>
            )}
            </fieldset>
          </details>

          <hr style={{ border: 'none', borderTop: '1px solid var(--border-color)', margin: '0.35rem 0 0.9rem' }} />

          <details open style={{ marginBottom: '0.8rem' }}>
            <summary style={{ cursor: 'pointer', color: 'var(--text-accent)', marginBottom: '0.55rem', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
              <span>Step 1 - Planner</span>
              <button className="btn" type="button" onClick={(e) => { e.preventDefault(); e.stopPropagation(); toggleSectionLock('planner'); }} style={{ padding: '0.2rem 0.35rem' }}>
                {sectionLocks.planner ? <Lock size={14} /> : <Unlock size={14} />}
              </button>
            </summary>
            <fieldset disabled={sectionLocks.planner} style={{ border: 'none', padding: 0, margin: 0 }}>
            <div className="config-control">
              <label>Narrative Prompt</label>
              <textarea rows={6} value={narrativePrompt} onChange={(e) => setNarrativePrompt(e.target.value)} style={{ width: '100%', resize: 'vertical' }} />
            </div>
            <div className="config-grid" style={{ marginTop: '0.65rem' }}>
              <div className="config-control">
                <label>Episodes</label>
                {sessionMode === 'existing' ? (
                  <select value={episodesMode} onChange={(e) => setEpisodesMode(e.target.value)}>
                    <option value="new">new</option>
                    <option value="continue">continue</option>
                  </select>
                ) : (
                  <input value="new (locked)" disabled />
                )}
              </div>
              <div className="config-control">
                <label>Episode Number (optional)</label>
                <input value={targetEpisode} onChange={(e) => setTargetEpisode(e.target.value)} placeholder="e.g. 2" disabled={sessionMode !== 'existing'} />
              </div>
            </div>
            <div className="config-control" style={{ marginTop: '0.65rem' }}>
              <label>
                <input type="checkbox" checked={sessionMode === 'existing' ? episodeMode : true} onChange={(e) => setEpisodeMode(e.target.checked)} disabled={sessionMode !== 'existing'} />
                <span style={{ marginLeft: 6 }}>
                  Episode Mode (on = continue series, off = single-video mode)
                  {sessionMode !== 'existing' ? ' - locked for new sessions' : ''}
                </span>
              </label>
            </div>
            <div className="config-grid" style={{ marginTop: '0.65rem' }}>
              <div className="config-control">
                <label>Art Style</label>
                <select value={preset} onChange={(e) => setPreset(e.target.value)}>
                  <option value="cinematic_anime">Cinematic Anime</option>
                  <option value="noir_comic">Noir Comic</option>
                  <option value="sci_fi_neon">Sci-Fi Neon</option>
                  <option value="horror_manga">Horror Manga</option>
                </select>
              </div>
            </div>
            <div className="config-grid" style={{ marginTop: '0.65rem' }}>
              <div className="config-control">
                <label>Max Images</label>
                <input type="number" min="1" value={maxImageRequests} onChange={(e) => setMaxImageRequests(parseInt(e.target.value, 10) || 1)} />
              </div>
              <div className="config-control">
                <label>Max Characters</label>
                <input type="number" min="1" value={maxCharsPerEpisode} onChange={(e) => setMaxCharsPerEpisode(parseInt(e.target.value, 10) || 1)} />
              </div>
            </div>
            <div className="config-grid" style={{ marginTop: '0.65rem' }}>
              <div className="config-control">
                <label>Max Panels</label>
                <input type="number" min="1" value={maxPanelsPerEpisode} onChange={(e) => setMaxPanelsPerEpisode(parseInt(e.target.value, 10) || 1)} />
              </div>
              <div className="config-control">
                <label>Max Duration (min)</label>
                <input type="number" min="1" value={maxEpisodeDurationMins} onChange={(e) => setMaxEpisodeDurationMins(parseInt(e.target.value, 10) || 1)} />
              </div>
            </div>
            <div style={{ marginTop: '0.5rem', display: 'flex', gap: '0.5rem', flexWrap: 'wrap' }}>
              <label style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                <input type="checkbox" checked={stepReset.planner} onChange={(e) => setStepReset((s) => ({ ...s, planner: e.target.checked }))} /> reset
              </label>
              <button className="btn" type="button" onClick={() => runNarrativeStep('planner')} disabled={stepBusy === 'planner'}>{stepBusy === 'planner' ? 'Running...' : 'Run Planner'}</button>
              <span style={{ color: 'var(--text-muted)', fontSize: '0.8rem' }}>hash: {workflowHashes.planner || 'n/a'}</span>
            </div>
            </fieldset>
          </details>

          <hr style={{ border: 'none', borderTop: '1px solid var(--border-color)', margin: '0.35rem 0 0.9rem' }} />

          <details open style={{ marginBottom: '0.8rem' }}>
            <summary style={{ cursor: 'pointer', color: 'var(--text-accent)', marginBottom: '0.55rem', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
              <span>Step 2 - Chars</span>
              <button className="btn" type="button" onClick={(e) => { e.preventDefault(); e.stopPropagation(); toggleSectionLock('chars'); }} style={{ padding: '0.2rem 0.35rem' }}>
                {sectionLocks.chars ? <Lock size={14} /> : <Unlock size={14} />}
              </button>
            </summary>
            <fieldset disabled={sectionLocks.chars} style={{ border: 'none', padding: 0, margin: 0 }}>
            {sessionMode === 'existing' ? (
              <div style={{ color: 'var(--text-muted)', fontSize: '0.85rem' }}>
                Character source is controlled by files from selected session.
              </div>
            ) : (
              <>
                <div className="config-control">
                  <label>Character in BuildPack</label>
                  <select value={buildpackCharacterId} onChange={(e) => setBuildpackCharacterId(e.target.value)}>
                    <option value="">None</option>
                    {(buildpackOptions?.characters || []).map((opt) => (
                      <option key={opt.id} value={opt.id}>{opt.name}</option>
                    ))}
                  </select>
                </div>
                <div className="config-grid" style={{ marginTop: '0.65rem' }}>
                  <div className="config-control">
                    <label>Source Session</label>
                    <select value={sourceCharSession} onChange={(e) => setSourceCharSession(e.target.value)}>
                      {sourceCharSessions.map((sid) => (
                        <option key={sid} value={sid}>{sid}</option>
                      ))}
                    </select>
                  </div>
                  <div className="config-control">
                    <label>Source Character</label>
                    <select value={sourceCharPath} onChange={(e) => setSourceCharPath(e.target.value)}>
                      <option value="">Select character file</option>
                      {filteredSourceChars.map((c) => (
                        <option key={c.path} value={c.path}>{c.name}</option>
                      ))}
                    </select>
                  </div>
                </div>
                <div style={{ marginTop: '0.5rem', display: 'flex', gap: '0.5rem', flexWrap: 'wrap' }}>
                  <button className="btn" type="button" onClick={copyCharacterToSession} disabled={!sourceCharPath}>Copy Character To Session</button>
                </div>
              </>
            )}
            <div style={{ marginTop: '0.5rem', display: 'flex', gap: '0.5rem', flexWrap: 'wrap' }}>
              <label style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                <input type="checkbox" checked={stepReset.chars} onChange={(e) => setStepReset((s) => ({ ...s, chars: e.target.checked }))} /> reset
              </label>
              <button className="btn" type="button" onClick={() => runNarrativeStep('chars')} disabled={stepBusy === 'chars'}>{stepBusy === 'chars' ? 'Running...' : 'Run Chars'}</button>
              <span style={{ color: 'var(--text-muted)', fontSize: '0.8rem' }}>hash: {workflowHashes.chars || 'n/a'}</span>
            </div>
            </fieldset>
          </details>

          <hr style={{ border: 'none', borderTop: '1px solid var(--border-color)', margin: '0.35rem 0 0.9rem' }} />

          <details open style={{ marginBottom: '0.8rem' }}>
            <summary style={{ cursor: 'pointer', color: 'var(--text-accent)', marginBottom: '0.55rem', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
              <span>Step 3 - Scenes</span>
              <button className="btn" type="button" onClick={(e) => { e.preventDefault(); e.stopPropagation(); toggleSectionLock('scenes'); }} style={{ padding: '0.2rem 0.35rem' }}>
                {sectionLocks.scenes ? <Lock size={14} /> : <Unlock size={14} />}
              </button>
            </summary>
            <fieldset disabled={sectionLocks.scenes} style={{ border: 'none', padding: 0, margin: 0 }}>
            <div style={{ marginTop: '0.5rem', display: 'flex', gap: '0.5rem', flexWrap: 'wrap' }}>
              <label style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                <input type="checkbox" checked={stepReset.scenes} onChange={(e) => setStepReset((s) => ({ ...s, scenes: e.target.checked }))} /> reset
              </label>
              <button className="btn" type="button" onClick={() => runNarrativeStep('scenes')} disabled={stepBusy === 'scenes'}>{stepBusy === 'scenes' ? 'Running...' : 'Run Scenes'}</button>
              <span style={{ color: 'var(--text-muted)', fontSize: '0.8rem' }}>hash: {workflowHashes.scenes || 'n/a'}</span>
            </div>
            </fieldset>
          </details>

          <hr style={{ border: 'none', borderTop: '1px solid var(--border-color)', margin: '0.35rem 0 0.9rem' }} />

          <details open style={{ marginBottom: '0.8rem' }}>
            <summary style={{ cursor: 'pointer', color: 'var(--text-accent)', marginBottom: '0.55rem', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
              <span>Step 4 - Audio</span>
              <button className="btn" type="button" onClick={(e) => { e.preventDefault(); e.stopPropagation(); toggleSectionLock('audio'); }} style={{ padding: '0.2rem 0.35rem' }}>
                {sectionLocks.audio ? <Lock size={14} /> : <Unlock size={14} />}
              </button>
            </summary>
            <fieldset disabled={sectionLocks.audio} style={{ border: 'none', padding: 0, margin: 0 }}>
            <div style={{ marginTop: '0.5rem', display: 'flex', gap: '0.5rem', flexWrap: 'wrap' }}>
              <label style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                <input type="checkbox" checked={stepReset.audio} onChange={(e) => setStepReset((s) => ({ ...s, audio: e.target.checked }))} /> reset
              </label>
              <button className="btn" type="button" onClick={() => runNarrativeStep('audio')} disabled={stepBusy === 'audio'}>{stepBusy === 'audio' ? 'Running...' : 'Run Audio'}</button>
              <span style={{ color: 'var(--text-muted)', fontSize: '0.8rem' }}>hash: {workflowHashes.audio || 'n/a'}</span>
            </div>
            </fieldset>
          </details>

          <hr style={{ border: 'none', borderTop: '1px solid var(--border-color)', margin: '0.35rem 0 0.9rem' }} />

          <details open style={{ marginBottom: '0.8rem' }}>
            <summary style={{ cursor: 'pointer', color: 'var(--text-accent)', marginBottom: '0.55rem', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
              <span>Step 5 - Texts (Subtitles/Clouds)</span>
              <button className="btn" type="button" onClick={(e) => { e.preventDefault(); e.stopPropagation(); toggleSectionLock('texts'); }} style={{ padding: '0.2rem 0.35rem' }}>
                {sectionLocks.texts ? <Lock size={14} /> : <Unlock size={14} />}
              </button>
            </summary>
            <fieldset disabled={sectionLocks.texts} style={{ border: 'none', padding: 0, margin: 0 }}>
            <div className="config-control" style={{ marginTop: '0.5rem' }}>
              <label>Texts Mode</label>
              <select value={buildpackCloudStyle === 'cloud-none' ? 'subtitles_only' : 'clouds'} onChange={(e) => setBuildpackCloudStyle(e.target.value === 'subtitles_only' ? 'cloud-none' : 'cloud-soft-round')}>
                <option value="subtitles_only">Subtitles Only</option>
                <option value="clouds">Clouds</option>
              </select>
            </div>
            <div style={{ marginTop: '0.5rem', display: 'flex', gap: '0.5rem', flexWrap: 'wrap' }}>
              <label style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                <input type="checkbox" checked={stepReset.texts} onChange={(e) => setStepReset((s) => ({ ...s, texts: e.target.checked }))} /> reset
              </label>
              <button className="btn" type="button" onClick={() => runNarrativeStep('texts')} disabled={stepBusy === 'texts'}>{stepBusy === 'texts' ? 'Running...' : 'Run Texts'}</button>
              <span style={{ color: 'var(--text-muted)', fontSize: '0.8rem' }}>hash: {workflowHashes.texts || 'n/a'}</span>
            </div>
            </fieldset>
          </details>

          <hr style={{ border: 'none', borderTop: '1px solid var(--border-color)', margin: '0.35rem 0 0.9rem' }} />

          <details open style={{ marginBottom: '0.8rem' }}>
            <summary style={{ cursor: 'pointer', color: 'var(--text-accent)', marginBottom: '0.55rem', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
              <span>Step 6 - Video</span>
              <button className="btn" type="button" onClick={(e) => { e.preventDefault(); e.stopPropagation(); toggleSectionLock('video'); }} style={{ padding: '0.2rem 0.35rem' }}>
                {sectionLocks.video ? <Lock size={14} /> : <Unlock size={14} />}
              </button>
            </summary>
            <fieldset disabled={sectionLocks.video} style={{ border: 'none', padding: 0, margin: 0 }}>
            <div className="config-control" style={{ marginTop: '0.5rem' }}>
              <label>Format</label>
              <select value={format} onChange={(e) => setFormat(e.target.value)}>
                <option value="tiktok">TikTok</option>
                <option value="instagram_reels">Instagram Reels</option>
                <option value="youtube_shorts">YouTube Shorts</option>
                <option value="youtube_widescreen">YouTube Widescreen</option>
              </select>
            </div>
            <div className="config-control" style={{ marginTop: '0.5rem' }}>
              <label>
                <input type="checkbox" checked={enableMusic} onChange={(e) => setEnableMusic(e.target.checked)} />
                <span style={{ marginLeft: 6 }}>Enable Music</span>
              </label>
            </div>
            <div style={{ marginTop: '0.5rem', display: 'flex', gap: '0.5rem', flexWrap: 'wrap' }}>
              <label style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                <input type="checkbox" checked={stepReset.video} onChange={(e) => setStepReset((s) => ({ ...s, video: e.target.checked }))} /> reset
              </label>
              <button className="btn" type="button" onClick={() => runNarrativeStep('video')} disabled={stepBusy === 'video'}>{stepBusy === 'video' ? 'Running...' : 'Run Video'}</button>
              <button className="btn" type="button" onClick={() => runNarrativeStep('all')} disabled={stepBusy === 'all'}>{stepBusy === 'all' ? 'Running...' : 'Run End-to-End'}</button>
              <span style={{ color: 'var(--text-muted)', fontSize: '0.8rem' }}>hash: {workflowHashes.video || 'n/a'}</span>
            </div>
            </fieldset>
          </details>

          {false && (
          <details open style={{ marginBottom: '0.8rem' }}>
            <summary style={{ cursor: 'pointer', color: 'var(--text-accent)', marginBottom: '0.55rem' }}>Narration & Style (with Preview)</summary>
            <div className="config-grid">
              <div className="config-control">
                <label>Cloud Style</label>
                <select value={cloudStyle} onChange={(e) => setCloudStyle(e.target.value)}>
                  {cloudProfiles.length === 0 && (
                    <>
                      <option value="fluffy">Fluffy</option>
                      <option value="stormy">Stormy</option>
                      <option value="sunny">Sunny</option>
                    </>
                  )}
                  {cloudProfiles.map((profile) => (
                    <option key={profile.id} value={profile.id}>{profile.name}</option>
                  ))}
                </select>
              </div>
              <div className="config-control">
                <label>Font Style</label>
                <select value={fontStyle} onChange={(e) => setFontStyle(e.target.value)}>
                  {fontProfiles.length === 0 && (
                    <>
                      <option value="Inter">Inter</option>
                      <option value="Roboto">Roboto</option>
                      <option value="Courier New">Courier New</option>
                      <option value="Comic Sans MS">Comic Sans MS</option>
                    </>
                  )}
                  {fontProfiles.map((profile) => (
                    <option key={profile.id} value={profile.id}>{profile.name}</option>
                  ))}
                </select>
              </div>
            </div>

            <div className="config-grid" style={{ marginTop: '0.8rem' }}>
              <div className="config-control">
                <label>Narration Mode</label>
                <select value={narrationMode} onChange={(e) => setNarrationMode(e.target.value)}>
                  <option value="subtitles_only">Subtitles Only</option>
                  <option value="speech_clouds_only">Speech Clouds Only</option>
                  <option value="thought_clouds_only">Thought Clouds Only</option>
                  <option value="hybrid_subtitles_clouds">Hybrid Subtitles + Clouds</option>
                </select>
              </div>
              <div className="config-control">
                <label>Subtitle Style</label>
                <select value={subtitleStyle} onChange={(e) => setSubtitleStyle(e.target.value)}>
                  {subtitleProfiles.length === 0 && <option value="subtitle-neon-clean">Neon Clean Subtitle</option>}
                  {subtitleProfiles.map((profile) => (
                    <option key={profile.id} value={profile.id}>{profile.name}</option>
                  ))}
                </select>
              </div>
            </div>

            <div style={{ marginTop: '0.7rem', display: 'flex', gap: '0.5rem', flexWrap: 'wrap' }}>
              <button
                className="btn"
                type="button"
                onClick={() => {
                  setSelectedFile(null);
                  setConfigPreview({
                    type: 'style',
                    title: selectedCloudProfile?.name || 'Cloud Style Preview',
                    text: 'Narration preview sample: The city breathed in neon silence.',
                    thumbnail: selectedCloudProfile?.preview_assets?.thumbnail || null,
                  });
                }}
              >
                Preview Cloud Style
              </button>
              <button
                className="btn"
                type="button"
                onClick={() => {
                  setSelectedFile(null);
                  setConfigPreview({
                    type: 'style',
                    title: selectedFontProfile?.name || 'Font Style Preview',
                    text: 'The quick brown fox jumps over the lazy dog.',
                    thumbnail: selectedFontProfile?.preview_assets?.thumbnail || null,
                  });
                }}
              >
                Preview Font Style
              </button>
              <button
                className="btn"
                type="button"
                onClick={() => {
                  setSelectedFile(null);
                  setConfigPreview({
                    type: 'style',
                    title: selectedSubtitleProfile?.name || 'Subtitle Style Preview',
                    text: narrationMode === 'subtitles_only' ? 'Subtitle mode enabled.' : 'Text cloud mode enabled.',
                    thumbnail: selectedSubtitleProfile?.preview_assets?.thumbnail || null,
                  });
                }}
              >
                Preview Subtitle/Text Mode
              </button>
              {selectedCloudProfile?.preview_assets?.thumbnail && (
                <button
                  className="btn"
                  type="button"
                  onClick={() => {
                    setSelectedFile({
                      name: selectedCloudProfile.preview_assets.thumbnail.split('/').pop(),
                      path: selectedCloudProfile.preview_assets.thumbnail,
                      extension: '.png',
                      is_dir: false,
                    });
                    setConfigPreview(null);
                  }}
                >
                  Open Cloud Asset
                </button>
              )}
            </div>

            <div style={{ marginTop: '0.8rem' }}>
              <div style={{ color: 'var(--text-muted)', fontSize: '0.82rem', marginBottom: '0.4rem' }}>Cloud style gallery</div>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, minmax(0,1fr))', gap: '0.4rem' }}>
                {cloudProfiles.slice(0, 10).map((profile) => {
                  const thumb = profile?.preview_assets?.thumbnail;
                  return (
                    <button
                      key={profile.id}
                      className="btn"
                      style={{
                        padding: '0.3rem',
                        border: profile.id === cloudStyle ? '1px solid var(--text-accent)' : '1px solid var(--border-color)',
                        textAlign: 'left',
                      }}
                      onClick={() => {
                        setCloudStyle(profile.id);
                        if (thumb) {
                          setSelectedFile({ name: thumb.split('/').pop(), path: thumb, extension: '.png', is_dir: false });
                          setConfigPreview(null);
                        }
                      }}
                    >
                      {thumb ? (
                        <img src={mediaUrl(thumb)} alt={profile.name} style={{ width: '100%', height: 62, objectFit: 'cover', borderRadius: 6 }} />
                      ) : (
                        <div style={{ width: '100%', height: 62, borderRadius: 6, background: 'var(--bg-surface)', display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--text-muted)', fontSize: '0.72rem' }}>
                          No thumb
                        </div>
                      )}
                      <div style={{ marginTop: '0.2rem', fontSize: '0.72rem', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{profile.name}</div>
                    </button>
                  );
                })}
              </div>
            </div>
          </details>
          )}

          {false && (
          <details open style={{ marginBottom: '0.8rem' }}>
            <summary style={{ cursor: 'pointer', color: 'var(--text-accent)', marginBottom: '0.55rem' }}>Character Reuse (with Preview)</summary>
            <div className="config-grid">
              <div className="config-control">
                <label>Character Pack</label>
                <select value={characterPackId} onChange={(e) => setCharacterPackId(e.target.value)}>
                  <option value="">None (generate in-session)</option>
                  {previewableCharacterPacks.map((pack) => (
                    <option key={pack.id} value={pack.id}>{pack.name}</option>
                  ))}
                </select>
              </div>
              <div className="config-control">
                <label>
                  <input type="checkbox" checked={reuseSessionChars} onChange={(e) => setReuseSessionChars(e.target.checked)} />
                  <span style={{ marginLeft: 6 }}>Reuse Existing Session Characters</span>
                </label>
              </div>
            </div>

            <div style={{ marginTop: '0.8rem' }}>
              <div style={{ color: 'var(--text-muted)', fontSize: '0.82rem', marginBottom: '0.4rem' }}>Character pack previews</div>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, minmax(0,1fr))', gap: '0.4rem' }}>
                {previewableCharacterPacks.slice(0, 10).map((pack) => {
                  const thumb = packPreviewImage(pack);
                  return (
                    <button
                      key={pack.id}
                      className="btn"
                      style={{
                        padding: '0.3rem',
                        border: pack.id === characterPackId ? '1px solid var(--text-accent)' : '1px solid var(--border-color)',
                        textAlign: 'left',
                      }}
                      onClick={() => {
                        setCharacterPackId(pack.id);
                        if (thumb) {
                          setSelectedFile({ name: thumb.split('/').pop(), path: thumb, extension: '.png', is_dir: false });
                          setConfigPreview(null);
                        }
                      }}
                    >
                      <img src={mediaUrl(thumb)} alt={pack.name} style={{ width: '100%', height: 62, objectFit: 'cover', borderRadius: 6 }} />
                      <div style={{ marginTop: '0.2rem', fontSize: '0.72rem', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{pack.name}</div>
                    </button>
                  );
                })}
              </div>
            </div>

            {reuseSessionChars && (
              <div style={{ marginTop: '0.7rem' }}>
                <div style={{ marginBottom: '0.4rem', color: 'var(--text-muted)', fontSize: '0.85rem' }}>Session character previews</div>
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, minmax(0,1fr))', gap: '0.4rem' }}>
                  {sessionChars.length === 0 && (
                    <div style={{ color: 'var(--text-muted)', fontSize: '0.8rem' }}>No character images in this session.</div>
                  )}
                  {sessionChars.map((item) => (
                    <button
                      key={item.path}
                      className="btn"
                      style={{ padding: '0.2rem', border: item.path === selectedSessionCharacter ? '1px solid var(--text-accent)' : '1px solid var(--border-color)' }}
                      onClick={() => {
                        setSelectedSessionCharacter(item.path);
                        setSelectedFile({ name: item.name, path: item.path, extension: '.png', is_dir: false });
                        setConfigPreview(null);
                      }}
                    >
                      <img src={mediaUrl(item.path)} alt={item.name} style={{ width: '100%', height: 70, objectFit: 'cover', borderRadius: 6 }} />
                      <div style={{ fontSize: '0.7rem', marginTop: '0.2rem', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{item.name}</div>
                    </button>
                  ))}
                </div>
              </div>
            )}
          </details>
          )}

          <button className="btn btn-primary" style={{ marginTop: '1rem', width: '100%' }} onClick={() => startAgent(selectedAgent)} disabled={running}>
            {running ? <Loader2 size={16} className="animate-spin" /> : <Play size={16} />} Run {AGENTS_LIST.find((a) => a.id === selectedAgent)?.name}
          </button>
        </section>
      </aside>

      <main style={{ flex: 1, display: 'flex', flexDirection: 'column', minHeight: 0 }}>
        <div style={{ flex: 1, display: 'flex', minHeight: 0, gap: '1rem' }}>
          <div className="glass-panel" style={{ width: '23%', minWidth: 260, padding: '0.75rem', display: 'flex', flexDirection: 'column', minHeight: 0 }}>
            <h3 style={{ margin: '0 0 0.75rem 0', fontSize: '1rem' }}>Session Files</h3>

            {sessionMode === 'new' ? (
              <div style={{ color: 'var(--text-muted)', padding: '0.75rem' }}>
                Session data will appear here after generation starts.
              </div>
            ) : (
              <SessionTreeView
                rootPath={sessionPath || null}
                loadChildren={async (path) => {
                  const res = await axios.get(`${API_BASE}/sessions/tree?path=${encodeURIComponent(path || '')}`);
                  return res.data;
                }}
                onItemSelect={handleTreeItemClick}
                selectedPath={selectedFile?.path || ''}
                refreshToken={treeRefreshToken}
                emptyMessage="No files found for this session yet."
              />
            )}
          </div>

          <div className="glass-panel" style={{ flex: 1, display: 'flex', flexDirection: 'column', minHeight: 0 }}>
            <div style={{ flex: 1, minHeight: 0, padding: '1rem', borderRadius: '12px', background: 'var(--bg-surface)', overflow: 'hidden' }}>
              {selectedFile ? (
                <FilePreviewPane selectedFile={selectedFile} apiBase={API_BASE} mediaBase={MEDIA_BASE} libraryMediaBase={LIBRARY_MEDIA_BASE} />
              ) : sessionMode === 'new' && buildpackPreviewBlobUrl ? (
                <div style={{ height: '100%', width: '100%', overflow: 'hidden', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                  <img
                    src={buildpackPreviewBlobUrl}
                    alt="BuildPack preview"
                    style={{ maxWidth: '100%', maxHeight: '100%', display: 'block', margin: '0 auto', borderRadius: 10, border: '1px solid var(--border-color)' }}
                  />
                </div>
              ) : configPreview?.type === 'style' ? (
                <div
                  style={{
                    height: '100%',
                    width: '100%',
                    borderRadius: '12px',
                    background: stylePreviewBackground(cloudStyle),
                    display: 'flex',
                    flexDirection: 'column',
                    alignItems: 'center',
                    justifyContent: 'center',
                    color: '#fff',
                    fontFamily: fontStyle.includes('roboto') ? 'Roboto' : 'Inter',
                    padding: '1rem',
                    textAlign: 'center',
                  }}
                >
                  <h3 style={{ marginTop: 0 }}>{configPreview.title}</h3>
                  <div style={{
                    background: 'rgba(15, 15, 25, 0.55)',
                    border: '1px solid rgba(255,255,255,0.24)',
                    borderRadius: 12,
                    padding: '0.8rem 1rem',
                    maxWidth: 620,
                    boxShadow: '0 8px 20px rgba(0,0,0,0.35)',
                  }}>
                    {configPreview.text}
                  </div>
                  {configPreview.thumbnail && (
                    <img
                      src={mediaUrl(configPreview.thumbnail)}
                      alt="style preview"
                      style={{ marginTop: '1rem', maxHeight: 220, borderRadius: 10, border: '1px solid rgba(255,255,255,0.25)' }}
                    />
                  )}
                </div>
              ) : (
                <div
                  style={{
                    height: '100%',
                    width: '100%',
                    borderRadius: '12px',
                    background: stylePreviewBackground(cloudStyle),
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    boxShadow: 'inset 0 0 60px rgba(0,0,0,0.3)',
                    color: '#fff',
                    fontFamily: fontStyle.includes('roboto') ? 'Roboto' : 'Inter',
                    fontSize: '1.15rem',
                    textAlign: 'center',
                    padding: '1.2rem',
                    textShadow: '2px 2px 10px rgba(0,0,0,0.5)',
                  }}
                >
                  {narrativePrompt || 'Enter narrative prompt to preview on canvas.'}
                </div>
              )}
            </div>
          </div>
        </div>

        <section className="glass-panel console-panel" style={{ height: 220, display: 'flex', flexDirection: 'column', background: '#0a0a0f', marginTop: '1rem' }}>
          <div style={{ padding: '0.75rem 1rem', borderBottom: '1px solid var(--border-color)', display: 'flex', alignItems: 'center', justifyContent: 'space-between', background: 'var(--bg-surface)' }}>
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

          <div ref={scrollRef} style={{ flex: 1, padding: '1rem', overflowY: 'auto', fontFamily: 'monospace', fontSize: '0.85rem', lineHeight: '1.6' }}>
            {logs.map((log, i) => (
              <div key={i} style={{ color: log.type === 'error' ? 'var(--danger)' : log.type === 'success' ? '#55efc4' : log.type === 'system' ? 'var(--text-muted)' : '#00cec9', marginBottom: '0.25rem' }}>
                <span style={{ opacity: 0.5, marginRight: 8 }}>[{new Date().toLocaleTimeString()}]</span>
                {log.msg}
              </div>
            ))}
            {!running && logs.length === 0 && <div style={{ opacity: 0.3, textAlign: 'center', marginTop: '20%' }}>Awaiting execution command...</div>}
          </div>
        </section>
      </main>
    </div>
  );
}
