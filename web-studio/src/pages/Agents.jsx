import { useState, useEffect, useRef } from 'react';
import { Play, SquareTerminal, Loader2, StopCircle } from 'lucide-react';
import axios from 'axios';
import { useNavigate, useParams } from 'react-router-dom';
import SessionTreeView from '../components/SessionTreeView';
import FilePreviewPane from '../components/FilePreviewPane';

const API_BASE = 'http://localhost:8000/api';
const WS_BASE = 'ws://localhost:8000/api';
const MEDIA_BASE = 'http://localhost:8000/media';
const LIBRARY_MEDIA_BASE = 'http://localhost:8000/library-media';
const AGENTS_LIST = [
  { id: 'narrativeManga', name: 'Narrative Manga', desc: 'Generates animated manga episodes with TTS and Chronos.' },
  { id: 'newsDesk', name: 'AI News Anchor', desc: 'Synthesizes daily news into a video broadcast.' },
  { id: 'brandAds', name: 'Brand Storyteller', desc: 'Creates short 15s commercial reels.' },
];
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
  const [selectedAgent, setSelectedAgent] = useState('narrativeManga');
  const [sessionMode, setSessionMode] = useState('new');
  const [sessionPath, setSessionPath] = useState('');
  const [availableSessions, setAvailableSessions] = useState([]);
  const [styleProfiles, setStyleProfiles] = useState([]);
  const [characterPacks, setCharacterPacks] = useState([]);
  const [sessionChars, setSessionChars] = useState([]);

  const [narrativePrompt, setNarrativePrompt] = useState('A sci-fi detective embarks on a neon city mystery.');
  const [theme, setTheme] = useState('scary_stories');
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

  const ws = useRef(null);
  const scrollRef = useRef(null);

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
      if (sessionMode === 'existing' && !sessionPath) {
        setLogs([{ type: 'error', msg: 'Please select an existing session before running.' }]);
        return;
      }

      setRunning(true);
      setLogs([{ type: 'system', msg: `Triggering ${agentName}...` }]);
      const res = await axios.post(`${API_BASE}/agents/run`, {
        agent_name: agentName,
        prompt: narrativePrompt,
        theme,
        preset,
        format,
        cloud_style: cloudStyle,
        font_style: fontStyle,
        narration_mode: narrationMode,
        character_pack_id: characterPackId || null,
        reuse_session_chars: reuseSessionChars,
        session_chars_path: reuseSessionChars ? `${sessionPath}/chars` : null,
        selected_session_character: reuseSessionChars ? selectedSessionCharacter || null : null,
        session_mode: sessionMode,
        session_path: sessionMode === 'existing' ? sessionPath : null,
        enable_music: enableMusic,
        max_image_requests: maxImageRequests,
        max_chars_per_episode: maxCharsPerEpisode,
        max_panels_per_episode: maxPanelsPerEpisode,
        max_episode_duration_mins: maxEpisodeDurationMins,
      });
      setJobId(res.data.job_id);
    } catch (err) {
      setLogs((prev) => [...prev, { type: 'error', msg: `Failed to start: ${err.message}` }]);
      setRunning(false);
    }
  };

  const handleTreeItemClick = (item) => {
    if (item.is_dir) {
      setSelectedFile(null);
      return;
    }
    setSelectedFile(item);
    setConfigPreview(null);
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
    setPage('workspace');
    setSelectedAgent(agentId);
    setSessionMode(normalizedMode);
    if (normalizedMode === 'existing' && sessionId) {
      setSessionPath(`${sessionId}/${agentId}`);
    } else {
      setSessionPath('');
    }
  }, [agentId, modeParam, sessionId]);

  useEffect(() => {
    setSelectedFile(null);
  }, [sessionMode, sessionPath]);

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
            const match = sub.data.find((item) => item.is_dir && item.name === selectedAgent);
            if (match) {
              try {
                const charsRes = await axios.get(`${API_BASE}/characters/session-images`, { params: { session_path: match.path } });
                if ((charsRes.data || []).length > 0) {
                  sessionOptions.push(match.path);
                }
              } catch {
                // ignore sessions without usable character previews
              }
            }
          } catch {
            // ignore missing session folders
          }
        }

        setAvailableSessions(sessionOptions);
        if (sessionMode === 'existing') {
          const urlDerivedPath = sessionId ? `${sessionId}/${selectedAgent}` : '';
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
            <summary style={{ cursor: 'pointer', color: 'var(--text-accent)', marginBottom: '0.55rem' }}>Run Setup</summary>
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

            <div className="config-control" style={{ marginBottom: '0.8rem' }}>
              <label>Narrative Prompt</label>
              <textarea
                rows={3}
                value={narrativePrompt}
                onChange={(e) => setNarrativePrompt(e.target.value)}
                style={{ width: '100%', resize: 'vertical' }}
              />
            </div>
          </details>

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

          <details style={{ marginBottom: '0.8rem' }}>
            <summary style={{ cursor: 'pointer', color: 'var(--text-accent)', marginBottom: '0.55rem' }}>Generation Controls</summary>
            <div className="config-grid" style={{ marginTop: '0.8rem' }}>
              <div className="config-control">
                <label>Theme</label>
                <select value={theme} onChange={(e) => setTheme(e.target.value)}>
                  <option value="scary_stories">Scary Stories</option>
                  <option value="mystery_adventure">Mystery Adventure</option>
                  <option value="slice_of_life">Slice of Life</option>
                </select>
              </div>
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

            <div className="config-grid" style={{ marginTop: '0.8rem' }}>
              <div className="config-control">
                <label>Format</label>
                <select value={format} onChange={(e) => setFormat(e.target.value)}>
                  <option value="tiktok">TikTok</option>
                  <option value="instagram_reels">Instagram Reels</option>
                  <option value="youtube_shorts">YouTube Shorts</option>
                  <option value="youtube_widescreen">YouTube Widescreen</option>
                </select>
              </div>
              <div className="config-control">
                <label>
                  <input type="checkbox" checked={enableMusic} onChange={(e) => setEnableMusic(e.target.checked)} />
                  <span style={{ marginLeft: 6 }}>Enable Music</span>
                </label>
              </div>
            </div>

            <div className="config-grid" style={{ marginTop: '0.8rem' }}>
              <div className="config-control">
                <label>Max Images</label>
                <input type="number" min="1" value={maxImageRequests} onChange={(e) => setMaxImageRequests(parseInt(e.target.value, 10) || 1)} />
              </div>
              <div className="config-control">
                <label>Max Characters</label>
                <input type="number" min="1" value={maxCharsPerEpisode} onChange={(e) => setMaxCharsPerEpisode(parseInt(e.target.value, 10) || 1)} />
              </div>
              <div className="config-control">
                <label>Max Panels</label>
                <input type="number" min="1" value={maxPanelsPerEpisode} onChange={(e) => setMaxPanelsPerEpisode(parseInt(e.target.value, 10) || 1)} />
              </div>
              <div className="config-control">
                <label>Max Duration (min)</label>
                <input type="number" min="1" value={maxEpisodeDurationMins} onChange={(e) => setMaxEpisodeDurationMins(parseInt(e.target.value, 10) || 1)} />
              </div>
            </div>
          </details>

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
