import { useState, useEffect, useRef } from 'react';
import { Play, SquareTerminal, Loader2, StopCircle, Lock, Unlock, RotateCcw, RefreshCcw } from 'lucide-react';
import axios from 'axios';
import { useNavigate, useParams } from 'react-router-dom';
import SessionTreeView from '../components/SessionTreeView';
import FilePreviewPane from '../components/FilePreviewPane';

const API_BASE = 'http://localhost:8000/api';
const WS_BASE = 'ws://localhost:8000/api';
const MEDIA_BASE = 'http://localhost:8000/media';
const LIBRARY_MEDIA_BASE = 'http://localhost:8000/library-media';
const PIPELINE_START_TIME_KEY = 'autoanimator.pipelineStartTimeBySession';
const AGENTS_LIST = [
  { id: 'autoAnimator', name: 'AutoAnimator', desc: 'Focused preview-driven animator powered by Narrative Manga backend.' },
];
const AUTOANIMATOR_TEMPLATE_SESSION_ID = '1392763';
const VALID_AGENT_IDS = new Set(AGENTS_LIST.map((a) => a.id));
const DEFAULT_AUTOANIMATOR_LIMITS = {
  maxImageRequests: 50,
  maxCharsPerEpisode: 3,
  maxPanelsPerEpisode: 50,
  maxEpisodeDurationMins: 1,
};
const DEFAULT_SECTION_LOCKS = {
  step0: true,
  planner: true,
  preset_prompt: true,
  chars: true,
  scenes: true,
  audio: true,
  texts: true,
  music: true,
  video: true,
};

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

function isAutoAnimatorSessionFolderName(name) {
  if (typeof name !== 'string') return false;
  const lower = name.trim().toLowerCase();
  return lower === 'autoanimator' || lower.endsWith('_autoanimator');
}

export default function Agents() {
  const navigate = useNavigate();
  const { agentId, sessionMode: modeParam, sessionId } = useParams();

  const [page, setPage] = useState('selector');
  const [running, setRunning] = useState(false);
  const [logs, setLogs] = useState([]);
  const [jobId, setJobId] = useState(null);
  const [pipelineStartBySession, setPipelineStartBySession] = useState(() => {
    try {
      const raw = window.localStorage.getItem(PIPELINE_START_TIME_KEY);
      const parsed = raw ? JSON.parse(raw) : {};
      return parsed && typeof parsed === 'object' ? parsed : {};
    } catch {
      return {};
    }
  });
  const [selectedAgent, setSelectedAgent] = useState('autoAnimator');
  const [sessionMode, setSessionMode] = useState('new');
  const [sessionPath, setSessionPath] = useState('');
  const [availableSessions, setAvailableSessions] = useState([]);
  const [styleProfiles, setStyleProfiles] = useState([]);
  const [characterPacks, setCharacterPacks] = useState([]);
  const [sessionChars, setSessionChars] = useState([]);

  const [narrativePrompt, setNarrativePrompt] = useState('A sci-fi detective embarks on a neon city mystery.');
  const [presetPrompt, setPresetPrompt] = useState('');
  const [projectName, setProjectName] = useState('');
  const [projectNameUserEdited, setProjectNameUserEdited] = useState(false);
  const [theme, setTheme] = useState('auto-select');
  const [preset, setPreset] = useState('auto-select');
  const [niche, setNiche] = useState('auto-select');
  const [plannerThemes, setPlannerThemes] = useState({});
  const [plannerArtStyles, setPlannerArtStyles] = useState({});
  const [plannerNiches, setPlannerNiches] = useState({});
  const [format, setFormat] = useState('youtube_widescreen');
  const [cloudStyle, setCloudStyle] = useState('cloud-fluffy-default');
  const [fontStyle, setFontStyle] = useState('font-inter-clean');
  const [subtitleStyle, setSubtitleStyle] = useState('subtitle-neon-clean');
  const [narrationMode, setNarrationMode] = useState('hybrid_subtitles_clouds');
  const [characterPackId, setCharacterPackId] = useState('');
  const [reuseSessionChars, setReuseSessionChars] = useState(false);
  const [selectedSessionCharacter, setSelectedSessionCharacter] = useState('');
  const [enableMusic, setEnableMusic] = useState(true);
  const [musicProvider, setMusicProvider] = useState('lyria');
  const [lyriaModel, setLyriaModel] = useState('lyria-3-clip-preview');
  const [ttsProvider, setTtsProvider] = useState('edge');
  const [geminiTtsModel, setGeminiTtsModel] = useState('models/gemini-2.5-flash-tts');
  const [maxImageRequests, setMaxImageRequests] = useState(DEFAULT_AUTOANIMATOR_LIMITS.maxImageRequests);
  const [maxCharsPerEpisode, setMaxCharsPerEpisode] = useState(DEFAULT_AUTOANIMATOR_LIMITS.maxCharsPerEpisode);
  const [maxPanelsPerEpisode, setMaxPanelsPerEpisode] = useState(DEFAULT_AUTOANIMATOR_LIMITS.maxPanelsPerEpisode);
  const [maxEpisodeDurationMins, setMaxEpisodeDurationMins] = useState(DEFAULT_AUTOANIMATOR_LIMITS.maxEpisodeDurationMins);
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
  const [workflowHistory, setWorkflowHistory] = useState({});
  const [selectedHistoryHash, setSelectedHistoryHash] = useState({});
  const [hashRevertBusy, setHashRevertBusy] = useState('');
  const [stepBusy, setStepBusy] = useState('');
  const [stepReset, setStepReset] = useState({ planner: false, chars: false, scenes: false, audio: false, texts: false, music: false, video: false });
  const [episodesMode, setEpisodesMode] = useState('new');
  const [episodeMode, setEpisodeMode] = useState(true);
  const [targetEpisode, setTargetEpisode] = useState('');
  const [sourceCharSession, setSourceCharSession] = useState('');
  const [sourceCharPath, setSourceCharPath] = useState('');
  const [startFrameFile, setStartFrameFile] = useState(null);
  const [endFrameFile, setEndFrameFile] = useState(null);
  const [startFramePath, setStartFramePath] = useState('');
  const [endFramePath, setEndFramePath] = useState('');
  const [availableModelsByTask, setAvailableModelsByTask] = useState({ planner: [], chars: [], scenes: [] });
  const [plannerModel, setPlannerModel] = useState('models/gemini-flash-latest');
  const [charsModel, setCharsModel] = useState('models/gemini-2.5-flash-image');
  const [scenesModel, setScenesModel] = useState('models/gemini-2.5-flash-image');
  const [charPromptItems, setCharPromptItems] = useState([]);
  const [charRedoBusy, setCharRedoBusy] = useState('');
  const [toasts, setToasts] = useState([]);
  const [sectionLocks, setSectionLocks] = useState({
    ...DEFAULT_SECTION_LOCKS,
  });

  const selectedNicheConfig = plannerNiches && niche && niche !== 'auto-select'
    ? plannerNiches[niche]
    : null;
  const selectedNicheDirectorContext = String(selectedNicheConfig?.director_context || '').trim();

  const ws = useRef(null);
  const wsIntentionalCloseRef = useRef(false);
  const sessionPathRef = useRef('');
  const scrollRef = useRef(null);
  const buildpackRequestSeq = useRef(0);

  useEffect(() => {
    sessionPathRef.current = sessionPath || '';
  }, [sessionPath]);

  const setSessionPipelineStartTime = (path, isoTs) => {
    const p = String(path || '').trim();
    const ts = String(isoTs || '').trim();
    if (!p || !ts) return;
    setPipelineStartBySession((prev) => {
      const next = { ...prev, [p]: ts };
      try {
        window.localStorage.setItem(PIPELINE_START_TIME_KEY, JSON.stringify(next));
      } catch {
        // Ignore localStorage errors.
      }
      return next;
    });
  };

  const pushToast = (type, message) => {
    const id = `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
    setToasts((prev) => [...prev, { id, type, message }]);
    setTimeout(() => {
      setToasts((prev) => prev.filter((t) => t.id !== id));
    }, 3200);
  };

  const autoRunMissingFields = () => {
    const missing = [];
    if (sessionMode === 'existing' && !sessionPath) {
      missing.push('Step 0: existing session selection');
    }
    if (sessionMode === 'new') {
      if (!buildpackResolution) missing.push('Step 0: resolution');
      if (!buildpackFontStyle) missing.push('Step 0: font style');
      if (!buildpackSubtitleStyle) missing.push('Step 0: subtitle style');
      if (!buildpackCloudStyle) missing.push('Step 0: cloud style');
    }
    if ((!narrativePrompt || !narrativePrompt.trim()) && !(episodeMode && presetPrompt.trim())) {
      missing.push('Step 1: narrative prompt');
    }
    if (!preset) missing.push('Step 1: art style');
    if (!plannerModel) missing.push('Step 1: planner model');
    return missing;
  };

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
    const missing = autoRunMissingFields();
    if (missing.length > 0) {
      const msg = `Auto run blocked. Fill required fields: ${missing.join(', ')}`;
      setLogs((prev) => [...prev, { type: 'error', msg }]);
      pushToast('error', 'Fill Step 0 and Step 1 required fields first.');
      return;
    }

    try {
      setRunning(true);
      const startedAt = new Date().toISOString();
      setLogs([{ type: 'system', msg: `Running full pipeline via ${agentName}...` }]);
      await runNarrativeStep('all', { pipelineStartedAt: startedAt, resetConsole: true });
    } catch (err) {
      setLogs((prev) => [...prev, { type: 'error', msg: `Failed to start: ${err.message}` }]);
      setRunning(false);
      return;
    }
    setRunning(false);
  };

  const goBackToAgentSelector = () => {
    setPage('selector');
    setSessionMode('new');
    setSessionPath('');
    navigate('/agents');
  };

  const startNewSessionFromWorkspace = () => {
    setSessionMode('new');
    setSessionPath('');
    setProjectName('');
    setProjectNameUserEdited(false);
    setNiche('auto-select');
    setPresetPrompt('');
    setStartFrameFile(null);
    setEndFrameFile(null);
    setStartFramePath('');
    setEndFramePath('');
    setMaxImageRequests(DEFAULT_AUTOANIMATOR_LIMITS.maxImageRequests);
    setMaxCharsPerEpisode(DEFAULT_AUTOANIMATOR_LIMITS.maxCharsPerEpisode);
    setMaxPanelsPerEpisode(DEFAULT_AUTOANIMATOR_LIMITS.maxPanelsPerEpisode);
    setMaxEpisodeDurationMins(DEFAULT_AUTOANIMATOR_LIMITS.maxEpisodeDurationMins);
    goToAgentWorkspace(selectedAgent, 'new');
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
      setWorkflowHistory({});
      return;
    }
    try {
      const res = await axios.get(`${API_BASE}/agents/autoanimator/checkpoints`, { params: { session_path: path } });
      setWorkflowHashes(res.data?.hashes || {});
      setWorkflowHistory(res.data?.history || {});
    } catch {
      setWorkflowHashes({});
      setWorkflowHistory({});
    }
  };

  const applyTemplateSettings = (settings = {}) => {
    if (typeof settings?.prompt === 'string' && settings.prompt.trim()) setNarrativePrompt(settings.prompt);
    if (typeof settings?.preset_prompt === 'string') setPresetPrompt(settings.preset_prompt);
    // For new sessions, project name should be backend-driven or user-entered,
    // not inherited from template defaults.
    if (typeof settings?.theme === 'string' && settings.theme.trim()) setTheme(settings.theme);
    if (typeof settings?.preset === 'string' && settings.preset.trim()) setPreset(settings.preset);
    if (typeof settings?.niche === 'string' && settings.niche.trim()) setNiche(settings.niche);
    if (typeof settings?.format === 'string' && settings.format.trim()) setFormat(settings.format);
    if (typeof settings?.planner_model === 'string' && settings.planner_model.trim()) setPlannerModel(settings.planner_model);
    if (typeof settings?.character_image_model === 'string' && settings.character_image_model.trim()) setCharsModel(settings.character_image_model);
    if (typeof settings?.scene_image_model === 'string' && settings.scene_image_model.trim()) setScenesModel(settings.scene_image_model);
    if (typeof settings?.max_image_requests === 'number') setMaxImageRequests(settings.max_image_requests);
    if (typeof settings?.max_chars_per_episode === 'number') setMaxCharsPerEpisode(settings.max_chars_per_episode);
    if (typeof settings?.max_panels_per_episode === 'number') setMaxPanelsPerEpisode(settings.max_panels_per_episode);
    if (typeof settings?.max_episode_duration_mins === 'number') setMaxEpisodeDurationMins(settings.max_episode_duration_mins);
    if (typeof settings?.cloud_style === 'string' && settings.cloud_style.trim()) setBuildpackCloudStyle(settings.cloud_style);
    if (typeof settings?.font_style === 'string' && settings.font_style.trim()) setBuildpackFontStyle(settings.font_style);
    if (typeof settings?.subtitle_style === 'string' && settings.subtitle_style.trim()) setBuildpackSubtitleStyle(settings.subtitle_style);
    if (typeof settings?.subtitle_scale === 'number') setSubtitleScale(settings.subtitle_scale);
    if (typeof settings?.enable_music === 'boolean') setEnableMusic(settings.enable_music);
    if (typeof settings?.music_provider === 'string' && settings.music_provider.trim()) setMusicProvider(settings.music_provider);
    if (typeof settings?.lyria_model === 'string' && settings.lyria_model.trim()) setLyriaModel(settings.lyria_model);
    if (typeof settings?.tts_provider === 'string' && settings.tts_provider.trim()) setTtsProvider(settings.tts_provider);
    if (typeof settings?.gemini_tts_model === 'string' && settings.gemini_tts_model.trim()) setGeminiTtsModel(settings.gemini_tts_model);
    if (typeof settings?.episodes_mode === 'string' && settings.episodes_mode.trim()) setEpisodesMode(settings.episodes_mode);
    if (typeof settings?.episode_mode === 'boolean') setEpisodeMode(settings.episode_mode);
    if (typeof settings?.start_frame_path === 'string') setStartFramePath(settings.start_frame_path);
    if (typeof settings?.end_frame_path === 'string') setEndFramePath(settings.end_frame_path);

    const resolution = Array.isArray(settings?.resolution) ? settings.resolution : [];
    if (resolution.length === 2) {
      const [w, h] = resolution;
      if (w === 1920 && h === 1080) setBuildpackResolution('youtube_video');
      else if (w === 1080 && h === 1920) setBuildpackResolution('youtube_shorts');
      else if (w === 1080 && h === 1080) setBuildpackResolution('insta_posts');
    }
  };

  const normalizeHistoryRows = (step) => {
    const rows = workflowHistory?.[step];
    return Array.isArray(rows) ? rows : [];
  };

  const revertToStepHash = async (step) => {
    if (!sessionPath) return;
    const hash = selectedHistoryHash?.[step];
    if (!hash) return;

    setHashRevertBusy(step);
    setBuildpackSaveMessage('');
    try {
      const res = await axios.post(`${API_BASE}/agents/autoanimator/revert-hash`, {
        session_path: sessionPath,
        step,
        hash,
      });
      if (res.data?.hashes) setWorkflowHashes(res.data.hashes);
      if (res.data?.history) setWorkflowHistory(res.data.history);
      const currentHash = res.data?.hashes?.[step] || res.data?.hash || hash;
      setSelectedHistoryHash((prev) => ({ ...prev, [step]: currentHash }));
      // Pull a fresh server snapshot so dropdown state is immediately consistent.
      await refreshWorkflowHashes(sessionPath);
      setTreeRefreshToken((prev) => prev + 1);
      setLogs((prev) => [...prev, { type: 'success', msg: `Restored ${step} to hash ${currentHash}` }]);
      pushToast('success', `Restored ${step} to ${currentHash}`);
      setBuildpackSaveMessage(`Restored ${step} to hash ${currentHash}`);
    } catch (e) {
      pushToast('error', `Failed to restore ${step}.`);
      setLogs((prev) => [...prev, { type: 'error', msg: `Restore failed for ${step}: ${e.message}` }]);
      setBuildpackSaveMessage(`Restore failed for ${step}: ${e.message}`);
    } finally {
      setHashRevertBusy('');
    }
  };

  const buildSessionSettingsSnapshot = () => ({
    prompt: narrativePrompt,
    preset_prompt: presetPrompt,
    project_name: projectName,
    episodes_mode: episodesMode,
    episode: targetEpisode ? parseInt(targetEpisode, 10) : null,
    theme,
    preset,
    niche,
    niche_context: selectedNicheDirectorContext || null,
    format,
    planner_model: plannerModel,
    character_image_model: charsModel,
    scene_image_model: scenesModel,
    char_visual_overrides: charPromptItems.reduce((acc, item) => {
      if (item?.name && typeof item.visual_prompt === 'string') {
        acc[item.name] = item.visual_prompt;
      }
      return acc;
    }, {}),
    resolution: null,
    fps: null,
    enable_music: enableMusic,
    music_provider: musicProvider,
    lyria_model: lyriaModel,
    tts_provider: ttsProvider,
    gemini_tts_model: geminiTtsModel,
    vector_upscale: false,
    max_image_requests: maxImageRequests,
    max_chars_per_episode: maxCharsPerEpisode,
    max_panels_per_episode: maxPanelsPerEpisode,
    max_episode_duration_mins: maxEpisodeDurationMins,
    cloud_style: buildpackCloudStyle,
    font_style: buildpackFontStyle,
    subtitle_style: buildpackSubtitleStyle,
    narration_mode: buildpackCloudStyle === 'cloud-none' ? 'subtitles_only' : 'hybrid_subtitles_clouds',
    subtitle_x: subtitleX,
    subtitle_y: subtitleY,
    subtitle_scale: subtitleScale,
    cloud_x: cloudX,
    cloud_y: cloudY,
    cloud_w: cloudW,
    cloud_h: cloudH,
    episode_mode: episodeMode,
    start_frame_path: startFramePath || null,
    end_frame_path: endFramePath || null,
  });

  const ensureSessionForPlannerRun = async () => {
    if (sessionPath) return sessionPath;
    const normalizedProjectName = projectNameUserEdited ? (projectName || '').trim() : '';
    const payload = normalizedProjectName ? { project_name: normalizedProjectName } : {};
    const res = await axios.post(`${API_BASE}/agents/autoanimator/bootstrap-session`, payload);
    const path = String(res.data?.session_path || '').trim();
    if (!path) return '';

    setSessionPath(path);
    if (sessionMode !== 'existing') {
      setSessionMode('existing');
    }
    setTreeRefreshToken((prev) => prev + 1);

    const sid = String(res.data?.session_id || path.split('/')[0] || '');
    if (sid) {
      navigate(`/agents/${encodeURIComponent(selectedAgent)}/existing/${encodeURIComponent(sid)}`, { replace: true });
    }
    return path;
  };

  const uploadReferenceFramesIfNeeded = async (activeSessionPath) => {
    let nextStart = startFramePath || '';
    let nextEnd = endFramePath || '';

    if (startFrameFile) {
      const fd = new FormData();
      fd.append('session_path', activeSessionPath);
      fd.append('role', 'start');
      fd.append('file', startFrameFile);
      const up = await axios.post(`${API_BASE}/agents/autoanimator/upload-reference-frame`, fd, {
        headers: { 'Content-Type': 'multipart/form-data' },
      });
      nextStart = String(up.data?.frame_path || '').trim();
      setStartFramePath(nextStart);
      setStartFrameFile(null);
    }

    if (endFrameFile) {
      const fd = new FormData();
      fd.append('session_path', activeSessionPath);
      fd.append('role', 'end');
      fd.append('file', endFrameFile);
      const up = await axios.post(`${API_BASE}/agents/autoanimator/upload-reference-frame`, fd, {
        headers: { 'Content-Type': 'multipart/form-data' },
      });
      nextEnd = String(up.data?.frame_path || '').trim();
      setEndFramePath(nextEnd);
      setEndFrameFile(null);
    }

    return {
      startFramePath: nextStart || null,
      endFramePath: nextEnd || null,
    };
  };

  const runNarrativeStep = async (step, opts = {}) => {
    const stepToSections = {
      planner: ['planner'],
      chars: ['chars'],
      scenes: ['scenes'],
      audio: ['audio'],
      texts: ['texts'],
      music: ['music'],
      video: ['video'],
      all: ['step0', 'planner', 'chars', 'scenes', 'audio', 'texts', 'music', 'video'],
    };
    const sectionsToLock = stepToSections[step] || [];
    if (sectionsToLock.length > 0) {
      setSectionLocks((prev) => {
        const next = { ...prev };
        sectionsToLock.forEach((k) => {
          next[k] = true;
        });
        return next;
      });
    }

    setStepBusy(step);
    setBuildpackSaveMessage('');
    if (opts?.resetConsole) {
      setLogs([]);
    }
    try {
      const needsPlannerContext = step === 'all' || step === 'planner';
      let activeSessionPath = sessionPath;
      let activeSessionMode = sessionMode;

      if (needsPlannerContext && !activeSessionPath) {
        activeSessionPath = await ensureSessionForPlannerRun();
        if (activeSessionPath) {
          activeSessionMode = 'existing';
        }
      }

      let uploadedRefs = {
        startFramePath: startFramePath || null,
        endFramePath: endFramePath || null,
      };
      if (needsPlannerContext && activeSessionPath) {
        uploadedRefs = await uploadReferenceFramesIfNeeded(activeSessionPath);
      }

      const isExisting = activeSessionMode === 'existing' || Boolean(activeSessionPath);
      if (isExisting && activeSessionPath) {
        try {
          await axios.post(`${API_BASE}/agents/autoanimator/session-sync`, {
            session_path: activeSessionPath,
            settings: {
              ...buildSessionSettingsSnapshot(),
              start_frame_path: uploadedRefs.startFramePath,
              end_frame_path: uploadedRefs.endFramePath,
            },
            locks: sectionLocks,
          });
        } catch {
          // Continue run even if settings sync fails; payload still carries current values.
        }
      }
      const effectiveEpisodesMode = isExisting ? episodesMode : 'new';
      const effectiveEpisodeMode = isExisting ? episodeMode : true;
      const payload = {
        session_mode: isExisting ? 'existing' : 'new',
        session_path: isExisting ? activeSessionPath : null,
        step,
        reset: opts?.redo ? true : Boolean(stepReset[step]),
        redo: Boolean(opts?.redo),
        prompt: narrativePrompt,
        preset_prompt: presetPrompt,
        project_name: projectName,
        niche,
        theme,
        episodes: effectiveEpisodesMode,
        episode: targetEpisode ? parseInt(targetEpisode, 10) : null,
        preset,
        format,
        enable_music: enableMusic,
        music_provider: musicProvider,
        lyria_model: lyriaModel,
        tts_provider: ttsProvider,
        gemini_tts_model: geminiTtsModel,
        narration_mode: buildpackCloudStyle === 'cloud-none' ? 'subtitles_only' : 'hybrid_subtitles_clouds',
        buildpack_resolution: buildpackResolution,
        cloud_style: buildpackCloudStyle,
        font_style: buildpackFontStyle,
        subtitle_style: buildpackSubtitleStyle,
        subtitle_scale: subtitleScale,
        episode_mode: effectiveEpisodeMode,
        planner_model: plannerModel,
        chars_model: charsModel,
        scenes_model: scenesModel,
        chars_visual_overrides: charPromptItems.reduce((acc, item) => {
          if (item?.name && typeof item.visual_prompt === 'string') {
            acc[item.name] = item.visual_prompt;
          }
          return acc;
        }, {}),
        max_image_requests: maxImageRequests,
        max_chars_per_episode: maxCharsPerEpisode,
        max_panels_per_episode: maxPanelsPerEpisode,
        max_episode_duration_mins: maxEpisodeDurationMins,
        start_frame_path: uploadedRefs.startFramePath,
        end_frame_path: uploadedRefs.endFramePath,
      };

      const start = await axios.post(`${API_BASE}/agents/autoanimator/run-step-live`, payload);

      const startedSessionPath = start.data?.session_path;
      if (startedSessionPath) {
        if (startedSessionPath !== sessionPath) {
          setSessionPath(startedSessionPath);
        }
        if (sessionMode !== 'existing') {
          setSessionMode('existing');
        }
        if (opts?.pipelineStartedAt) {
          setSessionPipelineStartTime(startedSessionPath, opts.pipelineStartedAt);
        }
        setTreeRefreshToken((prev) => prev + 1);
        const sid = String(start.data?.session_id || startedSessionPath.split('/')[0] || '');
        if (sid) {
          navigate(`/agents/${encodeURIComponent(selectedAgent)}/existing/${encodeURIComponent(sid)}`, { replace: true });
        }
      }

      if (start.data?.done && start.data?.result) {
        const instant = start.data.result;
        const instantStatus = instant?.status || 'success';
        setLogs((prev) => [...prev, { type: instantStatus === 'error' ? 'error' : 'info', msg: instant?.reason || `Step '${step}' ${instantStatus}.` }]);
        if (instantStatus === 'error') {
          pushToast('error', `Step ${step} failed.`);
        } else {
          pushToast('success', `Step ${step} ${instantStatus}.`);
        }
        return;
      }

      const currentJobId = start.data?.job_id;
      if (!currentJobId) {
        setLogs((prev) => [...prev, { type: 'error', msg: `Step '${step}' did not return a job id.` }]);
        return;
      }

      setJobId(currentJobId);
      setLogs((prev) => [...prev, { type: 'info', msg: `Step '${step}' started.` }]);

      let finalRes = null;
      for (;;) {
        // Poll final structured result while websocket streams console lines.
        await new Promise((resolve) => setTimeout(resolve, 500));
        const statusRes = await axios.get(`${API_BASE}/agents/autoanimator/job/${currentJobId}`);
        if (statusRes.data?.done) {
          finalRes = statusRes.data?.result || {};
          break;
        }
      }

      setJobId(null);

      const nextPath = finalRes?.session_path || startedSessionPath || sessionPath;
      if (nextPath && nextPath !== sessionPath) {
        setSessionPath(nextPath);
      }
      if (finalRes?.hashes) {
        setWorkflowHashes(finalRes.hashes);
      } else if (nextPath) {
        await refreshWorkflowHashes(nextPath);
      }
      if (finalRes?.history) {
        setWorkflowHistory(finalRes.history);
      }

      const status = finalRes?.status || 'success';
      const note = status === 'error' ? (finalRes?.stderr || 'Step failed') : `Step '${step}' completed`;
      setLogs((prev) => [...prev, { type: status === 'error' ? 'error' : 'success', msg: note }]);
      pushToast(status === 'error' ? 'error' : 'success', status === 'error' ? `Step ${step} failed.` : `Step ${step} completed.`);

      if (status !== 'error' && step === 'chars') {
        setTreeRefreshToken((prev) => prev + 1);
      }

      if (nextPath) {
        const sid = nextPath.split('/')[0];
        goToAgentWorkspace(selectedAgent, 'existing', nextPath);
        if (sid) {
          navigate(`/agents/${encodeURIComponent(selectedAgent)}/existing/${encodeURIComponent(sid)}`, { replace: true });
        }
      }
    } catch (e) {
      setLogs((prev) => [...prev, { type: 'error', msg: `Step '${step}' failed: ${e.message}` }]);
      pushToast('error', `Step ${step} failed.`);
    } finally {
      setJobId(null);
      setStepBusy('');
    }
  };

  const copyCharacterToSession = async () => {
    if (!sourceCharPath) return;
    try {
      const target = sessionPath || null;
      const res = await axios.post(`${API_BASE}/agents/autoanimator/copy-character`, {
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

  const abortCurrentJob = async () => {
    if (!jobId) return;
    try {
      await axios.post(`${API_BASE}/agents/autoanimator/job/${jobId}/abort`);
      setLogs((prev) => [...prev, { type: 'system', msg: 'Abort requested. Waiting for worker shutdown...' }]);
      pushToast('success', 'Abort requested.');
    } catch (e) {
      setLogs((prev) => [...prev, { type: 'error', msg: `Abort failed: ${e.message}` }]);
      pushToast('error', 'Abort failed.');
    }
  };

  const redoSingleCharacter = async (item) => {
    if (!item?.name || !sessionPath) return;
    setCharRedoBusy(item.name);
    setBuildpackSaveMessage('');
    setLogs((prev) => [...prev, { type: 'info', msg: `Single-char redo started: ${item.name}` }]);
    try {
      try {
        await axios.post(`${API_BASE}/agents/autoanimator/session-sync`, {
          session_path: sessionPath,
          settings: buildSessionSettingsSnapshot(),
          locks: sectionLocks,
        });
      } catch {
        // Continue even if state sync fails.
      }

      const res = await axios.post(`${API_BASE}/agents/autoanimator/redo-char`, {
        session_path: sessionPath,
        char_name: item.name,
        visual_prompt: item.visual_prompt,
        chars_model: charsModel,
      });

      const stdout = String(res.data?.stdout || '');
      const stderr = String(res.data?.stderr || '');
      if (stdout.trim()) {
        const lines = stdout.split('\n').map((l) => l.trimEnd()).filter(Boolean).map((msg) => ({ type: 'log', msg }));
        setLogs((prev) => [...prev, ...lines]);
      }
      if (stderr.trim()) {
        const lines = stderr.split('\n').map((l) => l.trimEnd()).filter(Boolean).map((msg) => ({ type: 'error', msg }));
        setLogs((prev) => [...prev, ...lines]);
      }

      if (res.data?.ok === false) {
        setLogs((prev) => [...prev, { type: 'error', msg: `Single-char redo failed: ${res.data?.error || 'unknown error'}` }]);
        pushToast('error', `Failed to regenerate ${item.name}.`);
        setBuildpackSaveMessage(`Regenerate failed for ${item.name}: ${res.data?.error || 'unknown error'}`);
        return;
      }

      if (res.data?.hashes) {
        setWorkflowHashes(res.data.hashes);
      } else {
        await refreshWorkflowHashes(sessionPath);
      }
      setTreeRefreshToken((prev) => prev + 1);
      setLogs((prev) => [...prev, { type: 'success', msg: `Single-char redo completed: ${item.name}` }]);
      pushToast('success', `Regenerated ${item.name}.`);
      setBuildpackSaveMessage(`Regenerated ${item.name}`);
    } catch (e) {
      pushToast('error', `Failed to regenerate ${item.name}.`);
      setBuildpackSaveMessage(`Regenerate failed for ${item.name}: ${e.message}`);
    } finally {
      setCharRedoBusy('');
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
          const outputsMarker = '/outputs/';
          const outIdx = absPath.indexOf(outputsMarker);
          if (outIdx >= 0) {
            const rel = absPath.slice(outIdx + outputsMarker.length);
            if (rel) {
              setSessionPath(rel);
              setTreeRefreshToken((prev) => prev + 1);
            }
          }
        }
        if (data.msg.includes("Step '") && data.msg.includes('finished with status')) {
          setTreeRefreshToken((prev) => prev + 1);
          const activePath = sessionPathRef.current;
          if (activePath) refreshWorkflowHashes(activePath);
        }
      }
      if (data.type === 'success' || data.type === 'error') {
        setRunning(false);
      }
    };

    ws.current.onerror = () => {
      if (!wsIntentionalCloseRef.current) {
        setLogs((prev) => [...prev, { type: 'error', msg: 'WebSocket disconnected abnormally.' }]);
      }
      setRunning(false);
    };

    ws.current.onclose = () => {
      if (!wsIntentionalCloseRef.current) {
        setLogs((prev) => [...prev, { type: 'info', msg: 'Live log stream closed.' }]);
      }
    };

    return () => {
      wsIntentionalCloseRef.current = true;
      if (ws.current && ws.current.readyState < 2) {
        ws.current.close();
      }
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
    setSessionPath('');
    setProjectName('');
    setProjectNameUserEdited(false);
  }, [agentId, modeParam, sessionId]);

  useEffect(() => {
    setSelectedFile(null);
  }, [sessionMode, sessionPath]);

  useEffect(() => {
    if (!sessionPath) return;
    // Reset local project-name ownership on session switch so backend state wins
    // until user explicitly edits the field again.
    setProjectName('');
    setProjectNameUserEdited(false);
  }, [sessionPath]);

  useEffect(() => {
    if (sessionPath) {
      refreshWorkflowHashes(sessionPath);
    } else {
      setWorkflowHashes({});
      setWorkflowHistory({});
      setSelectedHistoryHash({});
      setSectionLocks({ ...DEFAULT_SECTION_LOCKS });
    }
  }, [sessionPath]);

  useEffect(() => {
    const loadTemplateDefaultsForNewSession = async () => {
      if (page !== 'workspace' || sessionMode !== 'new' || sessionPath) return;
      try {
        const templateRoot = await axios.get(`${API_BASE}/sessions/tree`, {
          params: { path: AUTOANIMATOR_TEMPLATE_SESSION_ID },
        });
        const templateDir = (templateRoot.data || []).find((item) => item.is_dir && isAutoAnimatorSessionFolderName(item.name));
        if (!templateDir?.path) {
          return;
        }
        const res = await axios.get(`${API_BASE}/sessions/file`, {
          params: { path: `${templateDir.path}/session_state.json` },
        });
        const raw = res.data?.content || '{}';
        const parsed = JSON.parse(raw);
        const settings = parsed?.settings || {};
        applyTemplateSettings(settings);
        setFormat('youtube_widescreen');
        // New sessions default to LLM auto-selection for aesthetics.
        setTheme('auto-select');
        setPreset('auto-select');
        setNiche('auto-select');
        setSectionLocks({ ...DEFAULT_SECTION_LOCKS });
      } catch {
        // Keep built-in defaults if template session is unavailable.
        setFormat('youtube_widescreen');
        setTheme('auto-select');
        setPreset('auto-select');
        setNiche('auto-select');
      }
    };
    loadTemplateDefaultsForNewSession();
  }, [page, sessionMode, sessionPath]);

  useEffect(() => {
    const keys = ['planner', 'chars', 'scenes', 'audio', 'texts', 'music', 'video'];
    setSelectedHistoryHash((prev) => {
      const next = { ...prev };
      let changed = false;
      keys.forEach((k) => {
        const rows = Array.isArray(workflowHistory?.[k]) ? workflowHistory[k] : [];
        if (!rows.length) return;
        const currentHash = workflowHashes?.[k] || '';
        const preferred = currentHash && rows.some((r) => r?.hash === currentHash)
          ? currentHash
          : (rows[0]?.hash || '');
        if (next[k] !== preferred) {
          next[k] = preferred;
          changed = true;
        }
      });
      return changed ? next : prev;
    });
  }, [workflowHistory, workflowHashes]);

  useEffect(() => {
    const loadSavedPrompt = async () => {
      if (sessionMode !== 'existing' || !sessionPath) return;
      try {
        const filePath = `${sessionPath}/session_state.json`;
        const res = await axios.get(`${API_BASE}/sessions/file`, { params: { path: filePath } });
        const raw = res.data?.content || '{}';
        const parsed = JSON.parse(raw);
        const settings = parsed?.settings || {};
        const savedPrompt = typeof settings?.prompt === 'string' ? settings.prompt : '';
        const savedPresetPrompt = settings?.preset_prompt;

        const isEpisodeMode = settings?.episode_mode === true;
        const presetFromState = typeof savedPresetPrompt === 'string' ? savedPresetPrompt : '';
        const hasPreset = presetFromState.trim().length > 0;
        const hasSavedPrompt = savedPrompt.trim().length > 0;

        if (isEpisodeMode) {
          if (hasPreset) {
            setPresetPrompt(presetFromState);
            setNarrativePrompt(hasSavedPrompt ? savedPrompt : '');
          } else if (hasSavedPrompt) {
            // Legacy-session upgrade: ask backend to compute an LLM-derived persistent preset prompt.
            try {
              const materialize = await axios.post(`${API_BASE}/agents/autoanimator/materialize-preset-prompt`, {
                session_path: sessionPath,
                base_prompt: savedPrompt,
                project_name: typeof settings?.project_name === 'string' ? settings.project_name : '',
                niche: typeof settings?.niche === 'string' ? settings.niche : '',
              });
              const computedPreset = typeof materialize?.data?.preset_prompt === 'string' ? materialize.data.preset_prompt : '';
              if (computedPreset.trim()) {
                setPresetPrompt(computedPreset);
                setNarrativePrompt(savedPrompt);
              } else {
                setPresetPrompt('');
                setNarrativePrompt(savedPrompt);
              }
            } catch {
              setPresetPrompt('');
              setNarrativePrompt(savedPrompt);
            }
          } else {
            setPresetPrompt('');
            setNarrativePrompt('');
          }
        } else {
          if (hasSavedPrompt) {
            setNarrativePrompt(savedPrompt);
          }
          if (typeof savedPresetPrompt === 'string') {
            setPresetPrompt(savedPresetPrompt);
          }
        }
        if (typeof settings?.project_name === 'string') {
          const backendProjectName = settings.project_name.trim();
          if (backendProjectName && !projectNameUserEdited) {
            setProjectName(backendProjectName);
          }
        }

        if (typeof settings?.preset === 'string' && settings.preset.trim()) setPreset(settings.preset);
        if (typeof settings?.theme === 'string' && settings.theme.trim()) setTheme(settings.theme);
        if (typeof settings?.niche === 'string' && settings.niche.trim()) setNiche(settings.niche);
        if (typeof settings?.planner_model === 'string' && settings.planner_model.trim()) setPlannerModel(settings.planner_model);
        if (typeof settings?.character_image_model === 'string' && settings.character_image_model.trim()) setCharsModel(settings.character_image_model);
        if (typeof settings?.scene_image_model === 'string' && settings.scene_image_model.trim()) setScenesModel(settings.scene_image_model);
        if (typeof settings?.max_image_requests === 'number') setMaxImageRequests(settings.max_image_requests);
        if (typeof settings?.max_chars_per_episode === 'number') setMaxCharsPerEpisode(settings.max_chars_per_episode);
        if (typeof settings?.max_panels_per_episode === 'number') setMaxPanelsPerEpisode(settings.max_panels_per_episode);
        if (typeof settings?.max_episode_duration_mins === 'number') setMaxEpisodeDurationMins(settings.max_episode_duration_mins);
        if (typeof settings?.enable_music === 'boolean') setEnableMusic(settings.enable_music);
        if (typeof settings?.music_provider === 'string' && settings.music_provider.trim()) setMusicProvider(settings.music_provider);
        if (typeof settings?.lyria_model === 'string' && settings.lyria_model.trim()) setLyriaModel(settings.lyria_model);
        if (typeof settings?.tts_provider === 'string' && settings.tts_provider.trim()) setTtsProvider(settings.tts_provider);
        if (typeof settings?.gemini_tts_model === 'string' && settings.gemini_tts_model.trim()) setGeminiTtsModel(settings.gemini_tts_model);
        if (typeof settings?.cloud_style === 'string' && settings.cloud_style.trim()) setBuildpackCloudStyle(settings.cloud_style);
        if (typeof settings?.font_style === 'string' && settings.font_style.trim()) setBuildpackFontStyle(settings.font_style);
        if (typeof settings?.subtitle_style === 'string' && settings.subtitle_style.trim()) setBuildpackSubtitleStyle(settings.subtitle_style);
        if (typeof settings?.subtitle_x === 'number') setSubtitleX(settings.subtitle_x);
        if (typeof settings?.subtitle_y === 'number') setSubtitleY(settings.subtitle_y);
        if (typeof settings?.subtitle_scale === 'number') setSubtitleScale(settings.subtitle_scale);
        if (typeof settings?.cloud_x === 'number') setCloudX(settings.cloud_x);
        if (typeof settings?.cloud_y === 'number') setCloudY(settings.cloud_y);
        if (typeof settings?.cloud_w === 'number') setCloudW(settings.cloud_w);
        if (typeof settings?.cloud_h === 'number') setCloudH(settings.cloud_h);
        if (typeof settings?.episodes_mode === 'string' && settings.episodes_mode.trim()) setEpisodesMode(settings.episodes_mode);
        if (typeof settings?.episode_mode === 'boolean') setEpisodeMode(settings.episode_mode);
        if (typeof settings?.episode === 'number') setTargetEpisode(String(settings.episode));
        if (typeof settings?.start_frame_path === 'string') setStartFramePath(settings.start_frame_path);
        if (typeof settings?.end_frame_path === 'string') setEndFramePath(settings.end_frame_path);
      } catch {
        // Keep current prompt when there is no stored session prompt.
      }
    };
    loadSavedPrompt();
  }, [sessionMode, sessionPath, projectNameUserEdited]);

  useEffect(() => {
    const loadPlannerCharPrompts = async () => {
      if (page !== 'workspace' || !sessionPath) {
        setCharPromptItems([]);
        return;
      }
      try {
        const res = await axios.get(`${API_BASE}/agents/autoanimator/char-prompts`, { params: { session_path: sessionPath } });
        const rows = Array.isArray(res.data?.char_prompts) ? res.data.char_prompts : [];
        setCharPromptItems(rows.map((r) => ({ name: r.name, visual_prompt: r.visual_prompt || '' })));
      } catch {
        setCharPromptItems([]);
      }
    };

    loadPlannerCharPrompts();
  }, [page, sessionPath, workflowHashes.planner]);

  useEffect(() => {
    if (sessionMode !== 'existing') {
      setEpisodesMode('new');
      setEpisodeMode(true);
      setTargetEpisode('');
      return;
    }
    setEpisodesMode((prev) => (prev === 'new' ? 'continue' : prev));
  }, [sessionMode]);

  useEffect(() => {
    const loadLocks = async () => {
      if (!sessionPath) return;
      try {
        const res = await axios.get(`${API_BASE}/agents/autoanimator/locks`, { params: { session_path: sessionPath } });
        const incoming = res.data?.locks || {};
        setSectionLocks((prev) => ({ ...DEFAULT_SECTION_LOCKS, ...prev, ...incoming }));
      } catch {
        setSectionLocks((prev) => ({ ...DEFAULT_SECTION_LOCKS, ...prev }));
      }
    };
    loadLocks();
  }, [sessionPath]);

  const toggleSectionLock = async (sectionKey) => {
    const next = { ...sectionLocks, [sectionKey]: !sectionLocks[sectionKey] };
    setSectionLocks(next);
    if (!sessionPath) return;
    try {
      await axios.post(`${API_BASE}/agents/autoanimator/session-sync`, {
        session_path: sessionPath,
        settings: buildSessionSettingsSnapshot(),
        locks: next,
      });
      setTreeRefreshToken((prev) => prev + 1);
    } catch {
      // Keep local lock state even if persistence fails.
    }
  };

  useEffect(() => {
    if (page !== 'workspace' || sessionMode !== 'existing' || !sessionPath) {
      return;
    }

    const intervalId = setInterval(() => {
      setTreeRefreshToken((prev) => prev + 1);
      refreshWorkflowHashes(sessionPath);
    }, 30000);

    return () => clearInterval(intervalId);
  }, [page, sessionMode, sessionPath]);

  useEffect(() => {
    const loadSessions = async () => {
      try {
        const root = await axios.get(`${API_BASE}/sessions/tree`);
        const roots = root.data.filter((item) => item.is_dir);
        const sessionOptions = [];

        for (const r of roots) {
          try {
            const sub = await axios.get(`${API_BASE}/sessions/tree`, { params: { path: r.path } });
            const match = (sub.data || []).find((item) => item.is_dir && isAutoAnimatorSessionFolderName(item.name));
            if (match) {
              sessionOptions.push(match.path);
            }
          } catch {
            // ignore missing session folders
          }
        }

        setAvailableSessions(sessionOptions);
        if (sessionMode === 'existing') {
          const urlDerivedPath = sessionId
            ? (sessionOptions.find((p) => String(p).startsWith(`${sessionId}/`)) || '')
            : '';
          const currentPath = String(sessionPath || '');
          // Do not snap back to an older session while a new one is being initialized.
          const nextPath = currentPath || (sessionOptions.includes(urlDerivedPath)
            ? urlDerivedPath
            : (sessionOptions[0] || ''));

          if (nextPath && nextPath !== sessionPath) {
            setSessionPath(nextPath);
          }

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
  }, [navigate, page, selectedAgent, sessionId, sessionMode, sessionPath]);

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
    const loadPlannerOptions = async () => {
      try {
        const res = await axios.get(`${API_BASE}/agents/autoanimator/planner-options`);
        const themes = res.data?.themes || {};
        const styles = res.data?.art_styles || {};
        const niches = res.data?.niches || {};
        const defaults = res.data?.defaults || {};
        setPlannerThemes(themes);
        setPlannerArtStyles(styles);
        setPlannerNiches(niches);
        if (sessionMode === 'new') {
          if (typeof defaults?.max_image_requests === 'number') setMaxImageRequests(defaults.max_image_requests);
          if (typeof defaults?.max_chars_per_episode === 'number') setMaxCharsPerEpisode(defaults.max_chars_per_episode);
          if (typeof defaults?.max_panels_per_episode === 'number') setMaxPanelsPerEpisode(defaults.max_panels_per_episode);
          if (typeof defaults?.max_episode_duration_mins === 'number') setMaxEpisodeDurationMins(defaults.max_episode_duration_mins);
          if (typeof defaults?.niche === 'string' && defaults.niche.trim()) setNiche(defaults.niche);
        }
        if (typeof defaults?.tts_provider === 'string' && defaults.tts_provider.trim()) setTtsProvider(defaults.tts_provider);
        if (typeof defaults?.gemini_tts_model === 'string' && defaults.gemini_tts_model.trim()) setGeminiTtsModel(defaults.gemini_tts_model);
      } catch {
        setPlannerThemes({});
        setPlannerArtStyles({});
        setPlannerNiches({});
      }
    };

    if (page === 'workspace') {
      loadPlannerOptions();
    }
  }, [page, sessionMode]);

  useEffect(() => {
    const loadGoogleModels = async () => {
      try {
        const res = await axios.get(`${API_BASE}/agents/autoanimator/google-models`);
        const byTask = res.data?.by_task || {};
        const defaults = res.data?.defaults || {};
        setAvailableModelsByTask({
          planner: Array.isArray(byTask?.planner) ? byTask.planner : [],
          chars: Array.isArray(byTask?.chars) ? byTask.chars : [],
          scenes: Array.isArray(byTask?.scenes) ? byTask.scenes : [],
        });
        setPlannerModel((prev) => prev || defaults?.planner_model || prev);
        setCharsModel((prev) => prev || defaults?.character_image_model || prev);
        setScenesModel((prev) => prev || defaults?.scene_image_model || prev);
      } catch {
        setAvailableModelsByTask({ planner: [], chars: [], scenes: [] });
      }
    };
    if (page === 'workspace') {
      loadGoogleModels();
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

  const renderHashHistoryControls = (step) => {
    const rows = normalizeHistoryRows(step);
    if (!rows.length) return null;

    return (
      <div style={{ display: 'flex', gap: '0.4rem', alignItems: 'center', flexWrap: 'wrap' }}>
        <select
          value={selectedHistoryHash?.[step] || ''}
          onChange={(e) => setSelectedHistoryHash((prev) => ({ ...prev, [step]: e.target.value }))}
          style={{ maxWidth: 260 }}
        >
          {rows.map((entry) => (
            <option key={`${step}-${entry.hash}-${entry.timestamp}`} value={entry.hash}>
              {entry.hash} | {entry.timestamp?.replace('T', ' ').slice(0, 19) || 'unknown'}
            </option>
          ))}
        </select>
        <button
          className="btn"
          type="button"
          onClick={() => revertToStepHash(step)}
          disabled={hashRevertBusy === step || !selectedHistoryHash?.[step]}
        >
          {hashRevertBusy === step ? 'Restoring...' : 'Restore'}
        </button>
      </div>
    );
  };

  useEffect(() => {
    if (!reuseSessionChars) return;
    if (!sourceCharSession && sourceCharSessions.length > 0) {
      setSourceCharSession(sourceCharSessions[0]);
    }
  }, [reuseSessionChars, sourceCharSession, sourceCharSessions]);

  useEffect(() => {
    if (reuseSessionChars) return;
    setSourceCharPath('');
    setSourceCharSession('');
  }, [reuseSessionChars]);

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
    <div className="agents-layout" style={{ display: 'flex', gap: '1rem', height: '100%', position: 'relative' }}>
      <div className="agents-toast-stack" style={{ position: 'fixed', top: 18, right: 22, zIndex: 9999, display: 'flex', flexDirection: 'column', gap: 8 }}>
        {toasts.map((t) => (
          <div
            key={t.id}
            style={{
              minWidth: 220,
              maxWidth: 360,
              padding: '0.55rem 0.75rem',
              borderRadius: 8,
              border: '1px solid var(--border-color)',
              background: t.type === 'error' ? '#4a1f1f' : '#1f3f2f',
              color: '#f4f8ff',
              boxShadow: '0 8px 24px rgba(0,0,0,0.35)',
              fontSize: '0.86rem',
            }}
          >
            {t.message}
          </div>
        ))}
      </div>
      <aside className="glass-panel agents-sidebar" style={{ width: 390, display: 'flex', flexDirection: 'column' }}>
        <section className="agents-sidebar-header" style={{ padding: '1rem', borderBottom: '1px solid var(--border-color)', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <div className="agents-sidebar-title-wrap">
            <h2 className="agents-sidebar-title" style={{ margin: 0, display: 'flex', alignItems: 'center', gap: '8px' }}>
              <Play size={20} className="text-accent" /> {AGENTS_LIST.find((a) => a.id === selectedAgent)?.name}
            </h2>
            <p className="agents-sidebar-subtitle" style={{ marginTop: '0.45rem', color: 'var(--text-muted)', fontSize: '0.9rem' }}>
              Preview-first configuration for higher quality narration and character consistency.
            </p>
          </div>
          <div className="agents-sidebar-actions" style={{ display: 'flex', gap: '0.5rem' }}>
            <button className="btn agents-action-btn" type="button" onClick={startNewSessionFromWorkspace} style={{ height: '2rem' }}>
              Start New Session
            </button>
            <button className="btn agents-action-btn" type="button" onClick={goBackToAgentSelector} style={{ height: '2rem' }}>
              Back
            </button>
          </div>
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
              <label>Project Name</label>
              <input
                type="text"
                value={projectName}
                onChange={(e) => {
                  setProjectNameUserEdited(true);
                  setProjectName(e.target.value);
                }}
                placeholder="Leave blank to let backend assign"
                style={{ width: '100%' }}
              />
            </div>
            <div className="config-control" style={{ marginTop: '0.55rem' }}>
              <label style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                <span>Preset Prompt (series source-of-truth)</span>
                <button
                  className="btn"
                  type="button"
                  onClick={(e) => { e.preventDefault(); e.stopPropagation(); toggleSectionLock('preset_prompt'); }}
                  style={{ padding: '0.2rem 0.35rem' }}
                >
                  {sectionLocks.preset_prompt ? <Lock size={14} /> : <Unlock size={14} />}
                </button>
              </label>
              <textarea
                className="planner-prompt-textarea"
                rows={5}
                wrap="soft"
                value={presetPrompt}
                onChange={(e) => setPresetPrompt(e.target.value)}
                disabled={sectionLocks.preset_prompt}
                style={{ width: '100%', resize: 'vertical', maxWidth: '100%' }}
              />
            </div>
            <div className="config-control" style={{ marginTop: '0.55rem' }}>
              <label>Narrative Prompt (episode add-on)</label>
              <textarea
                className="planner-prompt-textarea"
                rows={6}
                wrap="soft"
                value={narrativePrompt}
                onChange={(e) => setNarrativePrompt(e.target.value)}
                placeholder="Optional for continue mode when preset prompt is already set."
                style={{ width: '100%', resize: 'vertical', maxWidth: '100%' }}
              />
            </div>
            <div className="config-grid" style={{ marginTop: '0.65rem' }}>
              <div className="config-control">
                <label>Start Frame (optional)</label>
                <input
                  type="file"
                  accept="image/png,image/jpeg,image/webp"
                  onChange={(e) => {
                    const f = e.target.files && e.target.files[0] ? e.target.files[0] : null;
                    setStartFrameFile(f);
                    if (f) setStartFramePath('');
                  }}
                />
                {(startFramePath || startFrameFile) && (
                  <div style={{ marginTop: '0.25rem', color: 'var(--text-muted)', fontSize: '0.78rem' }}>
                    {startFramePath ? `Saved: ${startFramePath}` : `Pending upload: ${startFrameFile?.name || ''}`}
                  </div>
                )}
              </div>
              <div className="config-control">
                <label>End Frame (optional)</label>
                <input
                  type="file"
                  accept="image/png,image/jpeg,image/webp"
                  onChange={(e) => {
                    const f = e.target.files && e.target.files[0] ? e.target.files[0] : null;
                    setEndFrameFile(f);
                    if (f) setEndFramePath('');
                  }}
                />
                {(endFramePath || endFrameFile) && (
                  <div style={{ marginTop: '0.25rem', color: 'var(--text-muted)', fontSize: '0.78rem' }}>
                    {endFramePath ? `Saved: ${endFramePath}` : `Pending upload: ${endFrameFile?.name || ''}`}
                  </div>
                )}
              </div>
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
                <input value={targetEpisode} onChange={(e) => setTargetEpisode(e.target.value)} placeholder="e.g. 2" />
              </div>
            </div>
            <div className="config-control" style={{ marginTop: '0.65rem' }}>
              <label>
                <input type="checkbox" checked={sessionMode === 'existing' ? episodeMode : true} onChange={(e) => setEpisodeMode(e.target.checked)} disabled />
                <span style={{ marginLeft: 6 }}>
                  Episode Mode (on = continue series, off = single-video mode)
                  {sessionMode === 'existing' ? ' - locked for existing sessions' : ' - locked for new sessions'}
                </span>
              </label>
            </div>
            <div className="config-grid" style={{ marginTop: '0.65rem' }}>
              <div className="config-control">
                <label>Theme</label>
                <select value={theme} onChange={(e) => setTheme(e.target.value)} disabled={sessionMode === 'existing'}>
                  <option value="auto-select">Auto-select (LLM)</option>
                  {Object.entries(plannerThemes).map(([key, text]) => (
                    <option key={key} value={key}>{key} - {String(text).slice(0, 44)}</option>
                  ))}
                </select>
              </div>
              <div className="config-control">
                <label>Art Style</label>
                <select value={preset} onChange={(e) => setPreset(e.target.value)} disabled={sessionMode === 'existing'}>
                  <option value="auto-select">Auto-select (LLM)</option>
                  {Object.entries(plannerArtStyles).map(([key]) => (
                    <option key={key} value={key}>{key}</option>
                  ))}
                </select>
              </div>
              <div className="config-control">
                <label>Niche Bundle</label>
                <select value={niche} onChange={(e) => setNiche(e.target.value)}>
                  <option value="auto-select">Auto-select (general)</option>
                  {Object.entries(plannerNiches).map(([key, cfg]) => (
                    <option key={key} value={key}>{cfg?.label || key}</option>
                  ))}
                </select>
              </div>
            </div>
            <div className="config-control" style={{ marginTop: '0.65rem' }}>
              <label>Director Context Prompt (from selected niche)</label>
              <textarea
                className="planner-prompt-textarea"
                rows={4}
                wrap="soft"
                value={
                  niche === 'auto-select'
                    ? 'Auto-select is enabled. Director context will be chosen from the selected niche at runtime.'
                    : (selectedNicheDirectorContext || 'No director_context defined for this niche in config.')
                }
                readOnly
                style={{ width: '100%', resize: 'vertical', maxWidth: '100%', opacity: 0.9 }}
              />
            </div>
            <div className="config-grid" style={{ marginTop: '0.65rem' }}>
              <div className="config-control">
                <label>Planner Model</label>
                <select value={plannerModel} onChange={(e) => setPlannerModel(e.target.value)} disabled={sessionMode === 'existing'}>
                  {availableModelsByTask.planner.length === 0 && <option value={plannerModel}>{plannerModel}</option>}
                  {availableModelsByTask.planner.map((m) => (
                    <option key={m.name} value={m.name}>{m.name}</option>
                  ))}
                </select>
              </div>
            </div>
            <div className="config-grid" style={{ marginTop: '0.65rem' }}>
              <div className="config-control">
                <label>Max Images</label>
                <input type="number" min="1" value={maxImageRequests} onChange={(e) => setMaxImageRequests(parseInt(e.target.value, 10) || 1)} disabled={sessionMode === 'existing'} />
              </div>
              <div className="config-control">
                <label>Max Characters</label>
                <input type="number" min="1" value={maxCharsPerEpisode} onChange={(e) => setMaxCharsPerEpisode(parseInt(e.target.value, 10) || 1)} disabled={sessionMode === 'existing'} />
              </div>
            </div>
            <div className="config-grid" style={{ marginTop: '0.65rem' }}>
              <div className="config-control">
                <label>Max Panels</label>
                <input type="number" min="1" value={maxPanelsPerEpisode} onChange={(e) => setMaxPanelsPerEpisode(parseInt(e.target.value, 10) || 1)} disabled={sessionMode === 'existing'} />
              </div>
              <div className="config-control">
                <label>Max Duration (min)</label>
                <input type="number" min="1" value={maxEpisodeDurationMins} onChange={(e) => setMaxEpisodeDurationMins(parseInt(e.target.value, 10) || 1)} disabled={sessionMode === 'existing'} />
              </div>
            </div>
            <div style={{ marginTop: '0.5rem', display: 'flex', gap: '0.5rem', flexWrap: 'wrap' }}>
              <label style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                <input type="checkbox" checked={stepReset.planner} onChange={(e) => setStepReset((s) => ({ ...s, planner: e.target.checked }))} /> reset
              </label>
              <button className="btn" type="button" onClick={() => runNarrativeStep('planner')} disabled={stepBusy === 'planner'}>{stepBusy === 'planner' ? 'Running...' : 'Run Planner'}</button>
              <button className="btn" type="button" title="Redo Planner" onClick={() => runNarrativeStep('planner', { redo: true })} disabled={stepBusy === 'planner' || stepBusy === 'all'}><RotateCcw size={14} /></button>
              <span style={{ color: 'var(--text-muted)', fontSize: '0.8rem' }}>hash: {workflowHashes.planner || 'n/a'}</span>
              {renderHashHistoryControls('planner')}
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
            <div className="config-control" style={{ marginBottom: '0.6rem' }}>
              <label>Chars Model</label>
              <select value={charsModel} onChange={(e) => setCharsModel(e.target.value)}>
                {availableModelsByTask.chars.length === 0 && <option value={charsModel}>{charsModel}</option>}
                {availableModelsByTask.chars.map((m) => (
                  <option key={m.name} value={m.name}>{m.name}</option>
                ))}
              </select>
            </div>
            <div className="config-control" style={{ marginBottom: '0.6rem' }}>
              <label>Planner Character Prompts</label>
              {charPromptItems.length === 0 ? (
                <div style={{ color: 'var(--text-muted)', fontSize: '0.8rem' }}>
                  Run Planner first to populate character prompts.
                </div>
              ) : (
                <div style={{ display: 'flex', flexDirection: 'column', gap: '0.45rem' }}>
                  {charPromptItems.map((item, idx) => (
                    <div key={`${item.name}-${idx}`}>
                      <div style={{ color: 'var(--text-muted)', fontSize: '0.78rem', marginBottom: '0.2rem', display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '0.35rem' }}>
                        <span>{item.name}</span>
                        <button
                          className="btn"
                          type="button"
                          title={`Redo ${item.name}`}
                          onClick={() => redoSingleCharacter(item)}
                          disabled={charRedoBusy === item.name || stepBusy === 'chars' || stepBusy === 'all' || !sessionPath}
                          style={{ padding: '0.15rem 0.3rem' }}
                        >
                          {charRedoBusy === item.name ? <Loader2 size={12} className="animate-spin" /> : <RotateCcw size={12} />}
                        </button>
                      </div>
                      <textarea
                        rows={6}
                        value={item.visual_prompt}
                        onChange={(e) => {
                          const value = e.target.value;
                          setCharPromptItems((prev) => prev.map((p, pidx) => (pidx === idx ? { ...p, visual_prompt: value } : p)));
                        }}
                        style={{ width: '100%', resize: 'vertical', minHeight: 150 }}
                      />
                    </div>
                  ))}
                </div>
              )}
            </div>
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
                <div className="config-control" style={{ marginTop: '0.65rem' }}>
                  <label style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                    <input
                      type="checkbox"
                      checked={reuseSessionChars}
                      onChange={(e) => setReuseSessionChars(e.target.checked)}
                    />
                    Import Characters (optional)
                  </label>
                </div>
                {reuseSessionChars && (
                  <>
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
              </>
            )}
            <div style={{ marginTop: '0.5rem', display: 'flex', gap: '0.5rem', flexWrap: 'wrap' }}>
              <label style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                <input type="checkbox" checked={stepReset.chars} onChange={(e) => setStepReset((s) => ({ ...s, chars: e.target.checked }))} /> reset
              </label>
              <button className="btn" type="button" onClick={() => runNarrativeStep('chars')} disabled={stepBusy === 'chars'}>{stepBusy === 'chars' ? 'Running...' : 'Run Chars'}</button>
              <button className="btn" type="button" title="Redo Chars" onClick={() => runNarrativeStep('chars', { redo: true })} disabled={stepBusy === 'chars' || stepBusy === 'all'}><RotateCcw size={14} /></button>
              <span style={{ color: 'var(--text-muted)', fontSize: '0.8rem' }}>hash: {workflowHashes.chars || 'n/a'}</span>
              {renderHashHistoryControls('chars')}
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
            <div className="config-control" style={{ marginTop: '0.5rem' }}>
              <label>Scenes Model</label>
              <select value={scenesModel} onChange={(e) => setScenesModel(e.target.value)}>
                {availableModelsByTask.scenes.length === 0 && <option value={scenesModel}>{scenesModel}</option>}
                {availableModelsByTask.scenes.map((m) => (
                  <option key={m.name} value={m.name}>{m.name}</option>
                ))}
              </select>
            </div>
            <div style={{ marginTop: '0.5rem', display: 'flex', gap: '0.5rem', flexWrap: 'wrap' }}>
              <label style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                <input type="checkbox" checked={stepReset.scenes} onChange={(e) => setStepReset((s) => ({ ...s, scenes: e.target.checked }))} /> reset
              </label>
              <button className="btn" type="button" onClick={() => runNarrativeStep('scenes')} disabled={stepBusy === 'scenes'}>{stepBusy === 'scenes' ? 'Running...' : 'Run Scenes'}</button>
              <button className="btn" type="button" title="Redo Scenes" onClick={() => runNarrativeStep('scenes', { redo: true })} disabled={stepBusy === 'scenes' || stepBusy === 'all'}><RotateCcw size={14} /></button>
              <span style={{ color: 'var(--text-muted)', fontSize: '0.8rem' }}>hash: {workflowHashes.scenes || 'n/a'}</span>
              {renderHashHistoryControls('scenes')}
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
            <div className="config-control" style={{ marginTop: '0.5rem' }}>
              <label>TTS Provider</label>
              <select value={ttsProvider} onChange={(e) => setTtsProvider(e.target.value)}>
                <option value="edge">Edge TTS (default)</option>
                <option value="gemini">Google Gemini TTS</option>
              </select>
            </div>
            {ttsProvider === 'gemini' && (
              <div className="config-control" style={{ marginTop: '0.5rem' }}>
                <label>Gemini TTS Model</label>
                <select value={geminiTtsModel} onChange={(e) => setGeminiTtsModel(e.target.value)}>
                  <option value="models/gemini-2.5-flash-tts">Gemini 2.5 Flash TTS</option>
                  <option value="models/gemini-2.5-pro-tts">Gemini 2.5 Pro TTS</option>
                </select>
              </div>
            )}
            <div style={{ marginTop: '0.5rem', display: 'flex', gap: '0.5rem', flexWrap: 'wrap' }}>
              <label style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                <input type="checkbox" checked={stepReset.audio} onChange={(e) => setStepReset((s) => ({ ...s, audio: e.target.checked }))} /> reset
              </label>
              <button className="btn" type="button" onClick={() => runNarrativeStep('audio')} disabled={stepBusy === 'audio'}>{stepBusy === 'audio' ? 'Running...' : 'Run Audio'}</button>
              <button className="btn" type="button" title="Redo Audio" onClick={() => runNarrativeStep('audio', { redo: true })} disabled={stepBusy === 'audio' || stepBusy === 'all'}><RotateCcw size={14} /></button>
              <span style={{ color: 'var(--text-muted)', fontSize: '0.8rem' }}>hash: {workflowHashes.audio || 'n/a'}</span>
              {renderHashHistoryControls('audio')}
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
            <div className="config-grid" style={{ marginTop: '0.65rem' }}>
              <div className="config-control">
                <label>Font Style</label>
                <select value={buildpackFontStyle} onChange={(e) => setBuildpackFontStyle(e.target.value)}>
                  {(buildpackOptions?.fontstyles || []).map((opt) => (
                    <option key={opt.id} value={opt.id}>{opt.name}</option>
                  ))}
                </select>
              </div>
              <div className="config-control">
                <label>Subtitle Style</label>
                <select value={buildpackSubtitleStyle} onChange={(e) => setBuildpackSubtitleStyle(e.target.value)}>
                  {(buildpackOptions?.subtitle_styles || []).map((opt) => (
                    <option key={opt.id} value={opt.id}>{opt.name}</option>
                  ))}
                </select>
              </div>
            </div>
            <div className="config-grid" style={{ marginTop: '0.65rem' }}>
              <div className="config-control">
                <label>Cloud Style</label>
                <select value={buildpackCloudStyle} onChange={(e) => setBuildpackCloudStyle(e.target.value)}>
                  {(buildpackOptions?.cloud_styles || []).map((opt) => (
                    <option key={opt.id} value={opt.id}>{opt.name}</option>
                  ))}
                </select>
              </div>
              <div className="config-control">
                <label>Subtitle Scale</label>
                <input type="range" min="0.5" max="2.2" step="0.05" value={subtitleScale} onChange={(e) => setSubtitleScale(parseFloat(e.target.value))} />
              </div>
            </div>
            <div style={{ marginTop: '0.5rem', display: 'flex', gap: '0.5rem', flexWrap: 'wrap' }}>
              <label style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                <input type="checkbox" checked={stepReset.texts} onChange={(e) => setStepReset((s) => ({ ...s, texts: e.target.checked }))} /> reset
              </label>
              <button className="btn" type="button" onClick={() => runNarrativeStep('texts')} disabled={stepBusy === 'texts'}>{stepBusy === 'texts' ? 'Running...' : 'Run Texts'}</button>
              <button className="btn" type="button" title="Redo Texts" onClick={() => runNarrativeStep('texts', { redo: true })} disabled={stepBusy === 'texts' || stepBusy === 'all'}><RotateCcw size={14} /></button>
              <span style={{ color: 'var(--text-muted)', fontSize: '0.8rem' }}>hash: {workflowHashes.texts || 'n/a'}</span>
              {renderHashHistoryControls('texts')}
            </div>
            </fieldset>
          </details>

          <hr style={{ border: 'none', borderTop: '1px solid var(--border-color)', margin: '0.35rem 0 0.9rem' }} />

          <details open style={{ marginBottom: '0.8rem' }}>
            <summary style={{ cursor: 'pointer', color: 'var(--text-accent)', marginBottom: '0.55rem', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
              <span>Step 6 - Music</span>
              <button className="btn" type="button" onClick={(e) => { e.preventDefault(); e.stopPropagation(); toggleSectionLock('music'); }} style={{ padding: '0.2rem 0.35rem' }}>
                {sectionLocks.music ? <Lock size={14} /> : <Unlock size={14} />}
              </button>
            </summary>
            <fieldset disabled={sectionLocks.music} style={{ border: 'none', padding: 0, margin: 0 }}>
            <div className="config-control" style={{ marginTop: '0.5rem' }}>
              <label>
                <input type="checkbox" checked={enableMusic} onChange={(e) => setEnableMusic(e.target.checked)} />
                <span style={{ marginLeft: 6 }}>Enable Music Generation</span>
              </label>
            </div>
            <div className="config-control" style={{ marginTop: '0.5rem' }}>
              <label>Music Provider</label>
              <select value={musicProvider} onChange={(e) => setMusicProvider(e.target.value)}>
                <option value="strudel">Strudel</option>
                <option value="lyria">Lyria</option>
              </select>
            </div>
            {musicProvider === 'lyria' && (
              <div className="config-control" style={{ marginTop: '0.5rem' }}>
                <label>Lyria Model</label>
                <select value={lyriaModel} onChange={(e) => setLyriaModel(e.target.value)}>
                  <option value="lyria-3-clip-preview">lyria-3-clip-preview</option>
                  <option value="lyria-3-pro-preview">lyria-3-pro-preview</option>
                </select>
              </div>
            )}
            <div style={{ marginTop: '0.5rem', display: 'flex', gap: '0.5rem', flexWrap: 'wrap' }}>
              <label style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                <input type="checkbox" checked={stepReset.music} onChange={(e) => setStepReset((s) => ({ ...s, music: e.target.checked }))} /> reset
              </label>
              <button className="btn" type="button" onClick={() => runNarrativeStep('music')} disabled={stepBusy === 'music'}>{stepBusy === 'music' ? 'Running...' : 'Run Music'}</button>
              <button className="btn" type="button" title="Redo Music" onClick={() => runNarrativeStep('music', { redo: true })} disabled={stepBusy === 'music' || stepBusy === 'all'}><RotateCcw size={14} /></button>
              <span style={{ color: 'var(--text-muted)', fontSize: '0.8rem' }}>hash: {workflowHashes.music || 'n/a'}</span>
              {renderHashHistoryControls('music')}
            </div>
            </fieldset>
          </details>

          <hr style={{ border: 'none', borderTop: '1px solid var(--border-color)', margin: '0.35rem 0 0.9rem' }} />

          <details open style={{ marginBottom: '0.8rem' }}>
            <summary style={{ cursor: 'pointer', color: 'var(--text-accent)', marginBottom: '0.55rem', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
              <span>Step 7 - Video</span>
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
                <option value="youtube_widescreen">YouTube Video (16:9 + Shorts export)</option>
              </select>
            </div>
            <div style={{ marginTop: '0.5rem', display: 'flex', gap: '0.5rem', flexWrap: 'wrap' }}>
              <label style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                <input type="checkbox" checked={stepReset.video} onChange={(e) => setStepReset((s) => ({ ...s, video: e.target.checked }))} /> reset
              </label>
              <button className="btn" type="button" onClick={() => runNarrativeStep('video')} disabled={stepBusy === 'video'}>{stepBusy === 'video' ? 'Running...' : 'Run Video'}</button>
              <button className="btn" type="button" title="Redo Video" onClick={() => runNarrativeStep('video', { redo: true })} disabled={stepBusy === 'video' || stepBusy === 'all'}><RotateCcw size={14} /></button>
              <span style={{ color: 'var(--text-muted)', fontSize: '0.8rem' }}>hash: {workflowHashes.video || 'n/a'}</span>
              {renderHashHistoryControls('video')}
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

          <div style={{ marginTop: '0.9rem', color: 'var(--text-muted)', fontSize: '0.8rem', lineHeight: 1.35 }}>
            NOTE: Clicking <strong>Run AutoAnimator</strong> runs full end-to-end with preloaded default settings.
            To customize defaults, unlock at least Step 0 and Step 1 using the lock icons, edit values,
            then run step-by-step or use auto mode.
          </div>
          <button className="btn btn-primary" style={{ marginTop: '0.65rem', width: '100%' }} onClick={() => startAgent(selectedAgent)} disabled={running}>
            {running ? <Loader2 size={16} className="animate-spin" /> : <Play size={16} />} Run {AGENTS_LIST.find((a) => a.id === selectedAgent)?.name}
          </button>
        </section>
      </aside>

      <main style={{ flex: 1, display: 'flex', flexDirection: 'column', minHeight: 0 }}>
        <div style={{ flex: 1, display: 'flex', minHeight: 0, gap: '1rem' }}>
          <div className="glass-panel" style={{ width: '23%', minWidth: 260, padding: '0.75rem', display: 'flex', flexDirection: 'column', minHeight: 0 }}>
            <div style={{ margin: '0 0 0.75rem 0', display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '0.5rem' }}>
              <h3 style={{ margin: 0, fontSize: '1rem' }}>Session Files</h3>
              <button
                className="btn"
                type="button"
                title="Refresh session files"
                onClick={() => setTreeRefreshToken((prev) => prev + 1)}
                style={{ padding: '0.2rem 0.35rem' }}
              >
                <RefreshCcw size={14} />
              </button>
            </div>

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
                  <div className="display-prompt-text" style={{ maxWidth: '92%', textAlign: 'left' }}>
                    {presetPrompt?.trim() ? (
                      <>
                        <div style={{ fontSize: '0.9rem', opacity: 0.86, marginBottom: '0.35rem' }}>Preset Prompt (Series Base)</div>
                        <div style={{ whiteSpace: 'pre-wrap' }}>{presetPrompt}</div>
                        <div style={{ marginTop: '0.9rem', fontSize: '0.9rem', opacity: 0.86, marginBottom: '0.35rem' }}>Narrative Add-on</div>
                        <div style={{ whiteSpace: 'pre-wrap' }}>
                          {narrativePrompt || 'No episode add-on provided.'}
                        </div>
                      </>
                    ) : (
                      narrativePrompt || 'Enter narrative prompt to preview on canvas.'
                    )}
                  </div>
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
              {sessionPath && pipelineStartBySession[sessionPath] && (
                <span style={{ marginLeft: '8px', color: 'var(--text-accent)' }}>
                  Pipeline Start: {new Date(pipelineStartBySession[sessionPath]).toLocaleString()}
                </span>
              )}
            </div>
            {running && (
              <button className="btn" style={{ color: 'var(--danger)', padding: '0.25rem 0.5rem' }} onClick={abortCurrentJob}>
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
